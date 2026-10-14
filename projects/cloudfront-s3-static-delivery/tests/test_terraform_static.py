"""Invariants `terraform validate` can't see, checked on the source text."""

import re
import unittest

from helpers import OIDC_MODULE, PROJECT, STATIC_SITE_MODULE, TERRAFORM_DIR, WORKFLOW


def read_tf(directory):
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(directory.glob("*.tf")))


SITE = read_tf(STATIC_SITE_MODULE)
OIDC = read_tf(OIDC_MODULE)
WORKFLOW_TEXT = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.exists() else ""


# Built from parts so this file does not match its own check.
PLACEHOLDER = re.compile(r"\b(" + "TO" + "DO|" + "FIX" + "ME)\b")


def strip_comments(text):
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


class StaticSiteModuleTests(unittest.TestCase):
    def test_oac_not_oai(self):
        code = strip_comments(SITE)
        self.assertIn('resource "aws_cloudfront_origin_access_control"', code)
        self.assertNotIn("aws_cloudfront_origin_access_identity", code)
        self.assertNotIn("s3_origin_config", code)
        self.assertRegex(code, r'signing_behavior\s*=\s*"always"')

    def test_bucket_policy_pinned_to_distribution(self):
        self.assertRegex(SITE, r'variable\s*=\s*"AWS:SourceArn"\s*\n\s*values\s*=\s*\[aws_cloudfront_distribution\.this\.arn\]')
        self.assertRegex(SITE, r'identifiers\s*=\s*\["cloudfront\.amazonaws\.com"\]')

    def test_bucket_hardening(self):
        self.assertIn('object_ownership = "BucketOwnerEnforced"', SITE)
        for flag in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
            self.assertRegex(SITE, flag + r"\s*=\s*true")
        self.assertIn('status = "Enabled"', SITE)
        self.assertIn("noncurrent_version_expiration", SITE)
        self.assertIn('"AES256"', SITE)

    def test_managed_cache_policy_looked_up_by_name(self):
        self.assertIn('data "aws_cloudfront_cache_policy" "caching_optimized"', SITE)
        self.assertIn('name = "Managed-CachingOptimized"', SITE)
        self.assertRegex(SITE, r"cache_policy_id\s*=\s*data\.aws_cloudfront_cache_policy\.")
        uuid = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        self.assertIsNone(re.search(uuid, strip_comments(SITE)), "hardcoded policy ID")

    def test_tls_and_http_version(self):
        self.assertIn('minimum_protocol_version = "TLSv1.2_2021"', SITE)
        self.assertIn('http_version        = "http2and3"', SITE)
        self.assertIn('ssl_support_method       = "sni-only"', SITE)

    def test_certificate_in_us_east_1(self):
        self.assertIn("configuration_aliases = [aws.us_east_1]", SITE)
        cert = SITE[SITE.index('resource "aws_acm_certificate" "this"'):]
        self.assertRegex(cert[:200], r"provider\s*=\s*aws\.us_east_1")
        self.assertIn('validation_method         = "DNS"', SITE)
        self.assertIn("aws_acm_certificate_validation.this.certificate_arn", SITE)

    def test_alias_a_and_aaaa(self):
        self.assertIn('type = "A"', SITE)
        self.assertIn('type = "AAAA"', SITE)

    def test_function_runtime_and_file(self):
        self.assertIn('runtime = "cloudfront-js-2.0"', SITE)
        self.assertIn('file("${path.module}/functions/uri-rewrite.js")', SITE)
        self.assertIn('event_type   = "viewer-request"', SITE)

    def test_error_responses(self):
        self.assertEqual(len(re.findall(r'response_page_path\s*=\s*"/404\.html"', SITE)), 2)
        self.assertRegex(SITE, r"error_code\s*=\s*403")
        self.assertRegex(SITE, r"error_code\s*=\s*404")

    def test_security_headers(self):
        for block in ("strict_transport_security", "content_security_policy", "content_type_options",
                      "frame_options", "referrer_policy"):
            self.assertIn(block + " {", SITE)

    def test_price_class_validated(self):
        self.assertIn('contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.price_class)', SITE)

    def test_web_acl_must_be_cloudfront_scope(self):
        self.assertIn("wafv2:us-east-1:[0-9]{12}:global/webacl/", SITE)

    def test_logging_is_optional_v2(self):
        self.assertIn('resource "aws_cloudwatch_log_delivery_source"', SITE)
        self.assertIn("count    = local.logging_enabled ? 1 : 0", SITE)
        self.assertNotIn("logging_config", strip_comments(SITE))


class OidcModuleTests(unittest.TestCase):
    def test_trust_requires_aud_and_exact_sub(self):
        self.assertIn('variable = "${local.oidc_host}:aud"', OIDC)
        self.assertIn('values   = ["sts.amazonaws.com"]', OIDC)
        self.assertIn('variable = "${local.oidc_host}:sub"', OIDC)
        self.assertNotIn("StringLike", OIDC)
        self.assertIn('"repo:${var.github_repository}:ref:refs/heads/${b}"', OIDC)
        self.assertIn('"repo:${var.github_repository}:environment:${e}"', OIDC)

    def test_permissions_scoped(self):
        actions = re.findall(r'actions\s*=\s*\[([^\]]*)\]', OIDC)
        flat = sorted(a.strip().strip('"') for group in actions for a in group.split(","))
        self.assertEqual(flat, sorted([
            "sts:AssumeRoleWithWebIdentity", "s3:ListBucket", "s3:PutObject", "s3:DeleteObject",
            "cloudfront:CreateInvalidation", "kms:GenerateDataKey", "kms:Decrypt"]))
        self.assertIn("resources = [var.distribution_arn]", OIDC)
        self.assertIn('resources = ["${var.bucket_arn}/*"]', OIDC)
        self.assertNotIn('"*"', OIDC)

    def test_existing_provider_supported(self):
        self.assertIn("count = var.create_oidc_provider ? 1 : 0", OIDC)


class RepoHygieneTests(unittest.TestCase):
    def project_files(self):
        for path in PROJECT.rglob("*"):
            if path.is_file() and ".terraform" not in path.parts and "__pycache__" not in path.parts:
                yield path

    def test_aws_provider_constraint_everywhere(self):
        for versions in TERRAFORM_DIR.rglob("*.tf"):
            text = versions.read_text()
            if "required_providers" in text:
                self.assertIn('version = ">= 6.0, < 7.0"', re.sub(r"\s+=", " =", text), versions)

    def test_only_documentation_account_id(self):
        for path in self.project_files():
            if path.suffix in (".hcl",):
                continue
            for match in re.findall(r"(?<![0-9])[0-9]{12}(?![0-9])", path.read_text(errors="ignore")):
                self.assertEqual(match, "123456789012", f"{path}: {match}")

    def test_only_example_domains(self):
        domain = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io)\b")
        allowed = re.compile(r"(^|\.)(example\.com|amazonaws\.com|cloudfront\.net|githubusercontent\.com|"
                             r"github\.com|hstspreload\.org|claude\.com|anthropic\.com|w3\.org)$")
        for path in self.project_files():
            if path.suffix in (".hcl",):
                continue
            for match in domain.finditer(path.read_text(errors="ignore")):
                self.assertRegex(match.group(0), allowed, f"{path}: {match.group(0)}")

    def test_no_placeholders_or_empty_files(self):
        for path in self.project_files():
            text = path.read_text(errors="ignore")
            self.assertTrue(text.strip(), f"empty file: {path}")
            self.assertIsNone(PLACEHOLDER.search(text), f"placeholder in {path}")

    def test_lock_files_present(self):
        for d in ("modules/static-site/validation-harness", "modules/github-oidc-deployer", "examples/basic"):
            self.assertTrue((TERRAFORM_DIR / d / ".terraform.lock.hcl").exists(), d)


@unittest.skipUnless(WORKFLOW_TEXT, "workflow file not found")
class WorkflowTests(unittest.TestCase):
    def test_default_permissions_read_only(self):
        top = WORKFLOW_TEXT[:WORKFLOW_TEXT.index("jobs:")]
        self.assertRegex(top, r"permissions:\s*\n\s+contents: read")
        self.assertNotIn("id-token", top)

    def test_path_filters(self):
        self.assertIn('"projects/cloudfront-s3-static-delivery/**"', WORKFLOW_TEXT)

    def test_deploy_job_disabled_and_only_place_with_id_token(self):
        deploy = WORKFLOW_TEXT[WORKFLOW_TEXT.index("  deploy-example:"):]
        self.assertRegex(deploy, r"\n    if: false")
        self.assertIn("id-token: write", deploy)
        self.assertEqual(WORKFLOW_TEXT.count("id-token: write"), 1)
        # Pinned to a full commit SHA (v4.x), never a mutable tag.
        self.assertRegex(deploy, r"aws-actions/configure-aws-credentials@[0-9a-f]{40} # v4\.")
        self.assertIn("role-to-assume: ${{ vars.", deploy)
        self.assertNotIn("secrets.AWS", WORKFLOW_TEXT)


if __name__ == "__main__":
    unittest.main()
