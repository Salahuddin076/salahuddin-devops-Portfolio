import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import helpers  # noqa: F401  (sys.path)

import make_imagedefinitions as mid

SHA = "3f9c2b1e7a4d5c6b8e9f0a1b2c3d4e5f6a7b8c9d"
REPO = "123456789012.dkr.ecr.us-east-1.amazonaws.com/container-delivery-demo"


class ContainerNameTests(unittest.TestCase):
    def test_valid_names(self):
        for name in ("app", "web_1", "api-gateway", "A" * 255):
            self.assertEqual(mid.validate_container_name(name), name)

    def test_invalid_names(self):
        for name in ("", "my app", "app:1", "app/web", "A" * 256, "ápp"):
            with self.subTest(name=name), self.assertRaises(mid.ValidationError):
                mid.validate_container_name(name)


class ImageUriTests(unittest.TestCase):
    def test_sha_tag_accepted(self):
        uri = f"{REPO}:{SHA}"
        self.assertEqual(mid.validate_image_uri(uri, require_commit_sha=True), uri)

    def test_digest_accepted(self):
        uri = f"{REPO}@sha256:" + "a" * 64
        self.assertEqual(mid.validate_image_uri(uri, require_commit_sha=True), uri)

    def test_nested_repo_and_china_region(self):
        mid.validate_image_uri("123456789012.dkr.ecr.cn-north-1.amazonaws.com.cn/team/app:v1.2.3")
        mid.validate_image_uri("123456789012.dkr.ecr.us-gov-west-1.amazonaws.com/team/app:v1")

    def test_mutable_tags_rejected(self):
        for tag in ("latest", "LATEST", "main", "prod"):
            with self.subTest(tag=tag), self.assertRaises(mid.ValidationError):
                mid.validate_image_uri(f"{REPO}:{tag}")

    def test_non_sha_tag_rejected_when_required(self):
        mid.validate_image_uri(f"{REPO}:v1.2.3")
        for tag in ("v1.2.3", SHA[:12], SHA.upper()):
            with self.subTest(tag=tag), self.assertRaises(mid.ValidationError):
                mid.validate_image_uri(f"{REPO}:{tag}", require_commit_sha=True)

    def test_malformed_uris_rejected(self):
        bad = [
            "",
            "container-delivery-demo:" + SHA,
            "docker.io/library/python:3.12",
            f"12345.dkr.ecr.us-east-1.amazonaws.com/demo:{SHA}",
            f"123456789012.dkr.ecr.us-east-1.amazonaws.com/Demo:{SHA}",
            f"{REPO}",
            f"{REPO}:",
            f"{REPO}@sha256:abc",
            f"{REPO}:{SHA} ",
        ]
        for uri in bad:
            with self.subTest(uri=uri), self.assertRaises(mid.ValidationError):
                mid.validate_image_uri(uri)


class CliTests(unittest.TestCase):
    def test_writes_expected_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "nested", "imagedefinitions.json")
            with redirect_stdout(io.StringIO()):
                code = mid.main(["--container", "app", "--image", f"{REPO}:{SHA}", "--output", out, "--require-commit-sha"])
            self.assertEqual(code, 0)
            with open(out, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), [{"name": "app", "imageUri": f"{REPO}:{SHA}"}])
            self.assertEqual(os.listdir(os.path.dirname(out)), ["imagedefinitions.json"])

    def test_invalid_input_exits_1_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "imagedefinitions.json")
            err = io.StringIO()
            with redirect_stderr(err):
                code = mid.main(["--container", "app", "--image", f"{REPO}:latest", "--output", out])
            self.assertEqual(code, 1)
            self.assertFalse(os.path.exists(out))
            self.assertIn("mutable tag", err.getvalue())


if __name__ == "__main__":
    unittest.main()
