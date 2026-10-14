"""Lifecycle hooks: pass, fail and exception paths; status reported exactly once."""

import unittest

from helpers import (EVENT, IMAGE, TAG, TASKDEF_ARN, FakeCodeDeployClient, FakeContext, FakeEcsClient,
                     FakeHttp)

import after_allow_traffic
import before_allow_traffic
from lifecycle import (FAILED, SUCCEEDED, CodeDeployAdapter, EcsAdapter, HookSettings, run_hook,
                       tag_of, task_definition_from_appspec)
from smoke import SmokeResult

TEST_ENV = {"TEST_BASE_URL": "https://api.example.com:8445", "SMOKE_REQUESTS": "10",
            "P95_BUDGET_MS": "300", "REQUEST_TIMEOUT_SECONDS": "3", "CONTAINER_NAME": "app"}
PROD_ENV = {"PROD_BASE_URL": "https://api.example.com", "SMOKE_REQUESTS": "5", "P95_BUDGET_MS": "300"}


def invoke(module, env, http=None, cd_client=None, ecs_client=None, context=None, event=EVENT):
    cd_client = cd_client or FakeCodeDeployClient()
    logs = []
    result = module.handler(
        event, context or FakeContext(), env=env, codedeploy=CodeDeployAdapter(cd_client),
        ecs=EcsAdapter(ecs_client or FakeEcsClient()), client=http or FakeHttp(), log=logs.append)
    return result, cd_client, logs


class BeforeAllowTrafficTests(unittest.TestCase):
    def test_pass_reports_succeeded_once(self):
        http = FakeHttp()
        result, cd, logs = invoke(before_allow_traffic, TEST_ENV, http)
        self.assertEqual(result["status"], SUCCEEDED, result)
        self.assertEqual(cd.puts, [{"deploymentId": "d-EXAMPLE111",
                                    "lifecycleEventHookExecutionId": "exec-EXAMPLE222",
                                    "status": "Succeeded"}])
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["hook"], "BeforeAllowTraffic")

    def test_targets_the_test_listener(self):
        http = FakeHttp()
        invoke(before_allow_traffic, TEST_ENV, http)
        self.assertTrue(all(url.startswith("https://api.example.com:8445/") for url, _ in http.calls))
        self.assertEqual(len(http.calls), 1 + 1 + 10)   # health, version, 10 latency samples
        self.assertTrue(all(timeout == 3.0 for _, timeout in http.calls))

    def test_expected_tag_comes_from_the_deployed_task_definition(self):
        ecs = FakeEcsClient()
        result, _, _ = invoke(before_allow_traffic, TEST_ENV, ecs_client=ecs)
        self.assertEqual(ecs.calls, [TASKDEF_ARN])
        self.assertEqual(result["expected_tag"], TAG)

    def test_version_mismatch_fails(self):
        result, cd, _ = invoke(before_allow_traffic, TEST_ENV, FakeHttp(tag="0" * 40))
        self.assertEqual(result["status"], FAILED)
        self.assertEqual([p["status"] for p in cd.puts], ["Failed"])
        self.assertTrue(any("image_tag" in f for f in result["failures"]))

    def test_health_failure_fails_without_sampling(self):
        http = FakeHttp(health_status=503)
        result, cd, _ = invoke(before_allow_traffic, TEST_ENV, http)
        self.assertEqual(result["status"], FAILED)
        self.assertEqual(len(http.calls), 1)
        self.assertEqual(len(cd.puts), 1)

    def test_latency_budget_breach_fails(self):
        http = FakeHttp(latency_ms=450)
        result, cd, _ = invoke(before_allow_traffic, TEST_ENV, http)
        self.assertEqual(result["status"], FAILED)
        self.assertEqual(result["p95_ms"], 450.0)
        self.assertEqual(len(cd.puts), 1)

    def test_one_slow_request_in_ten_breaches_nearest_rank_p95(self):
        # nearest-rank p95 of 10 samples is the 10th: one slow request fails it.
        http = FakeHttp(slow={11: 900})
        result, _, _ = invoke(before_allow_traffic, TEST_ENV, http)
        self.assertEqual(result["status"], FAILED)
        self.assertEqual(result["p95_ms"], 900.0)

    def test_http_exception_reports_failed_once(self):
        result, cd, logs = invoke(before_allow_traffic, TEST_ENV, FakeHttp(raise_on="/healthz"))
        self.assertEqual(result["status"], FAILED)
        self.assertIn("OSError", result["error"])
        self.assertEqual(len(cd.puts), 1)
        self.assertEqual(logs[0]["status"], "Failed")

    def test_aws_lookup_exception_reports_failed_once(self):
        cd = FakeCodeDeployClient(fail_get=True)
        result, cd, _ = invoke(before_allow_traffic, TEST_ENV, cd_client=cd)
        self.assertEqual(result["status"], FAILED)
        self.assertIn("AccessDenied", result["error"])
        self.assertEqual([p["status"] for p in cd.puts], ["Failed"])

    def test_missing_url_env_reports_failed_once(self):
        result, cd, _ = invoke(before_allow_traffic, {})
        self.assertEqual(result["status"], FAILED)
        self.assertIn("TEST_BASE_URL", result["error"])
        self.assertEqual(len(cd.puts), 1)

    def test_bad_numeric_env_reports_failed_once(self):
        result, cd, _ = invoke(before_allow_traffic, {**TEST_ENV, "SMOKE_REQUESTS": "ten"})
        self.assertEqual(result["status"], FAILED)
        self.assertEqual(len(cd.puts), 1)

    def test_expected_tag_override_skips_aws_lookup(self):
        ecs = FakeEcsClient()
        result, _, _ = invoke(before_allow_traffic, {**TEST_ENV, "EXPECTED_IMAGE_TAG": TAG}, ecs_client=ecs)
        self.assertEqual(result["status"], SUCCEEDED)
        self.assertEqual(ecs.calls, [])

    def test_out_of_lambda_time_fails_before_timeout(self):
        result, cd, _ = invoke(before_allow_traffic, TEST_ENV, context=FakeContext(remaining_ms=4000))
        self.assertEqual(result["status"], FAILED)
        self.assertIn("not enough Lambda time", result["failures"][0])
        self.assertEqual(len(cd.puts), 1)

    def test_reporting_failure_propagates_after_one_attempt(self):
        cd = FakeCodeDeployClient(fail_put=True)
        with self.assertRaises(RuntimeError):
            invoke(before_allow_traffic, TEST_ENV, cd_client=cd)
        self.assertEqual(len(cd.puts), 1)

    def test_event_without_ids_raises_and_reports_nothing(self):
        cd = FakeCodeDeployClient()
        for event in ({}, {"DeploymentId": "d-1"}, {"LifecycleEventHookExecutionId": "e-1"}, None):
            with self.subTest(event=event), self.assertRaises(ValueError):
                invoke(before_allow_traffic, TEST_ENV, cd_client=cd, event=event)
        self.assertEqual(cd.puts, [])


class AfterAllowTrafficTests(unittest.TestCase):
    def test_pass_targets_the_production_listener(self):
        http = FakeHttp()
        result, cd, logs = invoke(after_allow_traffic, PROD_ENV, http)
        self.assertEqual(result["status"], SUCCEEDED, result)
        self.assertTrue(all(url.startswith("https://api.example.com/") for url, _ in http.calls))
        self.assertEqual(len(cd.puts), 1)
        self.assertEqual(logs[0]["hook"], "AfterAllowTraffic")

    def test_old_version_still_served_fails(self):
        result, cd, _ = invoke(after_allow_traffic, PROD_ENV, FakeHttp(tag="previous-tag"))
        self.assertEqual(result["status"], FAILED)
        self.assertEqual([p["status"] for p in cd.puts], ["Failed"])

    def test_ignores_the_test_listener_variable(self):
        result, cd, _ = invoke(after_allow_traffic, {"TEST_BASE_URL": "https://api.example.com:8445"})
        self.assertEqual(result["status"], FAILED)
        self.assertIn("PROD_BASE_URL", result["error"])
        self.assertEqual(len(cd.puts), 1)

    def test_non_json_version_fails(self):
        result, _, _ = invoke(after_allow_traffic, PROD_ENV, FakeHttp(version_body=b"<html>"))
        self.assertEqual(result["status"], FAILED)


class RunHookTests(unittest.TestCase):
    class Reporter:
        def __init__(self):
            self.calls = []

        def put_status(self, deployment_id, execution_id, status):
            self.calls.append((deployment_id, execution_id, status))

    def test_base_exception_still_reports_then_propagates(self):
        reporter = self.Reporter()

        def check(_):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            run_hook(EVENT, hook_name="t", check=check, reporter=reporter, log=lambda r: None)
        self.assertEqual(reporter.calls, [("d-EXAMPLE111", "exec-EXAMPLE222", "Failed")])

    def test_ok_result_reports_succeeded(self):
        reporter = self.Reporter()
        out = run_hook(EVENT, hook_name="t", reporter=reporter, log=lambda r: None,
                       check=lambda _: SmokeResult(ok=True, base_url="https://x.example.com", expected_tag="a"))
        self.assertEqual(out["status"], "Succeeded")
        self.assertEqual(len(reporter.calls), 1)

    def test_not_ok_result_reports_failed(self):
        reporter = self.Reporter()
        run_hook(EVENT, hook_name="t", reporter=reporter, log=lambda r: None,
                 check=lambda _: SmokeResult(ok=False, base_url="https://x.example.com", expected_tag="a"))
        self.assertEqual(reporter.calls[0][2], "Failed")


class HelperTests(unittest.TestCase):
    def test_tag_of(self):
        self.assertEqual(tag_of(IMAGE), TAG)
        self.assertEqual(tag_of("localhost:5000/team/app:v1.2"), "v1.2")
        digest = "sha256:" + "a" * 64
        self.assertEqual(tag_of(f"example/app@{digest}"), digest)
        with self.assertRaises(ValueError):
            tag_of("localhost:5000/team/app")

    def test_task_definition_from_yaml_and_json_appspec(self):
        self.assertEqual(task_definition_from_appspec(f'TaskDefinition: "{TASKDEF_ARN}"'), TASKDEF_ARN)
        self.assertEqual(task_definition_from_appspec(f"TaskDefinition: {TASKDEF_ARN}\n"), TASKDEF_ARN)
        self.assertEqual(task_definition_from_appspec(f'{{"TaskDefinition": "{TASKDEF_ARN}"}}'), TASKDEF_ARN)
        with self.assertRaises(LookupError):
            task_definition_from_appspec("version: 0.0")

    def test_settings_from_env(self):
        s = HookSettings.from_env("TEST_BASE_URL", TEST_ENV)
        self.assertEqual((s.base_url, s.requests, s.p95_budget_ms), ("https://api.example.com:8445", 10, 300.0))
        with self.assertRaises(ValueError):
            HookSettings.from_env("TEST_BASE_URL", {})

    def test_adapters_do_not_import_boto3_on_construction(self):
        CodeDeployAdapter()
        EcsAdapter()


if __name__ == "__main__":
    unittest.main()
