"""render_appspec.py: required keys, validation, immutable tags, output shape."""

import json
import unittest

from helpers import IMAGE, TAG, TASKDEF_ARN, VALUES_EXAMPLE

import render_appspec as ra


def values(**overrides):
    base = json.loads(VALUES_EXAMPLE.read_text())
    base.update(overrides)
    return ra.build_values(base, [])


class ImageTagTests(unittest.TestCase):
    def test_accepts_immutable_references(self):
        self.assertEqual(ra.image_tag(IMAGE), TAG)
        self.assertEqual(ra.image_tag("public.ecr.aws/example/app:v1.2.3"), "v1.2.3")
        digest = "sha256:" + "b" * 64
        self.assertEqual(ra.image_tag(f"{IMAGE}@{digest}"), digest)
        self.assertEqual(ra.image_tag(f"registry.example.com:5000/app@{digest}"), digest)

    def test_rejects_latest_and_untagged(self):
        for image in (IMAGE.rsplit(":", 1)[0] + ":latest", IMAGE.rsplit(":", 1)[0] + ":LATEST",
                      IMAGE.rsplit(":", 1)[0], "registry.example.com:5000/app", "Bad Image", ""):
            with self.subTest(image=image), self.assertRaises(ra.RenderError):
                ra.image_tag(image)


class RenderTests(unittest.TestCase):
    def test_renders_both_files(self):
        files = ra.render(values())
        self.assertEqual(set(files), {"appspec.yaml", "taskdef.json"})
        appspec = files["appspec.yaml"]
        self.assertIn(f'TaskDefinition: "{TASKDEF_ARN}"', appspec)
        self.assertIn('ContainerName: "app"', appspec)
        self.assertIn("ContainerPort: 8080", appspec)
        self.assertIn('PlatformVersion: "LATEST"', appspec)
        self.assertIn("- BeforeAllowTraffic: \"arn:aws:lambda:", appspec)
        self.assertIn("- AfterAllowTraffic: \"arn:aws:lambda:", appspec)
        self.assertNotIn("${", appspec)

    def test_taskdef_types_and_derived_tag(self):
        taskdef = json.loads(ra.render(values())["taskdef.json"])
        container = taskdef["containerDefinitions"][0]
        self.assertEqual(container["portMappings"][0]["containerPort"], 8080)
        env = {e["name"]: e["value"] for e in container["environment"]}
        self.assertEqual(env, {"APP_ENV": "prod", "PORT": "8080", "IMAGE_TAG": TAG})
        self.assertEqual(taskdef["runtimePlatform"]["cpuArchitecture"], "ARM64")
        self.assertTrue(container["secrets"][0]["valueFrom"].endswith(":password::"))

    def test_only_appspec_needs_only_appspec_keys(self):
        v = {k: values()[k] for k in ra.APPSPEC_KEYS}
        self.assertEqual(set(ra.render(v, "appspec")), {"appspec.yaml"})
        with self.assertRaises(ra.RenderError):
            ra.render(v, "taskdef")

    def test_missing_required_keys_listed(self):
        v = values()
        del v["CONTAINER_NAME"], v["BEFORE_ALLOW_TRAFFIC_HOOK_ARN"]
        with self.assertRaises(ra.RenderError) as ctx:
            ra.render(v)
        self.assertIn("CONTAINER_NAME is required", ctx.exception.problems)
        self.assertIn("BEFORE_ALLOW_TRAFFIC_HOOK_ARN is required", ctx.exception.problems)

    def test_invalid_values_rejected(self):
        cases = {
            "TASK_DEFINITION_ARN": "arn:aws:ecs:us-east-1:123456789012:task-definition/bluegreen-prod",
            "CONTAINER_PORT": "70000",
            "PLATFORM_VERSION": "1.4",
            "CPU_ARCHITECTURE": "arm64",
            "AFTER_ALLOW_TRAFFIC_HOOK_ARN": "arn:aws:lambda:us-east-1:123456789012:layer:x",
            "DB_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:db:password::",
            "CONTAINER_NAME": 'app" injected: "x',
        }
        for key, bad in cases.items():
            with self.subTest(key=key), self.assertRaises(ra.RenderError):
                ra.render(values(**{key: bad}))

    def test_fargate_cpu_memory_pairs(self):
        with self.assertRaises(ra.RenderError):
            ra.render(values(CPU="256", MEMORY="4096"))
        with self.assertRaises(ra.RenderError):
            ra.render(values(CPU="300", MEMORY="1024"))
        ra.render(values(CPU="256", MEMORY="512"))

    def test_latest_rejected(self):
        with self.assertRaises(ra.RenderError) as ctx:
            ra.render(values(IMAGE=IMAGE.rsplit(":", 1)[0] + ":latest"))
        self.assertTrue(any("latest" in p for p in ctx.exception.problems))

    def test_image_tag_cannot_be_set_by_hand(self):
        with self.assertRaises(ra.RenderError):
            ra.build_values({"IMAGE_TAG": "other"}, [])

    def test_set_overrides_and_bad_set(self):
        v = ra.build_values({"IMAGE": IMAGE}, ["CONTAINER_NAME=web"])
        self.assertEqual(v["CONTAINER_NAME"], "web")
        with self.assertRaises(ra.RenderError):
            ra.build_values({}, ["NOEQUALS"])

    def test_template_placeholder_without_value_is_an_error(self):
        with self.assertRaises(ra.RenderError):
            ra.render_appspec({"X": "1"}, template="version: 0.0\nfoo: ${UNKNOWN}\n")


if __name__ == "__main__":
    unittest.main()
