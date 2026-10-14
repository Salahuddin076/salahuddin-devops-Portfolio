"""Static checks on the Terraform that `terraform validate` can't express."""

import re
import unittest

from helpers import CONFIG_DIR, PROJECT, TERRAFORM_DIR

import traffic_shift_sim

MODULE = TERRAFORM_DIR / "modules" / "ecs-service-bluegreen"
ENVS = ("dev", "staging", "prod")


def read(path):
    return path.read_text()


def module_text():
    return "\n".join(read(p) for p in sorted(MODULE.glob("*.tf")))


class ServiceModuleTests(unittest.TestCase):
    def test_code_deploy_controller_and_ignore_changes(self):
        ecs = read(MODULE / "ecs.tf")
        self.assertRegex(ecs, r'deployment_controller\s*{\s*type\s*=\s*"CODE_DEPLOY"')
        ignore = re.search(r"ignore_changes\s*=\s*\[([^\]]*)\]", ecs).group(1)
        for attr in ("task_definition", "load_balancer"):
            self.assertIn(attr, ignore)
        self.assertNotIn("deployment_circuit_breaker", ecs)

    def test_listeners_use_codedeploy_managed_default_actions(self):
        alb = read(MODULE / "alb.tf")
        # production and test listeners: one default forward each, ignored after creation
        self.assertEqual(len(re.findall(r"ignore_changes\s*=\s*\[default_action\]", alb)), 2)
        self.assertIn('resource "aws_lb" "this"', alb)
        cd = read(MODULE / "codedeploy.tf")
        self.assertIn("listener_arns = [aws_lb_listener.production.arn]", cd)
        self.assertIn("listener_arns = [aws_lb_listener.test.arn]", cd)

    def test_no_listener_rules_anywhere(self):
        # CodeDeploy rewrites listener default actions; rules are not the documented shape (ADR 0004).
        for path in TERRAFORM_DIR.rglob("*.tf"):
            with self.subTest(path=path.name):
                self.assertNotIn("aws_lb_listener_rule", read(path))

    def test_shared_platform_has_no_load_balancer(self):
        shared = "\n".join(read(p) for p in (TERRAFORM_DIR / "modules" / "shared-platform").glob("*.tf"))
        self.assertNotIn('resource "aws_lb', shared)

    def test_deployment_config_validation_matches_the_simulator(self):
        variables = read(MODULE / "variables.tf")
        block = variables.split('variable "deployment_config_name"', 1)[1].split("\nvariable ", 1)[0]
        listed = tuple(re.findall(r'"(CodeDeployDefault\.ECS\w+)"', block))
        self.assertEqual(set(listed), set(traffic_shift_sim.KNOWN_CONFIGS))

    def test_architecture_validation(self):
        self.assertIn('contains(["ARM64", "X86_64"], var.cpu_architecture)', read(MODULE / "variables.tf"))

    def test_rollback_and_alarms_wired(self):
        cd = read(MODULE / "codedeploy.tf")
        self.assertIn("aws_cloudwatch_metric_alarm.target_5xx", cd)
        self.assertIn("aws_cloudwatch_metric_alarm.p95_latency", cd)
        self.assertIn("ignore_poll_alarm_failure = false", cd)
        self.assertIn('"DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM"', read(MODULE / "variables.tf"))
        alarms = read(MODULE / "alarms.tf")
        self.assertIn('extended_statistic  = "p95"', alarms)
        self.assertIn("HTTPCode_Target_5XX_Count", alarms)

    def test_hook_names_match_managed_policy_prefix(self):
        self.assertEqual(module_text().count('function_name = "CodeDeployHook_'), 2)

    def test_no_wildcard_actions(self):
        self.assertNotRegex(module_text(), r'actions\s*=\s*\[[^\]]*"\*"')


class EnvironmentRootTests(unittest.TestCase):
    def normalized(self, env):
        text = read(TERRAFORM_DIR / "environments" / env / "main.tf")
        return re.sub(rf"\b{env}\b", "ENV", text.replace("dev, staging and prod", "ALL"))

    def test_roots_differ_only_by_environment(self):
        self.assertEqual(self.normalized("dev"), self.normalized("staging"))
        self.assertEqual(self.normalized("dev"), self.normalized("prod"))
        for name in ("variables.tf", "outputs.tf", "versions.tf", "providers.tf"):
            texts = {read(TERRAFORM_DIR / "environments" / e / name) for e in ENVS}
            self.assertEqual(len(texts), 1, name)

    def test_each_root_reads_its_settings_file(self):
        for env in ENVS:
            text = read(TERRAFORM_DIR / "environments" / env / "main.tf")
            self.assertIn(f'environment = "{env}"', text)
            self.assertIn("config/environments/${local.environment}.json", text)
            self.assertTrue((CONFIG_DIR / f"{env}.json").is_file())

    def test_lock_files_pin_the_validated_provider(self):
        dirs = [p.parent for p in TERRAFORM_DIR.rglob("versions.tf")]
        self.assertEqual(len(dirs), 6)
        for d in dirs:
            with self.subTest(dir=d.name):
                self.assertIn('version     = "6.68.0"', read(d / ".terraform.lock.hcl"))


class HygieneTests(unittest.TestCase):
    TEXT_SUFFIXES = {".py", ".tf", ".json", ".yaml", ".yml", ".md", ".example", ".hcl", ""}

    def files(self):
        for path in PROJECT.rglob("*"):
            if path.is_file() and ".terraform" not in path.parts and "__pycache__" not in path.parts \
                    and path.suffix in self.TEXT_SUFFIXES and "build" not in path.relative_to(PROJECT).parts:
                yield path

    def test_only_the_documentation_account_id(self):
        for path in self.files():
            for match in re.findall(r"(?<![\d.-])\d{12}(?![\d.])", read(path)):
                with self.subTest(path=str(path.relative_to(PROJECT))):
                    self.assertEqual(match, "123456789012")

    def test_no_todo_and_no_empty_files(self):
        marker = "TO" + "DO|FIX" + "ME"
        for path in self.files():
            with self.subTest(path=str(path.relative_to(PROJECT))):
                text = read(path)
                self.assertTrue(text.strip(), "empty file")
                self.assertNotRegex(text, marker)


if __name__ == "__main__":
    unittest.main()
