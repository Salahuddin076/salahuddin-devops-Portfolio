"""Every policy rule, with passing and failing cases."""

import datetime as dt
import unittest

from helpers import GOOD_PAB, change, plan, policy_json

import check_plan

TODAY = dt.date(2026, 10, 14)


def run(p):
    return check_plan.evaluate(p, "plan.json", [], TODAY)


def ids(report):
    return sorted((f.rule_id, f.address) for f in report.active)


class S3PublicAccessBlockTests(unittest.TestCase):
    def test_bucket_with_full_block_matched_by_name_passes(self):
        r = run(plan(change("aws_s3_bucket.a", {"bucket": "example-a"}),
                     change("aws_s3_bucket_public_access_block.a", {"bucket": "example-a", **GOOD_PAB})))
        self.assertEqual(ids(r), [])

    def test_bucket_matched_by_configuration_reference_passes(self):
        # New bucket: the PAB's bucket is unknown at plan time, only the reference links them.
        cfg = {"resources": [{"address": "aws_s3_bucket_public_access_block.a",
                              "expressions": {"bucket": {"references": ["aws_s3_bucket.a.id", "aws_s3_bucket.a"]}}}]}
        r = run(plan(change("aws_s3_bucket.a", {"bucket": "example-a"}),
                     change("aws_s3_bucket_public_access_block.a", dict(GOOD_PAB)), configuration=cfg))
        self.assertEqual(ids(r), [])

    def test_bucket_without_block_fails(self):
        r = run(plan(change("aws_s3_bucket.a", {"bucket": "example-a"})))
        self.assertEqual(ids(r), [("CSP-S3-001", "aws_s3_bucket.a")])

    def test_block_for_another_bucket_does_not_count(self):
        r = run(plan(change("aws_s3_bucket.a", {"bucket": "example-a"}),
                     change("aws_s3_bucket_public_access_block.b", {"bucket": "example-b", **GOOD_PAB})))
        self.assertEqual(ids(r), [("CSP-S3-001", "aws_s3_bucket.a")])

    def test_each_flag_false_fails(self):
        for flag in check_plan.PAB_FLAGS:
            with self.subTest(flag=flag):
                pab = {"bucket": "example-a", **GOOD_PAB, flag: False}
                r = run(plan(change("aws_s3_bucket.a", {"bucket": "example-a"}),
                             change("aws_s3_bucket_public_access_block.a", pab)))
                self.assertEqual(ids(r), [("CSP-S3-001", "aws_s3_bucket_public_access_block.a")])
                self.assertIn(flag, r.active[0].message)

    def test_missing_flag_counts_as_not_true(self):
        pab = {"bucket": "example-a", "block_public_acls": True}
        r = run(plan(change("aws_s3_bucket.a", {"bucket": "example-a"}),
                     change("aws_s3_bucket_public_access_block.a", pab)))
        self.assertEqual(r.active[0].rule_id, "CSP-S3-001")

    def test_destroyed_bucket_is_ignored(self):
        r = run(plan(change("aws_s3_bucket.old", None, actions=("delete",))))
        self.assertEqual(r.resources_checked, 0)
        self.assertEqual(ids(r), [])


def sg_ingress(from_port, to_port, protocol="tcp", cidrs=(), v6=()):
    return {"from_port": from_port, "to_port": to_port, "protocol": protocol,
            "cidr_blocks": list(cidrs), "ipv6_cidr_blocks": list(v6)}


class SecurityGroupTests(unittest.TestCase):
    def sg(self, *ingress):
        return run(plan(change("aws_security_group.s", {"ingress": list(ingress)})))

    def test_https_from_anywhere_passes(self):
        self.assertEqual(ids(self.sg(sg_ingress(443, 443, cidrs=["0.0.0.0/0"], v6=["::/0"]))), [])

    def test_ssh_from_private_range_passes(self):
        self.assertEqual(ids(self.sg(sg_ingress(22, 22, cidrs=["10.0.0.0/8"]))), [])

    def test_ssh_from_ipv4_anywhere_fails(self):
        r = self.sg(sg_ingress(22, 22, cidrs=["0.0.0.0/0"]))
        self.assertEqual(ids(r), [("CSP-SG-001", "aws_security_group.s")])
        self.assertIn("port 22", r.active[0].message)

    def test_rdp_from_ipv6_anywhere_fails(self):
        r = self.sg(sg_ingress(3389, 3389, v6=["::/0"]))
        self.assertIn("::/0 on port 3389", r.active[0].message)

    def test_port_range_covering_ssh_fails(self):
        self.assertEqual(len(self.sg(sg_ingress(0, 1024, cidrs=["0.0.0.0/0"])).active), 1)

    def test_all_protocols_fails(self):
        r = self.sg(sg_ingress(0, 0, protocol="-1", cidrs=["0.0.0.0/0"]))
        self.assertIn("port 22", r.active[0].message)
        self.assertIn("port 3389", r.active[0].message)

    def test_udp_on_port_22_passes(self):
        self.assertEqual(ids(self.sg(sg_ingress(22, 22, protocol="udp", cidrs=["0.0.0.0/0"]))), [])

    def test_standalone_security_group_rule(self):
        bad = change("aws_security_group_rule.r", {"type": "ingress", "from_port": 22, "to_port": 22,
                                                   "protocol": "tcp", "cidr_blocks": ["0.0.0.0/0"]})
        egress = change("aws_security_group_rule.e", {"type": "egress", "from_port": 0, "to_port": 0,
                                                      "protocol": "-1", "cidr_blocks": ["0.0.0.0/0"]})
        self.assertEqual(ids(run(plan(bad, egress))), [("CSP-SG-001", "aws_security_group_rule.r")])

    def test_vpc_ingress_rule_resource(self):
        bad = change("aws_vpc_security_group_ingress_rule.r", {"from_port": 3389, "to_port": 3389,
                                                               "ip_protocol": "tcp", "cidr_ipv4": "0.0.0.0/0"})
        ok = change("aws_vpc_security_group_ingress_rule.ok", {"from_port": 22, "to_port": 22,
                                                               "ip_protocol": "tcp", "cidr_ipv4": "203.0.113.0/24"})
        self.assertEqual(ids(run(plan(bad, ok))), [("CSP-SG-001", "aws_vpc_security_group_ingress_rule.r")])


class IamWildcardTests(unittest.TestCase):
    def pol(self, *stmts, rtype="aws_iam_policy"):
        return run(plan(change(f"{rtype}.p", {"policy": policy_json(*stmts)})))

    def test_scoped_policy_passes(self):
        self.assertEqual(ids(self.pol({"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::example-*/*"})), [])

    def test_action_star_on_specific_resource_passes(self):
        self.assertEqual(ids(self.pol({"Effect": "Allow", "Action": "*", "Resource": "arn:aws:s3:::example-a"})), [])

    def test_specific_action_on_resource_star_passes(self):
        self.assertEqual(ids(self.pol({"Effect": "Allow", "Action": ["ec2:Describe*"], "Resource": "*"})), [])

    def test_deny_star_star_passes(self):
        self.assertEqual(ids(self.pol({"Effect": "Deny", "Action": "*", "Resource": "*"})), [])

    def test_allow_star_star_fails_for_every_policy_type(self):
        for rtype in check_plan.IAM_POLICY_TYPES:
            with self.subTest(rtype=rtype):
                r = self.pol({"Sid": "Admin", "Effect": "Allow", "Action": "*", "Resource": "*"}, rtype=rtype)
                self.assertEqual(ids(r), [("CSP-IAM-001", f"{rtype}.p")])
                self.assertIn("'Admin'", r.active[0].message)

    def test_star_inside_lists_fails(self):
        r = self.pol({"Effect": "Allow", "Action": ["s3:GetObject", "*"], "Resource": ["arn:aws:s3:::x", "*"]})
        self.assertEqual(len(r.active), 1)

    def test_single_statement_object_form(self):
        doc = '{"Version": "2012-10-17", "Statement": {"Effect": "Allow", "Action": "*", "Resource": "*"}}'
        r = run(plan(change("aws_iam_policy.p", {"policy": doc})))
        self.assertEqual(len(r.active), 1)

    def test_unknown_policy_is_skipped(self):
        self.assertEqual(ids(run(plan(change("aws_iam_policy.p", {"name": "computed"})))), [])

    def test_invalid_json_fails_closed(self):
        r = run(plan(change("aws_iam_policy.p", {"policy": "{not json"})))
        self.assertEqual(r.active[0].rule_id, "CSP-IAM-001")


class RdsEncryptionTests(unittest.TestCase):
    def test_encrypted_instance_and_cluster_pass(self):
        r = run(plan(change("aws_db_instance.d", {"storage_encrypted": True}),
                     change("aws_rds_cluster.c", {"storage_encrypted": True})))
        self.assertEqual(ids(r), [])

    def test_unencrypted_or_unset_fails(self):
        r = run(plan(change("aws_db_instance.d", {"storage_encrypted": False}),
                     change("aws_rds_cluster.c", {"engine": "aurora-postgresql"})))
        self.assertEqual(ids(r), [("CSP-RDS-001", "aws_db_instance.d"), ("CSP-RDS-001", "aws_rds_cluster.c")])


class CloudTrailTests(unittest.TestCase):
    def test_validation_enabled_passes(self):
        self.assertEqual(ids(run(plan(change("aws_cloudtrail.t", {"enable_log_file_validation": True})))), [])

    def test_validation_disabled_is_medium(self):
        r = run(plan(change("aws_cloudtrail.t", {"enable_log_file_validation": False})))
        self.assertEqual(ids(r), [("CSP-CT-001", "aws_cloudtrail.t")])
        self.assertEqual(r.active[0].severity, "MEDIUM")
        self.assertFalse(r.failed, "a MEDIUM finding alone must not fail the gate")


class PublicAlbWafTests(unittest.TestCase):
    ALB = {"internal": False, "load_balancer_type": "application"}

    def test_public_alb_without_waf_warns(self):
        r = run(plan(change("aws_lb.pub", dict(self.ALB))))
        self.assertEqual(ids(r), [("CSP-WAF-001", "aws_lb.pub")])
        self.assertEqual(r.active[0].severity, "MEDIUM")
        self.assertFalse(r.failed)

    def test_internal_alb_and_nlb_are_ignored(self):
        r = run(plan(change("aws_lb.int", {"internal": True, "load_balancer_type": "application"}),
                     change("aws_lb.nlb", {"internal": False, "load_balancer_type": "network"})))
        self.assertEqual(ids(r), [])

    def test_association_by_root_reference_passes(self):
        cfg = {"resources": [{"address": "aws_wafv2_web_acl_association.a",
                              "expressions": {"resource_arn": {"references": ["aws_lb.pub.arn", "aws_lb.pub"]}}}]}
        r = run(plan(change("aws_lb.pub", dict(self.ALB)), change("aws_wafv2_web_acl_association.a", {}), configuration=cfg))
        self.assertEqual(ids(r), [])

    def test_association_through_module_variable_passes(self):
        cfg = {"resources": [], "module_calls": {"waf": {
            "expressions": {"alb_arn": {"references": ["aws_lb.pub.arn", "aws_lb.pub"]}},
            "module": {"resources": [{"address": "aws_wafv2_web_acl_association.alb",
                                      "expressions": {"resource_arn": {"references": ["var.alb_arn"]}}}]}}}}
        r = run(plan(change("aws_lb.pub", dict(self.ALB)),
                     change("module.waf.aws_wafv2_web_acl_association.alb[0]", {}), configuration=cfg))
        self.assertEqual(ids(r), [])

    def test_association_by_known_arn_passes(self):
        arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/example/0123456789abcdef"
        r = run(plan(change("aws_lb.pub", {**self.ALB, "arn": arn}),
                     change("aws_wafv2_web_acl_association.a", {"resource_arn": arn})))
        self.assertEqual(ids(r), [])

    def test_association_for_other_alb_does_not_count(self):
        cfg = {"resources": [{"address": "aws_wafv2_web_acl_association.a",
                              "expressions": {"resource_arn": {"references": ["aws_lb.other.arn", "aws_lb.other"]}}}]}
        r = run(plan(change("aws_lb.pub", dict(self.ALB)), change("aws_lb.other", dict(self.ALB)),
                     change("aws_wafv2_web_acl_association.a", {}), configuration=cfg))
        self.assertEqual(ids(r), [("CSP-WAF-001", "aws_lb.pub")])


class RuleCatalogueTests(unittest.TestCase):
    def test_every_rule_has_id_severity_and_remediation(self):
        self.assertEqual(len(check_plan.RULES), 6)
        for rule in check_plan.RULES.values():
            self.assertRegex(rule.id, r"^CSP-[A-Z0-9]+-\d{3}$")
            self.assertIn(rule.severity, check_plan.SEVERITIES)
            self.assertGreater(len(rule.remediation), 40)

    def test_plan_without_resource_changes_is_an_input_error(self):
        with self.assertRaises(check_plan.InputError):
            run({"format_version": "1.2"})


if __name__ == "__main__":
    unittest.main()
