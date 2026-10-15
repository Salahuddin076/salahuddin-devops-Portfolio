"""promote.py: tag validation, the env chain, the hotfix override, byte-exact edits and git commits."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import CONFIG_REPO, ScratchRepo

import promote

SHA_A = "9f3c2a7e5b1d4c8f6a0e2b7d9c1f3a5e7b9d0c2e"   # envs/dev
SHA_B = "4b8e1d0c6a2f9e3b7d5c1a8f0e6b2d4c9a7e3f1b"   # envs/staging
GIT = shutil.which("git")


def tag_of(repo: Path, env: str) -> str:
    return promote.read_tag((repo / "envs" / env / "values.yaml").read_text(), env)


class TagValidationTests(unittest.TestCase):
    def test_accepts_immutable_tags(self):
        for tag in (SHA_A, "v1.3.0-7a1c9e2", "1.3.0-7a1c9e2", "v10.0.12-" + SHA_A):
            with self.subTest(tag=tag):
                self.assertEqual(promote.validate_tag(tag), tag)

    def test_rejects_mutable_or_malformed_tags(self):
        for tag in ("latest", "LATEST", "main", "v1.3.0", "1.3", "abc1234", SHA_A[:39], SHA_A.upper(),
                    "v1.3.0-xyz1234", "v01.3.0-7a1c9e2", SHA_A + "0", "", "v1.3.0-7a1c9"):
            with self.subTest(tag=tag), self.assertRaises(promote.PromotionError):
                promote.validate_tag(tag)

    def test_latest_has_its_own_message(self):
        with self.assertRaisesRegex(promote.PromotionError, "mutable"):
            promote.validate_tag("latest")


class ChainTests(unittest.TestCase):
    def test_happy_path_dev_to_staging(self):
        with ScratchRepo() as repo:
            plan = promote.plan_promotion(repo, "staging", source="dev")
            self.assertEqual((plan.old_tag, plan.new_tag, plan.hotfix), (SHA_B, SHA_A, False))
            promote.apply(plan, repo)
            self.assertEqual(tag_of(repo, "staging"), SHA_A)
            self.assertEqual(tag_of(repo, "prod"), "v1.3.0-7a1c9e2", "prod untouched")
            self.assertIn("Promoted-From: dev", plan.commit_message())
            self.assertNotIn("Hotfix", plan.commit_message())

    def test_then_staging_to_prod(self):
        with ScratchRepo() as repo:
            promote.apply(promote.plan_promotion(repo, "staging", source="dev"), repo)
            plan = promote.plan_promotion(repo, "prod", source="staging")
            promote.apply(plan, repo)
            self.assertEqual(tag_of(repo, "prod"), SHA_A)
            self.assertIn("sync window", plan.pr_body())
            # prod's tag was quoted; the quotes are kept
            self.assertIn(f'  tag: "{SHA_A}"\n', (repo / "envs/prod/values.yaml").read_text())

    def test_skipped_env_is_refused(self):
        with ScratchRepo() as repo:
            before = (repo / "envs/prod/values.yaml").read_bytes()
            with self.assertRaisesRegex(promote.PromotionError, "next env after dev is staging"):
                promote.plan_promotion(repo, "prod", source="dev")
            self.assertEqual((repo / "envs/prod/values.yaml").read_bytes(), before)

    def test_backwards_and_same_env(self):
        with ScratchRepo() as repo:
            with self.assertRaises(promote.PromotionError):
                promote.plan_promotion(repo, "dev", source="staging")
            with self.assertRaises(promote.UsageError):
                promote.plan_promotion(repo, "dev", source="dev")
            with self.assertRaisesRegex(promote.PromotionError, "last env"):
                promote.plan_promotion(repo, "staging", source="prod")

    def test_hotfix_skips_and_is_recorded(self):
        with ScratchRepo() as repo:
            plan = promote.plan_promotion(repo, "prod", source="dev", force_hotfix=True,
                                          reason="INC-123 payment timeout fix")
            msg = plan.commit_message()
            self.assertTrue(msg.startswith(f"prod: HOTFIX orders-api {SHA_A} from dev\n"))
            self.assertIn("\nPromotion-Hotfix: true\n", msg)
            self.assertIn("\nHotfix-Reason: INC-123 payment timeout fix\n", msg)
            self.assertIn("**Hotfix**", plan.pr_body())

    def test_hotfix_needs_a_reason(self):
        with ScratchRepo() as repo, self.assertRaisesRegex(promote.UsageError, "--reason"):
            promote.plan_promotion(repo, "prod", source="dev", force_hotfix=True, reason="  ")

    def test_new_tag_enters_at_dev_only(self):
        new = "1" * 40
        with ScratchRepo() as repo:
            promote.apply(promote.plan_promotion(repo, "dev", tag=new), repo)
            self.assertEqual(tag_of(repo, "dev"), new)
            with self.assertRaisesRegex(promote.PromotionError, "new tags enter at dev"):
                promote.plan_promotion(repo, "staging", tag=new)
            with self.assertRaisesRegex(promote.PromotionError, "mutable"):
                promote.plan_promotion(repo, "dev", tag="latest")

    def test_bad_tag_in_source_env_is_refused(self):
        with ScratchRepo() as repo:
            p = repo / "envs/dev/values.yaml"
            p.write_text(p.read_text().replace(SHA_A, "latest"))
            with self.assertRaisesRegex(promote.PromotionError, "latest"):
                promote.plan_promotion(repo, "staging", source="dev")

    def test_noop_when_already_promoted(self):
        with ScratchRepo() as repo:
            promote.apply(promote.plan_promotion(repo, "staging", source="dev"), repo)
            plan = promote.plan_promotion(repo, "staging", source="dev")
            self.assertTrue(plan.noop)
            self.assertEqual(plan.new_text, plan.old_text)


SAMPLE = (
    "# leading comment\r\n"
    "env: staging   # inline\r\n"
    "\r\n"
    "image:\r\n"
    "  # the tag below is the only line that may change\r\n"
    "  repository: ghcr.io/example-org/orders-api\r\n"
    "  tag: 'v1.2.0-abcdef1'   # keep this comment\r\n"
    "  pullPolicy: IfNotPresent\r\n"
    "sidecar:\r\n"
    "  image:\r\n"
    "    tag: v9.9.9-0000000\r\n"
    "tag: top-level-is-not-image-tag\r\n"
    "nested:\r\n"
    "  image:\r\n"
    "    tag: also-not-this\r\n"
)


class FormattingTests(unittest.TestCase):
    def test_only_the_tag_line_changes_byte_for_byte(self):
        out = promote.replace_tag(SAMPLE, SHA_A)
        old_lines, new_lines = SAMPLE.splitlines(keepends=True), out.splitlines(keepends=True)
        self.assertEqual(len(old_lines), len(new_lines))
        changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
        self.assertEqual(changed, [6])
        self.assertEqual(new_lines[6], f"  tag: '{SHA_A}'   # keep this comment\r\n")
        self.assertEqual(promote.read_tag(out), SHA_A)

    def test_real_env_files_change_on_one_line_only(self):
        for env in ("dev", "staging", "prod"):
            with self.subTest(env=env):
                text = (CONFIG_REPO / "envs" / env / "values.yaml").read_text()
                out = promote.replace_tag(text, "2" * 40)
                diff = [(a, b) for a, b in zip(text.splitlines(True), out.splitlines(True)) if a != b]
                self.assertEqual(len(diff), 1)
                self.assertTrue(diff[0][0].lstrip().startswith("tag:"))
                self.assertEqual(text.count("\n"), out.count("\n"))

    def test_unquoted_tag_and_no_trailing_newline(self):
        text = "image:\n  tag: abc\n  repository: x"
        self.assertEqual(promote.replace_tag(text, SHA_A), f"image:\n  tag: {SHA_A}\n  repository: x")

    def test_ambiguous_files_are_errors(self):
        for text in ("env: dev\n", "image:\n  repository: x\n", "image:\n  tag: a\nimage:\n  tag: b\n",
                     "image:\n  tag: a\n  tag: b\n"):
            with self.subTest(text=text), self.assertRaises(promote.UsageError):
                promote.replace_tag(text, SHA_A)


@unittest.skipIf(GIT is None, "git is not installed")
class GitCommitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gitops-git-")
        self.repo = Path(self._tmp.name) / "orders-config"
        shutil.copytree(CONFIG_REPO, self.repo)
        for args in (["init", "--quiet", "-b", "main"], ["config", "user.name", "promotion-bot"],
                     ["config", "user.email", "bot@example.com"], ["config", "commit.gpgsign", "false"],
                     ["add", "."], ["commit", "--quiet", "-m", "initial"]):
            self.git(*args)

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True,
                              check=True, timeout=60).stdout.strip()

    def test_commit_on_a_branch_touches_only_the_target_file(self):
        plan = promote.plan_promotion(self.repo, "staging", source="dev")
        sha = promote.apply(plan, self.repo, commit=True, branch="promote/staging-9f3c2a7e5b1d")
        self.assertEqual(sha, self.git("rev-parse", "HEAD"))
        self.assertEqual(self.git("branch", "--show-current"), "promote/staging-9f3c2a7e5b1d")
        self.assertEqual(self.git("diff", "--name-only", "main", "HEAD"), "envs/staging/values.yaml")
        self.assertEqual(self.git("log", "-1", "--format=%s"), f"staging: promote orders-api {SHA_A} from dev")
        self.assertEqual(self.git("log", "-1", "--format=%(trailers:key=Promoted-From,valueonly)"), "dev")
        self.assertEqual(self.git("status", "--porcelain"), "")
        numstat = self.git("diff", "--numstat", "main", "HEAD")
        self.assertTrue(numstat.startswith("1\t1\t"), numstat)

    def test_hotfix_trailer_is_a_real_git_trailer(self):
        plan = promote.plan_promotion(self.repo, "prod", source="dev", force_hotfix=True, reason="INC-123")
        promote.apply(plan, self.repo, commit=True)
        self.assertEqual(self.git("log", "-1", "--format=%(trailers:key=Promotion-Hotfix,valueonly)"), "true")
        self.assertEqual(self.git("log", "-1", "--format=%(trailers:key=Hotfix-Reason,valueonly)"), "INC-123")

    def test_refuses_to_commit_over_local_edits(self):
        p = self.repo / "envs/staging/values.yaml"
        p.write_text(p.read_text() + "# local edit\n")
        plan = promote.plan_promotion(self.repo, "staging", source="dev")
        with self.assertRaisesRegex(promote.UsageError, "uncommitted"):
            promote.apply(plan, self.repo, commit=True)


if __name__ == "__main__":
    unittest.main()
