"""WAF log summary: counting, labels and the count-mode (would-block) math."""

import json
import unittest

from helpers import SAMPLE_LOGS

import waf_log_summary as wls


def record(ip="203.0.113.10", uri="/", action="ALLOW", term="Default_Action", term_type="REGULAR",
           groups=(), nonterm=(), ts=1791964800000):
    return {"timestamp": ts, "formatVersion": 1, "action": action, "terminatingRuleId": term,
            "terminatingRuleType": term_type, "ruleGroupList": list(groups), "nonTerminatingMatchingRules": list(nonterm),
            "rateBasedRuleList": [], "httpRequest": {"clientIp": ip, "uri": uri, "httpMethod": "GET", "headers": []}}


def group(name, terminating=None, nonterm=()):
    return {"ruleGroupId": f"AWS#{name}", "terminatingRule": terminating,
            "nonTerminatingMatchingRules": list(nonterm), "excludedRules": None}


def summarise(*records):
    return wls.summarise(json.dumps(r) for r in records)


SQLI_COUNT = [{"ruleId": "AWS-AWSManagedRulesSQLiRuleSet", "action": "COUNT"}]


def sqli_match(ip, uri="/api/reports/query", action="ALLOW", **kw):
    return record(ip=ip, uri=uri, action=action, nonterm=SQLI_COUNT,
                  groups=[group("AWSManagedRulesSQLiRuleSet", {"ruleId": "SQLi_BODY", "action": "BLOCK"})], **kw)


class BasicCountingTests(unittest.TestCase):
    def test_actions_and_window(self):
        s = summarise(record(ts=1000), record(action="BLOCK", term="ip-block-list", ts=5000), record(ts=3000))
        self.assertEqual(s.total, 3)
        self.assertEqual(s.actions, {"ALLOW": 2, "BLOCK": 1})
        self.assertEqual((s.first_ts, s.last_ts), (1000, 5000))

    def test_malformed_lines_are_skipped(self):
        s = wls.summarise(["{not json", "", json.dumps({"no": "action"}), json.dumps(record())])
        self.assertEqual((s.total, s.malformed), (1, 2))

    def test_managed_group_block_label_includes_inner_rule(self):
        r = record(action="BLOCK", term="AWS-AWSManagedRulesCommonRuleSet", term_type="MANAGED_RULE_GROUP",
                   groups=[group("AWSManagedRulesCommonRuleSet", {"ruleId": "NoUserAgent_HEADER", "action": "BLOCK"})])
        self.assertEqual(wls.blocked_rule_label(r), "AWS-AWSManagedRulesCommonRuleSet/NoUserAgent_HEADER")

    def test_top_blocked_rules_and_ips(self):
        s = summarise(
            record(ip="198.51.100.1", action="BLOCK", term="ip-block-list"),
            record(ip="198.51.100.1", action="BLOCK", term="ip-block-list"),
            record(ip="198.51.100.1"),
            record(ip="198.51.100.2", action="BLOCK", term="rate-limit-per-ip"),
        )
        d = wls.to_dict(s, top=5)
        self.assertEqual(d["top_blocked_rules"][0], {"rule": "ip-block-list", "requests": 2})
        self.assertEqual(d["top_blocked_client_ips"][0], {"ip": "198.51.100.1", "blocked": 2, "total": 3})

    def test_top_limits_rows(self):
        s = summarise(*[record(ip=f"203.0.113.{i}", action="BLOCK", term="ip-block-list") for i in range(1, 9)])
        self.assertEqual(len(wls.to_dict(s, top=3)["top_blocked_client_ips"]), 3)


class WouldBlockTests(unittest.TestCase):
    def test_count_mode_group_reports_inner_rule_once(self):
        matches = wls.would_block_matches(sqli_match("203.0.113.40"))
        self.assertEqual(matches, [("AWSManagedRulesSQLiRuleSet/SQLi_BODY", "count-mode group")])

    def test_custom_count_rule(self):
        r = record(nonterm=[{"ruleId": "rate-limit-per-ip", "action": "COUNT"}])
        self.assertEqual(wls.would_block_matches(r), [("rate-limit-per-ip", "count-mode rule")])

    def test_rule_action_override(self):
        r = record(groups=[group("AWSManagedRulesCommonRuleSet", nonterm=[
            {"ruleId": "SizeRestrictions_BODY", "action": "COUNT", "overriddenAction": "BLOCK"}])])
        self.assertEqual(wls.would_block_matches(r), [("AWSManagedRulesCommonRuleSet/SizeRestrictions_BODY", "rule override")])

    def test_group_that_terminated_is_not_count_mode(self):
        r = record(action="BLOCK", term="AWS-AWSManagedRulesCommonRuleSet", term_type="MANAGED_RULE_GROUP",
                   groups=[group("AWSManagedRulesCommonRuleSet", {"ruleId": "NoUserAgent_HEADER", "action": "BLOCK"})])
        self.assertEqual(wls.would_block_matches(r), [])

    def test_newly_blocked_excludes_requests_already_blocked(self):
        s = summarise(
            sqli_match("203.0.113.40"),
            sqli_match("203.0.113.41"),
            # matched SQLi in count mode, but a later custom rule blocked it anyway
            sqli_match("203.0.113.66", action="BLOCK", term="block-admin-paths"),
        )
        stats = s.count_rules["count-mode group:AWSManagedRulesSQLiRuleSet/SQLi_BODY"]
        self.assertEqual((stats.matches, stats.newly_blocked, len(stats.ips)), (3, 2, 2))
        self.assertNotIn("203.0.113.66", stats.ips)

    def test_hints(self):
        fp = summarise(*[sqli_match(f"203.0.113.{i}") for i in range(40, 45)])
        self.assertIn("false positive", next(iter(fp.count_rules.values())).hint())
        hostile = summarise(*[sqli_match("203.0.113.88", uri=f"/p/{i}") for i in range(4)])
        self.assertIn("candidate to block", next(iter(hostile.count_rules.values())).hint())
        mixed = summarise(*[sqli_match(f"203.0.113.{i}", uri=f"/p/{i}") for i in range(40, 44)])
        self.assertIn("mixed", next(iter(mixed.count_rules.values())).hint())
        stats = wls.CountRuleStats("r", "count-mode rule", matches=2)
        self.assertIn("no change", stats.hint())


class SampleDataTests(unittest.TestCase):
    """Pins the numbers quoted in the README."""

    @classmethod
    def setUpClass(cls):
        with SAMPLE_LOGS.open() as fh:
            cls.s = wls.summarise(fh)
        cls.d = wls.to_dict(cls.s, top=5)

    def test_totals(self):
        self.assertEqual(self.d["records"], 47)
        self.assertEqual(self.d["malformed_lines"], 0)
        self.assertEqual(self.d["actions"], {"ALLOW": 32, "BLOCK": 15})

    def test_top_blocked(self):
        self.assertEqual(self.d["top_blocked_rules"][0], {"rule": "ip-block-list", "requests": 5})
        self.assertEqual(sum(r["requests"] for r in self.d["top_blocked_rules"]), 14)  # 15 total, top 5 shown

    def test_flip_view(self):
        by_rule = {r["rule"]: r for r in self.d["count_mode_would_block"]}
        self.assertEqual(by_rule["rate-limit-per-ip"]["would_newly_block"], 6)
        self.assertEqual(by_rule["rate-limit-per-ip"]["unique_client_ips"], 1)
        self.assertEqual(by_rule["AWSManagedRulesSQLiRuleSet/SQLi_BODY"]["unique_client_ips"], 5)
        self.assertEqual(by_rule["AWSManagedRulesSQLiRuleSet/SQLi_QUERYARGUMENTS"]["unique_client_ips"], 1)
        self.assertEqual(by_rule["AWSManagedRulesCommonRuleSet/SizeRestrictions_BODY"]["kind"], "rule override")

    def test_sample_uses_documentation_ranges_only(self):
        import ipaddress
        doc_nets = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
        with SAMPLE_LOGS.open() as fh:
            for line in fh:
                ip = ipaddress.ip_address(json.loads(line)["httpRequest"]["clientIp"])
                self.assertTrue(any(ip in n for n in doc_nets), ip)

    def test_sensitive_headers_are_redacted(self):
        with SAMPLE_LOGS.open() as fh:
            for line in fh:
                for h in json.loads(line)["httpRequest"]["headers"]:
                    if h["name"].lower() in ("authorization", "cookie"):
                        self.assertEqual(h["value"], "REDACTED")


if __name__ == "__main__":
    unittest.main()
