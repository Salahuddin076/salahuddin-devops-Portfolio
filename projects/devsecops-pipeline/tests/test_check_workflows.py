import json
import unittest

import helpers
from helpers import fixture
import check_workflows as cw


def rules(findings):
    return sorted(f.rule for f in findings)


def lint(name):
    return cw.lint_text(fixture(name), name)


class GoodFixtureTests(unittest.TestCase):
    def test_good_fixture_has_no_findings(self):
        self.assertEqual(lint("good.yml"), [])

    def test_ok_pull_request_target_on_base_branch(self):
        self.assertEqual(lint("ok-pr-target-base.yml"), [])


class PermissionRules(unittest.TestCase):
    def test_wf001_missing_top_level_permissions(self):
        self.assertEqual(rules(lint("bad-no-permissions.yml")), ["WF001"])

    def test_wf002_write_all_top_and_job(self):
        found = lint("bad-write-all.yml")
        self.assertEqual(rules(found), ["WF002", "WF002"])
        self.assertEqual(sorted(f.line for f in found), [3, 7])

    def test_wf040_id_token_at_top_level(self):
        found = lint("bad-id-token-top.yml")
        self.assertEqual(rules(found), ["WF040"])
        self.assertEqual(found[0].line, 5)

    def test_id_token_at_job_level_is_fine(self):
        text = fixture("good.yml")
        self.assertIn("id-token: write", text)
        self.assertNotIn("WF040", rules(cw.lint_text(text, "good.yml")))


class PinningRules(unittest.TestCase):
    def setUp(self):
        self.found = lint("bad-unpinned.yml")
        self.by_line = {f.line: f.rule for f in self.found}

    def test_wf011_first_party_tag_is_warning(self):
        self.assertEqual(self.by_line[9], "WF011")
        self.assertEqual(cw.RULES["WF011"][0], "warning")

    def test_wf010_third_party_tag_branch_and_missing_ref(self):
        for line in (10, 11, 12):
            self.assertEqual(self.by_line[line], "WF010", line)

    def test_wf010_reusable_workflow_from_other_repo(self):
        self.assertEqual(self.by_line[16], "WF010")

    def test_wf012_docker_without_digest(self):
        self.assertEqual(self.by_line[13], "WF012")

    def test_wf013_sha_without_version_comment(self):
        self.assertEqual(self.by_line[14], "WF013")

    def test_local_actions_and_reusable_workflows_are_skipped(self):
        self.assertEqual(lint("good.yml"), [])

    def test_sha_pin_with_comment_passes(self):
        text = (
            "on: push\npermissions:\n  contents: read\njobs:\n  a:\n    runs-on: x\n    steps:\n"
            "      - uses: docker/login-action@dbcb813823bdd20940b903addbd779551569679f # v4.6.0\n"
        )
        self.assertEqual(cw.lint_text(text, "t.yml"), [])


class PullRequestTargetRule(unittest.TestCase):
    def test_wf020_checkout_of_pr_head(self):
        found = lint("bad-pr-target.yml")
        self.assertEqual(rules(found), ["WF020"])
        self.assertEqual(found[0].line, 13)

    def test_pr_head_checkout_without_pr_target_is_not_wf020(self):
        text = fixture("bad-pr-target.yml").replace("pull_request_target:", "pull_request:")
        self.assertNotIn("WF020", rules(cw.lint_text(text, "t.yml")))


class ScriptInjectionRule(unittest.TestCase):
    def test_wf030_single_line_block_and_github_script(self):
        found = [f for f in lint("bad-injection.yml") if f.rule == "WF030"]
        self.assertEqual(sorted(f.line for f in found), [12, 16, 17, 21])
        joined = " ".join(f.message for f in found)
        for field in ("github.event.issue.title", "github.head_ref",
                      "github.event.pull_request.body", "github.event.comment.body"):
            self.assertIn(field, joined)

    def test_env_mediated_value_is_safe(self):
        self.assertEqual(lint("good.yml"), [])

    def test_trusted_event_fields_are_not_flagged(self):
        text = (
            "on: push\npermissions:\n  contents: read\njobs:\n  a:\n    runs-on: x\n    steps:\n"
            "      - run: echo ${{ github.event.pull_request.number }} ${{ github.event.before }}\n"
        )
        self.assertEqual(cw.lint_text(text, "t.yml"), [])


class PersistCredentialsRule(unittest.TestCase):
    def test_wf050_default_and_explicit_true(self):
        found = lint("bad-persist-credentials.yml")
        self.assertEqual(rules(found), ["WF050", "WF050"])

    def test_pushing_job_is_exempt(self):
        # the `release` job in good.yml has contents: write and runs git push
        self.assertEqual(lint("good.yml"), [])


class ParseErrorRule(unittest.TestCase):
    def test_wf000(self):
        self.assertEqual(rules(lint("bad-parse.yml")), ["WF000"])


class OwnWorkflowsTests(unittest.TestCase):
    def test_this_projects_workflows_have_no_findings(self):
        for path in helpers.OWN_WORKFLOWS:
            with self.subTest(path=path.name):
                self.assertEqual(cw.lint_text(path.read_text(encoding="utf-8"), path.name), [])

    def test_reusable_workflow_scopes_security_events_and_id_token(self):
        from yaml_subset import parse

        doc = parse(helpers.OWN_WORKFLOWS[0].read_text(encoding="utf-8"))
        self.assertEqual(dict(doc["permissions"]), {"contents": "read"})
        uploaders = set()
        for name, job in doc["jobs"].items():
            perms = job.get("permissions")
            self.assertIsNotNone(perms, f"job {name} has no permissions block")
            steps = job.get("steps") or []
            uploads = any("upload-sarif" in str(s.get("uses", "")) for s in steps)
            if perms.get("security-events") == "write":
                uploaders.add(name)
            self.assertEqual(uploads, perms.get("security-events") == "write", name)
            self.assertEqual(perms.get("id-token") == "write", name == "sign-and-attest", name)
        self.assertEqual(uploaders, {"secrets-scan", "sast", "sca", "image-scan"})

    def test_sign_job_is_gated_on_publish_and_main(self):
        from yaml_subset import parse

        doc = parse(helpers.OWN_WORKFLOWS[0].read_text(encoding="utf-8"))
        cond = doc["jobs"]["sign-and-attest"]["if"]
        for part in ("inputs.publish", "github.event_name == 'push'", "refs/heads/main"):
            self.assertIn(part, cond)
        self.assertEqual(doc["on"]["workflow_call"]["inputs"]["publish"]["default"], "false")


class SarifTests(unittest.TestCase):
    def test_sarif_shape(self):
        sarif = cw.render_sarif(lint("bad-injection.yml"))
        self.assertEqual(sarif["version"], "2.1.0")
        run = sarif["runs"][0]
        rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
        self.assertEqual(rule_ids, set(cw.RULES))
        for res in run["results"]:
            self.assertIn(res["ruleId"], rule_ids)
            self.assertIn(res["level"], ("error", "warning"))
            self.assertGreaterEqual(res["locations"][0]["physicalLocation"]["region"]["startLine"], 1)
        json.dumps(sarif)  # serialisable


if __name__ == "__main__":
    unittest.main()
