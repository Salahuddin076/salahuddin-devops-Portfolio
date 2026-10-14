"""check_scps.py: every rule with passing and failing cases, plus the shipped files."""

import json
import unittest

from helpers import BAD_SCPS, POLICY_DIR, SCP_DIR, PolicyDir, deny, scp

import check_scps
from check_scps import MAX_SCP_CHARS, render_template, run

GOOD = scp(deny("DenyLeave", "organizations:LeaveOrganization"))
REGION_DENY_OK = scp({
    "Sid": "DenyRegions", "Effect": "Deny",
    "NotAction": ["iam:*", "organizations:*", "cloudfront:*", "route53:*", "support:*", "sts:*", "budgets:*", "health:*"],
    "Resource": "*",
    "Condition": {"StringNotEquals": {"aws:RequestedRegion": ["eu-west-1"]}},
})


def rule_ids(scp_dir, attachments=None):
    report = run(scp_dir, attachments, None)
    return sorted({f.rule_id for f in report.findings}), report


class ShippedPolicyTests(unittest.TestCase):
    def test_shipped_policies_pass(self):
        report = run(SCP_DIR, POLICY_DIR / "attachments.json", POLICY_DIR / "template-values.json")
        self.assertEqual(report.findings, [], [f.message for f in report.findings])

    def test_every_shipped_file_is_loaded(self):
        report = run(SCP_DIR, None, POLICY_DIR / "template-values.json")
        names = {p.name for p in report.policies}
        self.assertEqual(names, {
            "deny-all", "deny-leave-organization", "deny-root-user", "protect-s3-public-access-block",
            "protect-security-services", "region-allowlist", "require-imdsv2", "require-tags-on-create",
        })

    def test_every_attached_policy_exists_and_every_policy_is_attached(self):
        amap = json.loads((POLICY_DIR / "attachments.json").read_text())
        attached = {p for ps in amap["attachments"].values() for p in ps} - {"FullAWSAccess"}
        files = {check_scps.policy_name(p) for p in SCP_DIR.iterdir()}
        self.assertEqual(attached, files)

    def test_every_target_keeps_full_aws_access_and_a_spare_slot_somewhere(self):
        amap = json.loads((POLICY_DIR / "attachments.json").read_text())
        for target, policies in amap["attachments"].items():
            self.assertIn("FullAWSAccess", policies, target)
            self.assertLessEqual(len(policies), 5, target)
        self.assertLess(len(amap["attachments"]["root"]), 5, "keep one root slot free for an emergency SCP")

    def test_shipped_sizes_well_under_limit(self):
        report = run(SCP_DIR, None, POLICY_DIR / "template-values.json")
        for p in report.policies:
            self.assertLess(p.minified_size, MAX_SCP_CHARS, p.name)


class BadFixtureTests(unittest.TestCase):
    def test_bad_fixtures_fail_every_rule_once(self):
        ids, report = rule_ids(BAD_SCPS, BAD_SCPS / "attachments.json")
        self.assertEqual(ids, ["SCP-001", "SCP-002", "SCP-003", "SCP-004", "SCP-005", "SCP-006", "SCP-007"])
        by_file = {f.subject: f.rule_id for f in report.findings}
        self.assertEqual(by_file["invalid-json.json"], "SCP-001")
        self.assertEqual(by_file["oversized.json"], "SCP-002")
        self.assertEqual(by_file["wrong-version.json"], "SCP-003")
        self.assertEqual(by_file["missing-sid.json"], "SCP-004")
        self.assertEqual(by_file["allow-star.json"], "SCP-005")
        self.assertEqual(by_file["region-deny-missing-globals.json"], "SCP-006")
        self.assertEqual(by_file["attachments.json:workloads"], "SCP-007")


class Rule001JsonTests(unittest.TestCase):
    def test_valid_json_passes(self):
        with PolicyDir({"good": GOOD}) as d:
            self.assertEqual(rule_ids(d)[0], [])

    def test_invalid_json_fails(self):
        with PolicyDir({"bad": '{"Version": "2012-10-17", "Statement": [}'}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-001"])

    def test_missing_statement_fails(self):
        with PolicyDir({"bad": {"Version": "2012-10-17"}}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-001"])

    def test_unknown_template_variable_fails(self):
        with PolicyDir({"t.json.tftpl": '{"Version": "2012-10-17", "Statement": ${jsonencode(nope)}}'}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-001"])


class Rule002SizeTests(unittest.TestCase):
    def _sized(self, n_actions: int) -> dict:
        return scp(deny("Big", [f"ec2:Describe{i:04d}" for i in range(n_actions)]))

    def test_size_counts_minified_not_pretty(self):
        doc = self._sized(230)
        pretty = json.dumps(doc, indent=4)
        self.assertGreater(len(pretty), MAX_SCP_CHARS)
        self.assertLessEqual(len(check_scps.minify(doc)), MAX_SCP_CHARS)
        with PolicyDir({"big": pretty}) as d:
            self.assertEqual(rule_ids(d)[0], [])

    def test_over_limit_fails(self):
        with PolicyDir({"big": self._sized(300)}) as d:
            ids, report = rule_ids(d)
        self.assertEqual(ids, ["SCP-002"])
        self.assertIn("5,120", report.findings[0].message)


class Rule003VersionTests(unittest.TestCase):
    def test_old_version_fails(self):
        with PolicyDir({"old": scp(deny("A", "s3:*"), version="2008-10-17")}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-003"])

    def test_missing_version_fails(self):
        with PolicyDir({"none": {"Statement": [deny("A", "s3:*")]}}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-003"])


class Rule004SidTests(unittest.TestCase):
    def test_missing_sid_fails(self):
        with PolicyDir({"p": scp({"Effect": "Deny", "Action": "s3:*", "Resource": "*"})}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-004"])

    def test_duplicate_sid_fails(self):
        with PolicyDir({"p": scp(deny("Same", "s3:*"), deny("Same", "ec2:*"))}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-004"])

    def test_single_statement_object_is_accepted(self):
        with PolicyDir({"p": {"Version": "2012-10-17", "Statement": deny("Only", "s3:*")}}) as d:
            self.assertEqual(rule_ids(d)[0], [])


class Rule005AllowWildcardTests(unittest.TestCase):
    def test_allow_star_fails(self):
        with PolicyDir({"p": scp({"Sid": "A", "Effect": "Allow", "Action": "*", "Resource": "*"})}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-005"])

    def test_allow_service_wildcard_fails(self):
        with PolicyDir({"p": scp({"Sid": "A", "Effect": "Allow", "Action": ["s3:GetObject", "ec2:*"], "Resource": "*"})}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-005"])

    def test_allow_not_action_fails(self):
        with PolicyDir({"p": scp({"Sid": "A", "Effect": "Allow", "NotAction": "iam:*", "Resource": "*"})}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-005"])

    def test_explicit_allow_list_passes(self):
        with PolicyDir({"p": scp({"Sid": "A", "Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "*"})}) as d:
            self.assertEqual(rule_ids(d)[0], [])

    def test_deny_star_passes(self):
        with PolicyDir({"p": scp(deny("DenyAll", "*"))}) as d:
            self.assertEqual(rule_ids(d)[0], [])


class Rule006RegionDenyTests(unittest.TestCase):
    def test_complete_exemptions_pass(self):
        with PolicyDir({"r": REGION_DENY_OK}) as d:
            self.assertEqual(rule_ids(d)[0], [])

    def test_missing_iam_fails_and_names_it(self):
        doc = json.loads(json.dumps(REGION_DENY_OK))
        doc["Statement"][0]["NotAction"].remove("iam:*")
        with PolicyDir({"r": doc}) as d:
            ids, report = rule_ids(d)
        self.assertEqual(ids, ["SCP-006"])
        self.assertIn("iam:CreateRole", report.findings[0].message)

    def test_specific_actions_can_satisfy_the_exemption(self):
        doc = json.loads(json.dumps(REGION_DENY_OK))
        doc["Statement"][0]["NotAction"] = [a for a in doc["Statement"][0]["NotAction"] if a != "sts:*"] + ["sts:AssumeRole"]
        with PolicyDir({"r": doc}) as d:
            self.assertEqual(rule_ids(d)[0], [])

    def test_region_deny_with_action_fails(self):
        doc = scp(deny("DenyRegions", "*", Condition={"StringNotEquals": {"aws:RequestedRegion": "eu-west-1"}}))
        with PolicyDir({"r": doc}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-006"])

    def test_condition_key_match_is_case_insensitive(self):
        doc = json.loads(json.dumps(REGION_DENY_OK))
        doc["Statement"][0]["NotAction"] = ["s3:ListAllMyBuckets"]
        doc["Statement"][0]["Condition"] = {"StringNotEquals": {"AWS:REQUESTEDREGION": "eu-west-1"}}
        with PolicyDir({"r": doc}) as d:
            self.assertEqual(rule_ids(d)[0], ["SCP-006"])

    def test_non_region_deny_is_not_checked(self):
        with PolicyDir({"r": scp(deny("DenyS3", "s3:*"))}) as d:
            self.assertEqual(rule_ids(d)[0], [])


class Rule007And008AttachmentTests(unittest.TestCase):
    def _amap(self, attachments):
        return {"hierarchy": {k: None for k in attachments}, "attachments": attachments}

    def test_five_attachments_pass(self):
        files = {f"p{i}": scp(deny(f"S{i}", "s3:*")) for i in range(4)}
        with PolicyDir(files, self._amap({"root": ["FullAWSAccess", "p0", "p1", "p2", "p3"]})) as d:
            self.assertEqual(rule_ids(d, d / "attachments.json")[0], [])

    def test_six_attachments_fail(self):
        files = {f"p{i}": scp(deny(f"S{i}", "s3:*")) for i in range(5)}
        with PolicyDir(files, self._amap({"root": ["FullAWSAccess", "p0", "p1", "p2", "p3", "p4"]})) as d:
            self.assertEqual(rule_ids(d, d / "attachments.json")[0], ["SCP-007"])

    def test_duplicate_attachment_fails(self):
        with PolicyDir({"p0": GOOD}, self._amap({"root": ["FullAWSAccess", "p0", "p0"]})) as d:
            self.assertEqual(rule_ids(d, d / "attachments.json")[0], ["SCP-007"])

    def test_unknown_policy_fails(self):
        with PolicyDir({"p0": GOOD}, self._amap({"root": ["FullAWSAccess", "p0", "ghost"]})) as d:
            self.assertEqual(rule_ids(d, d / "attachments.json")[0], ["SCP-008"])

    def test_malformed_attachment_map_is_input_error(self):
        with PolicyDir({"p0": GOOD}, {"attachments": {"root": "FullAWSAccess"}}) as d:
            with self.assertRaises(check_scps.InputError):
                run(d, d / "attachments.json", None)


class TemplateTests(unittest.TestCase):
    def test_render_uses_json_encoding(self):
        out = render_template('{"r": ${jsonencode(regions)}}', {"regions": ["eu-west-1", "us-east-1"]})
        self.assertEqual(json.loads(out), {"r": ["eu-west-1", "us-east-1"]})

    def test_other_template_syntax_is_rejected(self):
        with self.assertRaises(ValueError):
            render_template('{"r": "${upper(x)}"}', {"x": "a"})
        with self.assertRaises(ValueError):
            render_template('%{ for r in x }${r}%{ endfor }', {"x": []})

    def test_shipped_template_renders_the_allowed_regions(self):
        values = check_scps.load_template_values(POLICY_DIR / "template-values.json")
        text = render_template((SCP_DIR / "region-allowlist.json.tftpl").read_text(), values)
        cond = json.loads(text)["Statement"][0]["Condition"]
        self.assertEqual(cond["StringNotEquals"]["aws:RequestedRegion"], values["allowed_regions"])
        self.assertEqual(cond["ArnNotLike"]["aws:PrincipalArn"], values["exempt_principal_arns"])


if __name__ == "__main__":
    unittest.main()
