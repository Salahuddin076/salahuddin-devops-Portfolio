"""simulate_scp.py: matching, conditions and the landing zone scenarios."""

import json
import unittest

from helpers import SCP_DIR, PolicyDir, deny, scp

import check_scps
import simulate_scp
from simulate_scp import PolicySet, Request, UnsupportedCondition, evaluate_operator, simulate

ROLE = "arn:aws:iam::123456789012:role/developer"
ROOT = "arn:aws:iam::123456789012:root"
BREAK_GLASS = "arn:aws:iam::123456789012:role/LandingZoneBreakGlass"
TAGS = (("aws:RequestTag/CostCenter", "CC-1001"), ("aws:RequestTag/Owner", "payments-team"),
        ("aws:RequestTag/Environment", "prod"))
IMDS = (("ec2:MetadataHttpTokens", "required"),)

POLICIES = simulate_scp.load_policy_set()


def run(ou, action, region="us-east-1", principal=ROLE, context=(), resource=None):
    return simulate(POLICIES, ou, Request(action, region, principal, resource, tuple(context)))


def denied_by(result):
    return {f"{m.policy}/{m.sid}" for m in result.denies}


class ScenarioTests(unittest.TestCase):
    """The behaviours the README promises."""

    def test_run_instances_in_disallowed_region_is_denied_by_region_allowlist(self):
        r = run("prod", "ec2:RunInstances", "ap-southeast-1", context=TAGS + IMDS)
        self.assertTrue(r.denied)
        self.assertEqual(denied_by(r), {"region-allowlist/DenyOutsideAllowedRegions"})

    def test_create_role_in_disallowed_region_is_allowed_because_iam_is_global(self):
        r = run("prod", "iam:CreateRole", "ap-southeast-1")
        self.assertFalse(r.denied, denied_by(r))

    def test_global_services_pass_in_any_region(self):
        for action in ("organizations:DescribeOrganization", "cloudfront:CreateDistribution",
                       "route53:ChangeResourceRecordSets", "support:CreateCase", "sts:AssumeRole"):
            with self.subTest(action=action):
                self.assertFalse(run("nonprod", action, "sa-east-1").denied)

    def test_leave_organization_is_denied_everywhere(self):
        for ou in POLICIES.hierarchy:
            with self.subTest(ou=ou):
                self.assertIn("deny-leave-organization/DenyLeaveOrganization",
                              denied_by(run(ou, "organizations:LeaveOrganization")))

    def test_root_user_is_denied_in_every_ou_below_root(self):
        for ou in POLICIES.hierarchy:
            if ou == "root":
                continue
            with self.subTest(ou=ou):
                self.assertTrue(run(ou, "s3:ListAllMyBuckets", principal=ROOT).denied)

    def test_root_user_denied_by_deny_root_user_policy(self):
        self.assertIn("deny-root-user/DenyRootUserActions", denied_by(run("prod", "s3:GetObject", principal=ROOT)))

    def test_role_named_root_is_not_the_root_user(self):
        r = run("prod", "s3:GetObject", principal="arn:aws:iam::123456789012:role/root")
        self.assertFalse(r.denied, denied_by(r))

    def test_suspended_ou_denies_everything(self):
        for action in ("s3:GetObject", "iam:CreateRole", "sts:GetCallerIdentity", "support:CreateCase"):
            with self.subTest(action=action):
                r = run("suspended", action, principal=BREAK_GLASS)
                self.assertIn("deny-all/DenyAllSuspendedAccount", denied_by(r))

    def test_imdsv1_launch_denied_imdsv2_allowed(self):
        self.assertIn("require-imdsv2/RequireImdsV2OnRunInstances",
                      denied_by(run("prod", "ec2:RunInstances", context=TAGS)))
        self.assertFalse(run("prod", "ec2:RunInstances", context=TAGS + IMDS).denied)

    def test_imds_value_other_than_required_is_denied(self):
        r = run("sandbox", "ec2:RunInstances", context=(("ec2:MetadataHttpTokens", "optional"),))
        self.assertIn("require-imdsv2/RequireImdsV2OnRunInstances", denied_by(r))

    def test_missing_tags_denied_in_workloads_only(self):
        r = run("prod", "ec2:RunInstances", context=IMDS)
        self.assertEqual(len([m for m in r.denies if m.policy == "require-tags-on-create"]), 3)
        # Sandbox has no tag requirement.
        self.assertFalse(run("sandbox", "ec2:RunInstances", context=IMDS).denied)

    def test_one_missing_tag_is_enough_to_deny(self):
        r = run("nonprod", "ec2:CreateVolume", context=TAGS[:2])
        self.assertEqual(denied_by(r), {"require-tags-on-create/RequireEnvironmentTagOnCreate"})

    def test_security_services_protected_except_for_break_glass(self):
        for action in ("cloudtrail:StopLogging", "guardduty:DeleteDetector",
                       "config:StopConfigurationRecorder", "securityhub:DisableSecurityHub"):
            with self.subTest(action=action):
                self.assertTrue(run("prod", action).denied)
                self.assertFalse(run("prod", action, principal=BREAK_GLASS).denied)

    def test_region_allowlist_exempts_break_glass(self):
        self.assertFalse(run("prod", "s3:CreateBucket", "ap-southeast-1", principal=BREAK_GLASS).denied)

    def test_account_public_access_block_protected(self):
        self.assertTrue(run("workloads", "s3:PutAccountPublicAccessBlock").denied)
        self.assertFalse(run("workloads", "s3:PutBucketPublicAccessBlock").denied)

    def test_action_names_are_case_insensitive(self):
        self.assertTrue(run("sandbox", "Organizations:leaveorganization").denied)

    def test_allowed_region_regional_call_not_denied(self):
        self.assertFalse(run("prod", "s3:GetObject", "eu-west-1").denied)

    def test_path_includes_parent_ou(self):
        r = run("nonprod", "s3:GetObject")
        self.assertEqual(r.path, ["root", "workloads", "nonprod"])


class EvaluationModelTests(unittest.TestCase):
    def _set(self, files, attachments, hierarchy):
        docs = dict(files)
        docs["FullAWSAccess"] = simulate_scp.FULL_AWS_ACCESS
        return PolicySet(docs, hierarchy, attachments)

    def test_missing_allow_at_a_level_is_an_implicit_deny(self):
        ps = self._set({"d": scp(deny("D", "ec2:*"))},
                       {"root": ["FullAWSAccess"], "ou": ["d"]},
                       {"root": None, "ou": "root"})
        r = simulate(ps, "ou", Request("s3:GetObject", "us-east-1", ROLE))
        self.assertTrue(r.denied)
        self.assertEqual(r.levels_without_allow, ["ou"])

    def test_narrow_allow_list_at_ou_limits_actions(self):
        allow_s3 = scp({"Sid": "OnlyS3", "Effect": "Allow", "Action": "s3:Get*", "Resource": "*"})
        ps = self._set({"a": allow_s3}, {"root": ["FullAWSAccess"], "ou": ["a"]}, {"root": None, "ou": "root"})
        self.assertFalse(simulate(ps, "ou", Request("s3:GetObject", "us-east-1", ROLE)).denied)
        self.assertTrue(simulate(ps, "ou", Request("ec2:RunInstances", "us-east-1", ROLE)).denied)

    def test_resource_is_checked_only_when_given(self):
        r = run("prod", "ec2:RunInstances", context=TAGS, resource="arn:aws:ec2:us-east-1:123456789012:volume/vol-1")
        self.assertNotIn("require-imdsv2/RequireImdsV2OnRunInstances", denied_by(r))
        r = run("prod", "ec2:RunInstances", context=TAGS, resource="arn:aws:ec2:us-east-1:123456789012:instance/i-1")
        self.assertIn("require-imdsv2/RequireImdsV2OnRunInstances", denied_by(r))

    def test_unknown_ou_is_input_error(self):
        with self.assertRaises(check_scps.InputError):
            run("finance", "s3:GetObject")

    def test_question_mark_wildcard(self):
        self.assertTrue(check_scps.action_matches("s3:Get?bject", "s3:GetObject"))
        self.assertFalse(check_scps.action_matches("s3:Get?bject", "s3:GetObjects"))


class ConditionTests(unittest.TestCase):
    CTX = {"aws:RequestedRegion": ["eu-west-1"], "aws:PrincipalArn": [ROLE], "aws:SecureTransport": ["true"]}

    def ev(self, op, keys):
        return evaluate_operator(op, keys, self.CTX)

    def test_string_equals_and_not_equals(self):
        self.assertTrue(self.ev("StringEquals", {"aws:RequestedRegion": ["us-east-1", "eu-west-1"]}))
        self.assertFalse(self.ev("StringNotEquals", {"aws:RequestedRegion": ["us-east-1", "eu-west-1"]}))
        self.assertTrue(self.ev("StringNotEquals", {"aws:RequestedRegion": "us-east-1"}))

    def test_string_equals_is_case_sensitive_but_keys_are_not(self):
        self.assertFalse(self.ev("StringEquals", {"aws:RequestedRegion": "EU-WEST-1"}))
        self.assertTrue(self.ev("StringEquals", {"AWS:requestedregion": "eu-west-1"}))

    def test_string_like(self):
        self.assertTrue(self.ev("StringLike", {"aws:RequestedRegion": "eu-*"}))
        self.assertTrue(self.ev("StringNotLike", {"aws:RequestedRegion": "us-*"}))

    def test_arn_like_wildcards_do_not_cross_colons(self):
        self.assertTrue(self.ev("ArnLike", {"aws:PrincipalArn": "arn:aws:iam::*:role/*"}))
        self.assertFalse(self.ev("ArnLike", {"aws:PrincipalArn": "arn:aws:iam::*:root"}))
        self.assertFalse(evaluate_operator("ArnLike", {"aws:PrincipalArn": "arn:aws:*:root"},
                                           {"aws:PrincipalArn": [ROOT]}))
        self.assertTrue(self.ev("ArnNotLike", {"aws:PrincipalArn": "arn:aws:iam::*:role/LandingZoneBreakGlass"}))

    def test_bool(self):
        self.assertTrue(self.ev("Bool", {"aws:SecureTransport": "true"}))
        self.assertFalse(self.ev("Bool", {"aws:SecureTransport": "false"}))
        self.assertFalse(self.ev("Bool", {"aws:MultiFactorAuthPresent": "true"}))

    def test_null(self):
        self.assertTrue(self.ev("Null", {"aws:RequestTag/CostCenter": "true"}))
        self.assertFalse(self.ev("Null", {"aws:RequestTag/CostCenter": "false"}))
        self.assertTrue(self.ev("Null", {"aws:RequestedRegion": "false"}))

    def test_missing_key_positive_false_negated_true(self):
        self.assertFalse(self.ev("StringEquals", {"ec2:MetadataHttpTokens": "required"}))
        self.assertTrue(self.ev("StringNotEquals", {"ec2:MetadataHttpTokens": "required"}))

    def test_if_exists(self):
        self.assertTrue(self.ev("StringEqualsIfExists", {"ec2:MetadataHttpTokens": "required"}))
        self.assertFalse(self.ev("StringEqualsIfExists", {"aws:RequestedRegion": "us-east-1"}))

    def test_multiple_keys_are_anded(self):
        self.assertFalse(self.ev("StringEquals", {"aws:RequestedRegion": "eu-west-1", "aws:PrincipalArn": ROOT}))

    def test_unsupported_operator_raises(self):
        for op in ("NumericLessThan", "ForAnyValue:StringEquals", "IpAddress", "NullIfExists"):
            with self.subTest(op=op):
                with self.assertRaises(UnsupportedCondition):
                    self.ev(op, {"aws:RequestedRegion": "x"})

    def test_every_shipped_operator_is_modelled(self):
        values = check_scps.load_template_values(check_scps.DEFAULT_TEMPLATE_VALUES)
        policies, _ = check_scps.load_policies(SCP_DIR, values)
        for p in policies:
            for stmt in check_scps.statements(p.document):
                for op in (stmt.get("Condition") or {}):
                    self.assertTrue(simulate_scp.condition_operator_supported(op), f"{p.name}: {op}")

    def test_bool_condition_in_a_policy(self):
        doc = scp(deny("DenyNoMfa", "ec2:TerminateInstances",
                       Condition={"BoolIfExists": {"aws:MultiFactorAuthPresent": "false"}}))
        with PolicyDir({"mfa": doc}, {"hierarchy": {"root": None},
                                      "attachments": {"root": ["FullAWSAccess", "mfa"]}}) as d:
            ps = simulate_scp.load_policy_set(d, d / "attachments.json", None)
        no_mfa = Request("ec2:TerminateInstances", "us-east-1", ROLE, None, (("aws:MultiFactorAuthPresent", "false"),))
        mfa = Request("ec2:TerminateInstances", "us-east-1", ROLE, None, (("aws:MultiFactorAuthPresent", "true"),))
        self.assertTrue(simulate(ps, "root", no_mfa).denied)
        self.assertFalse(simulate(ps, "root", mfa).denied)
        # IfExists: an absent key makes the condition true, so the deny applies.
        self.assertTrue(simulate(ps, "root", Request("ec2:TerminateInstances", "us-east-1", ROLE)).denied)


if __name__ == "__main__":
    unittest.main()
