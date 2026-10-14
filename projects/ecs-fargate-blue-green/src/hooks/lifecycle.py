"""CodeDeploy lifecycle-hook plumbing: report status exactly once, whatever happens.

CodeDeploy invokes a hook Lambda with `DeploymentId` and
`LifecycleEventHookExecutionId`, then waits until the function calls
`PutLifecycleEventHookExecutionStatus` (or the hook times out, up to an
hour later). So the one property that matters most is: every invocation
reports Succeeded or Failed exactly once. `run_hook` does the check inside
try/except/finally and reports in the finally block.

AWS access goes through small adapters (`CodeDeployAdapter`,
`EcsAdapter`). boto3 is imported lazily inside them, so the module imports
and tests run with the standard library only; tests inject fakes.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from smoke import HttpClient, SmokeConfig, SmokeResult, UrllibClient, run_smoke

SUCCEEDED = "Succeeded"
FAILED = "Failed"

_TASKDEF_IN_APPSPEC = re.compile(
    r"""["']?TaskDefinition["']?\s*:\s*["']?(arn:[^"'\s,}]+:task-definition/[^"'\s,}]+)"""
)


class StatusReporter(Protocol):
    def put_status(self, deployment_id: str, execution_id: str, status: str) -> None: ...


class ExpectedTagResolver(Protocol):
    def expected_tag(self, deployment_id: str) -> str: ...


def _client(service: str):
    import boto3  # lazy: only in Lambda, never in tests

    return boto3.client(service)


class CodeDeployAdapter:
    """Reports hook status and reads the deployment revision."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = _client("codedeploy")
        return self._client

    def put_status(self, deployment_id: str, execution_id: str, status: str) -> None:
        self.client.put_lifecycle_event_hook_execution_status(
            deploymentId=deployment_id,
            lifecycleEventHookExecutionId=execution_id,
            status=status,
        )

    def appspec_content(self, deployment_id: str) -> str:
        info = self.client.get_deployment(deploymentId=deployment_id)["deploymentInfo"]
        revision = info.get("revision") or {}
        content = (revision.get("appSpecContent") or {}).get("content")
        if not content:
            raise LookupError(f"deployment {deployment_id} has no inline AppSpec content")
        return content


class EcsAdapter:
    def __init__(self, client: Any = None) -> None:
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = _client("ecs")
        return self._client

    def container_image(self, task_definition_arn: str, container_name: str) -> str:
        taskdef = self.client.describe_task_definition(taskDefinition=task_definition_arn)["taskDefinition"]
        for container in taskdef.get("containerDefinitions", []):
            if container.get("name") == container_name:
                return container["image"]
        raise LookupError(f"no container {container_name!r} in {task_definition_arn}")


def tag_of(image: str) -> str:
    """`repo:tag` -> tag, `repo@sha256:...` -> the digest."""
    if "@" in image:
        return image.split("@", 1)[1]
    last = image.rsplit("/", 1)[-1]
    if ":" not in last:
        raise ValueError(f"image {image!r} has no tag")
    return last.rsplit(":", 1)[1]


def task_definition_from_appspec(content: str) -> str:
    match = _TASKDEF_IN_APPSPEC.search(content)
    if not match:
        raise LookupError("AppSpec content has no TaskDefinition ARN")
    return match.group(1)


class DeploymentTagResolver:
    """Expected tag = the image tag of the container in the deployed task definition."""

    def __init__(self, codedeploy: CodeDeployAdapter, ecs: EcsAdapter, container_name: str) -> None:
        self._codedeploy = codedeploy
        self._ecs = ecs
        self._container = container_name

    def expected_tag(self, deployment_id: str) -> str:
        arn = task_definition_from_appspec(self._codedeploy.appspec_content(deployment_id))
        return tag_of(self._ecs.container_image(arn, self._container))


class FixedTagResolver:
    def __init__(self, tag: str) -> None:
        self._tag = tag

    def expected_tag(self, deployment_id: str) -> str:
        return self._tag


@dataclass(frozen=True)
class HookSettings:
    """Per-hook settings, read from Lambda environment variables."""

    base_url: str
    container_name: str = "app"
    requests: int = 20
    p95_budget_ms: float = 500.0
    request_timeout_seconds: float = 5.0
    health_path: str = "/healthz"
    version_path: str = "/version"
    expected_tag_override: str = ""

    @classmethod
    def from_env(cls, url_var: str, env: Mapping[str, str] | None = None) -> "HookSettings":
        env = os.environ if env is None else env
        base_url = env.get(url_var, "").strip()
        if not base_url:
            raise ValueError(f"environment variable {url_var} is required")
        return cls(
            base_url=base_url,
            container_name=env.get("CONTAINER_NAME", "app"),
            requests=int(env.get("SMOKE_REQUESTS", "20")),
            p95_budget_ms=float(env.get("P95_BUDGET_MS", "500")),
            request_timeout_seconds=float(env.get("REQUEST_TIMEOUT_SECONDS", "5")),
            health_path=env.get("HEALTH_PATH", "/healthz"),
            version_path=env.get("VERSION_PATH", "/version"),
            expected_tag_override=env.get("EXPECTED_IMAGE_TAG", "").strip(),
        )


def log_json(record: dict) -> None:
    print(json.dumps(record, sort_keys=True, default=str), file=sys.stdout, flush=True)


def run_hook(
    event: Mapping[str, Any],
    *,
    hook_name: str,
    check: Callable[[str], SmokeResult],
    reporter: StatusReporter,
    log: Callable[[dict], None] = log_json,
) -> dict:
    """Run `check(deployment_id)` and report its outcome to CodeDeploy exactly once.

    An event without both IDs cannot be reported at all, so it raises before
    anything else happens. Otherwise the status starts as Failed and only a
    check that returns ok=True flips it; exceptions are logged and leave it
    Failed; the finally block reports it. If reporting itself fails, that
    exception propagates (one attempt, never a second report).
    """
    deployment_id = event.get("DeploymentId") if isinstance(event, Mapping) else None
    execution_id = event.get("LifecycleEventHookExecutionId") if isinstance(event, Mapping) else None
    if not deployment_id or not execution_id:
        raise ValueError("event needs DeploymentId and LifecycleEventHookExecutionId")

    status = FAILED
    detail: dict[str, Any] = {}
    try:
        result = check(deployment_id)
        detail = result.as_dict()
        status = SUCCEEDED if result.ok else FAILED
    except Exception as exc:  # any failure of the check is a Failed hook, never a silent hang
        detail = {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        reporter.put_status(deployment_id, execution_id, status)
        log({"hook": hook_name, "deployment_id": deployment_id, "status": status, **detail})
    return {"hook": hook_name, "status": status, **detail}


def build_check(
    settings: HookSettings,
    resolver: ExpectedTagResolver,
    client: HttpClient,
    remaining_ms: Callable[[], int] | None,
) -> Callable[[str], SmokeResult]:
    def check(deployment_id: str) -> SmokeResult:
        tag = settings.expected_tag_override or resolver.expected_tag(deployment_id)
        cfg = SmokeConfig(
            base_url=settings.base_url,
            expected_tag=tag,
            requests=settings.requests,
            p95_budget_ms=settings.p95_budget_ms,
            request_timeout_seconds=settings.request_timeout_seconds,
            health_path=settings.health_path,
            version_path=settings.version_path,
        )
        return run_smoke(cfg, client, remaining_ms)

    return check


def handle(
    event: Mapping[str, Any],
    context: Any,
    *,
    hook_name: str,
    url_var: str,
    env: Mapping[str, str] | None = None,
    codedeploy: CodeDeployAdapter | None = None,
    ecs: EcsAdapter | None = None,
    client: HttpClient | None = None,
    log: Callable[[dict], None] = log_json,
) -> dict:
    """Shared Lambda entry point. Every dependency can be injected."""
    codedeploy = codedeploy or CodeDeployAdapter()
    remaining = getattr(context, "get_remaining_time_in_millis", None)

    def check(deployment_id: str) -> SmokeResult:
        # Settings are parsed inside the check so a bad environment variable
        # is reported as Failed instead of escaping before the report.
        settings = HookSettings.from_env(url_var, env)
        resolver: ExpectedTagResolver
        if settings.expected_tag_override:
            resolver = FixedTagResolver(settings.expected_tag_override)
        else:
            resolver = DeploymentTagResolver(codedeploy, ecs or EcsAdapter(), settings.container_name)
        return build_check(settings, resolver, client or UrllibClient(), remaining)(deployment_id)

    return run_hook(event, hook_name=hook_name, check=check, reporter=codedeploy, log=log)
