"""Shared test setup: put app/, scripts/ and src/hooks/ on sys.path, plus fakes."""

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT / "app"
SCRIPTS_DIR = PROJECT / "scripts"
HOOKS_DIR = PROJECT / "src" / "hooks"
FIXTURES = PROJECT / "tests" / "fixtures"
CONFIG_DIR = PROJECT / "config" / "environments"
TERRAFORM_DIR = PROJECT / "terraform"
VALUES_EXAMPLE = PROJECT / "deploy" / "values.example.json"

for p in (APP_DIR, SCRIPTS_DIR, HOOKS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from smoke import HttpResponse  # noqa: E402

TAG = "3f9c2b1e7a4d5c6b8e9f0a1b2c3d4e5f6a7b8c9d"
TASKDEF_ARN = "arn:aws:ecs:us-east-1:123456789012:task-definition/bluegreen-prod:42"
IMAGE = f"123456789012.dkr.ecr.us-east-1.amazonaws.com/bluegreen-api:{TAG}"
EVENT = {"DeploymentId": "d-EXAMPLE111", "LifecycleEventHookExecutionId": "exec-EXAMPLE222"}


class FakeHttp:
    """Answers by path. `latency_ms` sets elapsed time; `raise_on` raises for a path."""

    def __init__(self, tag=TAG, health_status=200, version_status=200, latency_ms=20.0,
                 slow=None, raise_on=None, version_body=None):
        self.tag = tag
        self.health_status = health_status
        self.version_status = version_status
        self.latency_ms = latency_ms
        self.slow = slow or {}          # request index -> latency_ms
        self.raise_on = raise_on
        self.version_body = version_body
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        index = len(self.calls) - 1
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        if self.raise_on and path == self.raise_on:
            raise OSError("connection refused")
        elapsed = self.slow.get(index, self.latency_ms) / 1000
        if path == "/version":
            body = self.version_body
            if body is None:
                body = ('{"image_tag": "%s", "version": "1.0.0"}' % self.tag).encode()
            return HttpResponse(self.version_status, body, elapsed)
        return HttpResponse(self.health_status, b'{"status": "ok"}', elapsed)


class FakeCodeDeployClient:
    """Stands in for the boto3 codedeploy client."""

    def __init__(self, appspec=None, fail_put=False, fail_get=False):
        self.puts = []
        self.appspec = appspec if appspec is not None else (
            'version: 0.0\nResources:\n  - TargetService:\n      Type: AWS::ECS::Service\n'
            f'      Properties:\n        TaskDefinition: "{TASKDEF_ARN}"\n')
        self.fail_put = fail_put
        self.fail_get = fail_get

    def put_lifecycle_event_hook_execution_status(self, **kwargs):
        self.puts.append(kwargs)
        if self.fail_put:
            raise RuntimeError("throttled")
        return {"lifecycleEventHookExecutionId": kwargs["lifecycleEventHookExecutionId"]}

    def get_deployment(self, deploymentId):
        if self.fail_get:
            raise RuntimeError("AccessDenied")
        return {"deploymentInfo": {"deploymentId": deploymentId, "revision": {
            "revisionType": "AppSpecContent", "appSpecContent": {"content": self.appspec}}}}


class FakeEcsClient:
    def __init__(self, image=IMAGE, container="app"):
        self.image = image
        self.container = container
        self.calls = []

    def describe_task_definition(self, taskDefinition):
        self.calls.append(taskDefinition)
        return {"taskDefinition": {"containerDefinitions": [
            {"name": "sidecar", "image": "public.ecr.aws/example/sidecar:1.0"},
            {"name": self.container, "image": self.image}]}}


class FakeContext:
    def __init__(self, remaining_ms=300000):
        self.remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self):
        return self.remaining_ms
