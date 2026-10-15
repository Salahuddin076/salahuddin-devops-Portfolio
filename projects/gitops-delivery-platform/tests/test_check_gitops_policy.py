"""check_gitops_policy.py: the real config repo passes, the bad fixture trips every rule, single mutations."""

from __future__ import annotations

import unittest
from datetime import datetime

from helpers import CONFIG_REPO, FIXTURES, ScratchRepo

import check_gitops_policy as gp

BAD = FIXTURES / "policy" / "bad"


def rules(ctx):
    return sorted({f.rule for f in ctx.findings})


def edit(path, old, new, count=1):
    text = path.read_text()
    assert text.count(old) >= 1, f"{old!r} not in {path}"
    path.write_text(text.replace(old, new, count))


class GoodRepoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = gp.run(CONFIG_REPO)
        cls.apps = {a.name: a for a in cls.ctx.apps}

    def test_clean(self):
        self.assertEqual(self.ctx.findings, [])

    def test_appset_fans_out_one_app_per_env(self):
        self.assertEqual(sorted(self.apps), ["orders-api-dev", "orders-api-prod", "orders-api-staging",
                                             "platform-base", "root"])
        for env in ("dev", "staging", "prod"):
            app = self.apps[f"orders-api-{env}"]
            self.assertEqual(app.env, env)
            self.assertEqual(app.spec["destination"]["namespace"], f"orders-{env}")
            self.assertEqual(app.spec["source"]["helm"]["valueFiles"], [f"../../envs/{env}/values.yaml"])

    def test_sync_policies_per_env(self):
        self.assertEqual(self.apps["orders-api-dev"].automated, {"prune": True, "selfHeal": True})
        self.assertEqual(self.apps["orders-api-staging"].automated, {"prune": False, "selfHeal": True})
        self.assertIsNone(self.apps["orders-api-prod"].automated)
        # the patch merges into the template's syncPolicy instead of replacing it
        for env in ("dev", "staging", "prod"):
            self.assertIn("RespectIgnoreDifferences=true", self.apps[f"orders-api-{env}"].sync["syncOptions"])


class BadFixtureTests(unittest.TestCase):
    def test_every_rule_fires(self):
        ctx = gp.run(BAD)
        self.assertEqual(rules(ctx), ["GP001", "GP002", "GP003", "GP004", "GP005", "GP006", "GP007",
                                      "GP008", "GP009", "GP010"])
        msgs = {(f.rule, f.subject) for f in ctx.findings}
        self.assertIn(("GP001", "Application/orders-api-prod"), msgs)
        self.assertIn(("GP002", "Application/orders-api-staging"), msgs)
        self.assertIn(("GP004", "Application/debug-tools"), msgs)
        self.assertIn(("GP005", "envs/dev/values.yaml"), msgs)
        self.assertIn(("GP005", "envs/staging/values.yaml"), msgs)
        self.assertNotIn(("GP005", "envs/prod/values.yaml"), msgs)


class MutationTests(unittest.TestCase):
    """One change to a copy of the real repo, one rule."""

    def check(self, mutate, expected):
        with ScratchRepo() as repo:
            mutate(repo)
            self.assertEqual(rules(gp.run(repo)), expected)

    def test_prod_automated(self):
        def m(repo):
            edit(repo / "argocd/applicationsets/orders-api.yaml", "{{- end }}",
                 '{{- else if eq .path.basename "prod" }}\n    spec:\n      syncPolicy:\n'
                 '        automated:\n          selfHeal: true\n    {{- end }}')
        self.check(m, ["GP001"])

    def test_staging_prune(self):
        self.check(lambda r: edit(r / "argocd/applicationsets/orders-api.yaml", "prune: false", "prune: true"),
                   ["GP002"])

    def test_cluster_scoped_kind_allowed(self):
        self.check(lambda r: edit(r / "argocd/projects/orders-api.yaml", "clusterResourceWhitelist: []",
                                  'clusterResourceWhitelist:\n    - group: ""\n      kind: Namespace'), ["GP003"])

    def test_namespace_outside_project(self):
        self.check(lambda r: edit(r / "argocd/applicationsets/orders-api.yaml",
                                  'namespace: "orders-{{ .path.basename }}"', 'namespace: "{{ .path.basename }}"'),
                   ["GP004"])

    def test_latest_tag(self):
        self.check(lambda r: edit(r / "envs/prod/values.yaml", '"v1.3.0-7a1c9e2"', "latest"), ["GP005"])

    def test_prod_rollout_disabled(self):
        def m(repo):
            edit(repo / "envs/prod/values.yaml", "rollout:\n  enabled: true", "rollout:\n  enabled: false")
        self.check(m, ["GP006"])

    def test_weekend_gap(self):
        self.check(lambda r: edit(r / "argocd/projects/orders-api.yaml", "duration: 56h", "duration: 48h"),
                   ["GP007"])

    def test_manual_override_left_on(self):
        self.check(lambda r: edit(r / "argocd/projects/orders-api.yaml", "manualSync: false", "manualSync: true"),
                   ["GP007"])

    def test_missing_notifications(self):
        def m(repo):
            edit(repo / "argocd/applicationsets/orders-api.yaml",
                 "        notifications.argoproj.io/subscribe.on-health-degraded.slack: orders-alerts\n", "")
        self.check(m, ["GP008"])

    def test_missing_ignore_differences(self):
        self.check(lambda r: edit(r / "argocd/applicationsets/orders-api.yaml",
                                  "          - RespectIgnoreDifferences=true\n", ""), ["GP009"])

    def test_dev_not_pruning(self):
        self.check(lambda r: edit(r / "argocd/applicationsets/orders-api.yaml", "prune: true", "prune: false"),
                   ["GP010"])

    def test_unsupported_template_fails_closed(self):
        self.check(lambda r: edit(r / "argocd/applicationsets/orders-api.yaml",
                                  'eq .path.basename "staging"', 'hasPrefix .path.basename "stag"'), ["GP000"])

    def test_new_env_directory_defaults_to_manual(self):
        def m(repo):
            (repo / "envs/qa").mkdir()
            (repo / "envs/qa/values.yaml").write_text((repo / "envs/staging/values.yaml").read_text())
            edit(repo / "argocd/projects/orders-api.yaml", "      namespace: orders-prod\n",
                 "      namespace: orders-prod\n    - server: https://kubernetes.default.svc\n"
                 "      namespace: orders-qa\n")
        with ScratchRepo() as repo:
            m(repo)
            ctx = gp.run(repo)
            self.assertEqual(ctx.findings, [])
            qa = next(a for a in ctx.apps if a.name == "orders-api-qa")
            self.assertIsNone(qa.automated)


class TemplateAndCronTests(unittest.TestCase):
    def test_render_go_trim_and_branches(self):
        tpl = 'a{{- if eq .path.basename "x" }}\nX{{- else if eq .path.basename "y" }}\nY{{- else }}\nZ{{- end }}\n'
        self.assertEqual(gp.render_go(tpl, {"basename": "x", "path": "envs/x"}), "a\nX\n")
        self.assertEqual(gp.render_go(tpl, {"basename": "y", "path": "envs/y"}), "a\nY\n")
        self.assertEqual(gp.render_go(tpl, {"basename": "q", "path": "envs/q"}), "a\nZ\n")
        self.assertEqual(gp.render_go("{{ .path.path }}/{{.path.basename}}", {"basename": "b", "path": "p"}), "p/b")
        for bad in ("{{ .values.x }}", "{{ if true }}x{{ end }}", '{{ if eq .path.basename "a" }}', "{{ end }}"):
            with self.subTest(bad=bad), self.assertRaises(gp.TemplateError):
                gp.render_go(bad, {"basename": "a", "path": "p"})

    def test_window_minutes(self):
        monday = datetime(2026, 1, 5)
        nights = gp.window_minutes("0 17 * * 1-5", "15h", monday)
        self.assertEqual(len(nights), 5 * 15 * 60)  # Friday's window runs into Saturday, still this week
        self.assertIn(17 * 60, nights)                 # Mon 17:00
        self.assertNotIn(16 * 60 + 59, nights)         # Mon 16:59
        weekend = gp.window_minutes("0 0 * * 6", "56h", monday)
        self.assertIn(7 * 1440 - 1, weekend)           # Sun 23:59
        self.assertEqual(len(gp.window_minutes("30 9 * * 0", "1h30m", monday)), 90)
        for bad in (("0 17 * *", "1h"), ("0 25 * * *", "1h"), ("0 1 * * *", "soon")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                gp.window_minutes(bad[0], bad[1], monday)


if __name__ == "__main__":
    unittest.main()
