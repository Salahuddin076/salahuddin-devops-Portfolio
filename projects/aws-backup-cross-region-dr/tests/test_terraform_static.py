"""Text-level guards on Terraform invariants that `terraform validate` cannot see."""

import re
import unittest

from helpers import PROJECT

TF = PROJECT / "terraform"
MODULE = TF / "modules" / "backup-dr"
REGIONAL = MODULE / "modules" / "regional-vault"


def read_dir(path):
    return "\n".join(p.read_text() for p in sorted(path.glob("*.tf")))


class ModuleInvariantTests(unittest.TestCase):
    module = read_dir(MODULE)
    regional = read_dir(REGIONAL)
    variables = (MODULE / "variables.tf").read_text()

    def test_provider_aliases_and_constraint(self):
        versions = (MODULE / "versions.tf").read_text()
        self.assertIn("configuration_aliases = [aws.primary, aws.dr]", versions)
        self.assertIn('version               = ">= 6.0, < 7.0"', versions)

    def test_governance_is_the_default_lock_mode(self):
        self.assertRegex(self.variables, r'variable "vault_lock_mode" \{[^}]*default\s+= "governance"')
        self.assertIn("IRREVERSIBLE", self.variables)
        self.assertIn('var.vault_lock_mode == "compliance" ? var.vault_lock_changeable_for_days : null', self.module)

    def test_lock_min_max_validation(self):
        self.assertIn("var.vault_lock_max_retention_days >= var.vault_lock_min_retention_days", self.variables)

    def test_cold_storage_gap_validated_for_both_vaults(self):
        self.assertIn("r.delete_after_days >= r.cold_storage_after_days + 90", self.variables)
        self.assertIn("r.dr_delete_after_days >= r.dr_cold_storage_after_days + 90", self.variables)

    def test_vault_policy_denies_deletion_except_break_glass(self):
        self.assertIn('"backup:DeleteRecoveryPoint"', self.regional)
        self.assertIn('"backup:UpdateRecoveryPointLifecycle"', self.regional)
        self.assertIn('test     = "ArnNotEquals"', self.regional)
        self.assertIn("values   = [var.break_glass_role_arn]", self.regional)

    def test_vaults_use_their_own_cmk_and_never_force_destroy(self):
        self.assertIn("kms_key_arn   = aws_kms_key.vault.arn", self.regional)
        self.assertIn("force_destroy = false", self.regional)
        self.assertEqual(self.regional.count("enable_key_rotation     = true"), 2)

    def test_dr_vault_in_dr_provider_and_copy_targets_it(self):
        self.assertRegex(self.module, r'module "dr_vault" \{\s+source = "\./modules/regional-vault"\s+providers = \{\s+aws = aws\.dr')
        self.assertIn("destination_vault_arn = module.dr_vault.vault_arn", self.module)

    def test_notification_key_allows_backup_service(self):
        self.assertIn('identifiers = ["backup.amazonaws.com", "events.amazonaws.com", "cloudwatch.amazonaws.com"]', self.regional)
        self.assertIn("kms_master_key_id = aws_kms_key.notify.arn", self.regional)

    def test_alarms_and_failure_events(self):
        for metric in ("NumberOfBackupJobsFailed", "NumberOfCopyJobsFailed"):
            self.assertIn(metric, self.regional)
        for detail_type in ("Backup Job State Change", "Copy Job State Change", "Restore Job State Change"):
            self.assertIn(detail_type, self.regional)
        self.assertIn('"EXPIRED"', self.regional)

    def test_default_vault_events(self):
        for event in ("BACKUP_JOB_FAILED", "COPY_JOB_FAILED", "RESTORE_JOB_COMPLETED"):
            self.assertIn(f'"{event}"', self.variables)

    def test_selection_by_tag_with_exclusion(self):
        self.assertIn('key   = "aws:ResourceTag/${var.selection_tag_key}"', self.module)
        self.assertIn('key   = "aws:ResourceTag/${var.exclude_tag_key}"', self.module)

    def test_managed_backup_and_restore_policies(self):
        self.assertIn("service-role/AWSBackupServiceRolePolicyForBackup", self.module)
        self.assertIn("service-role/AWSBackupServiceRolePolicyForRestores", self.module)

    def test_restore_testing_reads_dr_vault_and_validator_listens_for_completed(self):
        self.assertIn("include_vaults        = [module.dr_vault.vault_arn]", self.module)
        self.assertIn('"detail-type" = ["Restore Job State Change"]', self.module)
        self.assertIn('detail        = { status = ["COMPLETED"] }', self.module)
        self.assertIn('handler          = "handler.handler"', self.module)

    def test_cleanup_permissions_require_restore_test_tag(self):
        self.assertIn('variable = "aws:ResourceTag/${var.restore_validator.restore_test_tag_key}"', self.module)
        self.assertRegex(self.variables, r"early_cleanup\s+= optional\(bool, false\)")

    def test_audit_controls(self):
        for control in ("BACKUP_PLAN_MIN_FREQUENCY_AND_MIN_RETENTION_CHECK", "BACKUP_RECOVERY_POINT_ENCRYPTED",
                        "BACKUP_RESOURCES_PROTECTED_BY_CROSS_REGION"):
            self.assertIn(control, self.module)


class CallerTests(unittest.TestCase):
    def test_callers_read_the_policy_file(self):
        for caller in (MODULE / "validation-harness" / "main.tf", TF / "examples" / "basic" / "main.tf"):
            text = caller.read_text()
            self.assertIn('jsondecode(file("${path.module}/', text)
            self.assertIn("policy/backup-policy.json", text)
            self.assertIn("backup_plans", text)

    def test_no_credentials_in_providers(self):
        for path in TF.rglob("*.tf"):
            text = path.read_text()
            self.assertNotRegex(text, r"(access_key|secret_key|profile)\s*=", str(path))

    def test_lock_files_present(self):
        for d in (MODULE / "validation-harness", TF / "examples" / "basic"):
            self.assertTrue((d / ".terraform.lock.hcl").is_file(), d)

    def test_only_placeholder_account_ids(self):
        for path in list(PROJECT.rglob("*.tf")) + list(PROJECT.rglob("*.json")) + list(PROJECT.rglob("*.md")):
            for account in re.findall(r"(?<![0-9])[0-9]{12}(?![0-9])", path.read_text()):
                self.assertEqual(account, "123456789012", f"{path}: {account}")


if __name__ == "__main__":
    unittest.main()
