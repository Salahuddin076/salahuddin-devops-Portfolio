"""Text/YAML-level guards on the Ansible layer: the same baseline role
applies to both inventory groups, group-specific vars differ only where
genuinely different, and shared policy lives in group_vars/all.yml once."""

from __future__ import annotations

import unittest

try:
    import yaml
    HAVE_YAML = True
except ImportError:  # pragma: no cover - PyYAML isn't a project dependency
    HAVE_YAML = False

from helpers import ANSIBLE

SITE = ANSIBLE / "site.yml"
INVENTORY = ANSIBLE / "inventory" / "hosts.ini"
TASKS = ANSIBLE / "roles" / "baseline" / "tasks" / "main.yml"
HANDLERS = ANSIBLE / "roles" / "baseline" / "handlers" / "main.yml"
ALL_VARS = ANSIBLE / "group_vars" / "all.yml"
AWS_VARS = ANSIBLE / "group_vars" / "aws_hosts.yml"
ONPREM_VARS = ANSIBLE / "group_vars" / "onprem_hosts.yml"


class PlaybookAppliesToBothEstatesTests(unittest.TestCase):
    site_text = SITE.read_text()
    inventory_text = INVENTORY.read_text()

    def test_both_inventory_groups_exist(self) -> None:
        self.assertIn("[aws_hosts]", self.inventory_text)
        self.assertIn("[onprem_hosts]", self.inventory_text)

    def test_playbook_targets_both_groups_with_the_baseline_role(self) -> None:
        self.assertIn("hosts: aws_hosts", self.site_text)
        self.assertIn("hosts: onprem_hosts", self.site_text)
        self.assertEqual(self.site_text.count("- baseline"), 2)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
    def test_playbook_parses_as_two_plays_both_using_baseline(self) -> None:
        docs = yaml.safe_load(self.site_text)
        self.assertEqual(len(docs), 2)
        hosts_seen = {play["hosts"] for play in docs}
        self.assertEqual(hosts_seen, {"aws_hosts", "onprem_hosts"})
        for play in docs:
            self.assertIn("baseline", play["roles"])


class GroupVarsDivergeOnlyWhereGenuinelyDifferentTests(unittest.TestCase):
    aws_text = AWS_VARS.read_text()
    onprem_text = ONPREM_VARS.read_text()
    all_text = ALL_VARS.read_text()

    def test_package_manager_and_interface_differ_between_estates(self) -> None:
        self.assertIn("baseline_package_manager: dnf", self.aws_text)
        self.assertIn("baseline_package_manager: apt", self.onprem_text)
        self.assertIn("baseline_network_interface: eth0", self.aws_text)
        self.assertIn("baseline_network_interface: ens192", self.onprem_text)

    def test_shared_policy_lives_in_all_yml_not_duplicated_per_group(self) -> None:
        shared_keys = [
            "baseline_patch_cron_schedule",
            "baseline_ssh_permit_root_login",
            "baseline_log_shipping_endpoint",
        ]
        for key in shared_keys:
            self.assertIn(key, self.all_text)
            self.assertNotIn(key, self.aws_text, f"{key} should not be duplicated per group_vars/aws_hosts.yml")
            self.assertNotIn(key, self.onprem_text, f"{key} should not be duplicated per group_vars/onprem_hosts.yml")


class BaselineRoleCoversAllRequiredAreasTests(unittest.TestCase):
    tasks_text = TASKS.read_text()
    handlers_text = HANDLERS.read_text()

    def test_covers_patching_hardening_and_log_shipping(self) -> None:
        self.assertIn("unattended-upgrades", self.tasks_text)
        self.assertIn("dnf-automatic", self.tasks_text)
        self.assertIn("PermitRootLogin", self.tasks_text)
        self.assertIn("log-shipper.conf.j2", self.tasks_text)

    def test_handlers_do_not_use_ignore_errors(self) -> None:
        # ansible-lint (production profile) flags ignore_errors; this
        # project uses failed_when: false instead, which is what the lint
        # run this README documents actually enforces.
        self.assertNotIn("ignore_errors", self.handlers_text)

    def test_role_refuses_to_run_for_an_unknown_estate(self) -> None:
        self.assertIn('baseline_estate in ["aws", "onprem"]', self.tasks_text)


if __name__ == "__main__":
    unittest.main()
