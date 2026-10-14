"""Rendered-chart checks (`helm template`); skipped when helm isn't installed."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest

from helpers import CHART_DIR, MODULE_DIR

import check_chart_policy
import yaml_lite

HELM = shutil.which("helm")


def render(*extra):
    out = subprocess.run([HELM, "template", "n8n", str(CHART_DIR), "--namespace", "n8n", *extra],
                         capture_output=True, text=True, timeout=120, check=True).stdout
    return out, yaml_lite.load_all(out)


def by_name(docs):
    return {(d["kind"], d["metadata"]["name"]): d for d in docs}


def env_of(container):
    return {e["name"]: e.get("value") for e in container["env"]}


@unittest.skipIf(HELM is None, "helm is not installed")
class RenderedChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text, cls.docs = render()
        cls.objs = by_name(cls.docs)
        cls.pods = {c: cls.objs[("Deployment", f"n8n-{c}")]["spec"]["template"]["spec"]
                    for c in ("main", "webhook", "worker")}
        cls.containers = {c: p["containers"][0] for c, p in cls.pods.items()}

    def test_expected_objects_and_no_secret(self):
        kinds = sorted(k for k, _ in self.objs)
        self.assertEqual(kinds, sorted(["Deployment"] * 3 + ["Service"] * 2 + ["NetworkPolicy"] * 3 +
                                       ["PodDisruptionBudget"] * 2 + ["HorizontalPodAutoscaler", "Ingress",
                                        "ScaledObject", "SecretProviderClass", "ServiceAccount",
                                        "TriggerAuthentication"]))
        self.assertNotIn("Secret", kinds)

    def test_one_image_three_roles(self):
        images = {c["image"] for c in self.containers.values()}
        self.assertEqual(images, {"docker.n8n.io/n8nio/n8n:2.41.3"})
        self.assertEqual(self.containers["main"]["args"], ["start"])
        self.assertEqual(self.containers["webhook"]["args"], ["webhook"])
        self.assertEqual(self.containers["worker"]["args"], ["worker", "--concurrency=10"])

    def test_main_is_a_recreate_singleton(self):
        spec = self.objs[("Deployment", "n8n-main")]["spec"]
        self.assertEqual(spec["replicas"], 1)
        self.assertEqual(spec["strategy"]["type"], "Recreate")
        self.assertEqual(env_of(self.containers["main"])["N8N_DISABLE_PRODUCTION_MAIN_PROCESS"], "true")
        for c in ("webhook", "worker"):
            self.assertNotIn("replicas", self.objs[("Deployment", f"n8n-{c}")]["spec"], "autoscaler owns it")

    def test_queue_mode_shared_config_from_files(self):
        for role, c in self.containers.items():
            with self.subTest(role=role):
                env = env_of(c)
                self.assertEqual(env["EXECUTIONS_MODE"], "queue")
                self.assertEqual(env["DB_TYPE"], "postgresdb")
                self.assertEqual(env["N8N_ENCRYPTION_KEY_FILE"], "/mnt/secrets/encryption-key")
                self.assertEqual(env["DB_POSTGRESDB_PASSWORD_FILE"], "/mnt/secrets/db-password")
                self.assertEqual(env["QUEUE_BULL_REDIS_PASSWORD_FILE"], "/mnt/secrets/redis-password")
                self.assertEqual(env["QUEUE_BULL_REDIS_TLS"], "true")
                self.assertEqual(env["N8N_WEBHOOK_URL"], "https://n8n.example.com/")
                self.assertEqual(env["N8N_METRICS"], "true")
                self.assertEqual(env["EXECUTIONS_DATA_PRUNE"], "true")
                self.assertNotIn("N8N_ENCRYPTION_KEY", env)
                self.assertNotIn("WEBHOOK_URL", env, "deprecated in 2.x: N8N_WEBHOOK_URL")
                self.assertTrue(all("valueFrom" not in e for e in c["env"]))

    def test_spc_files_match_the_file_env_vars(self):
        spc = self.objs[("SecretProviderClass", "n8n")]["spec"]
        self.assertEqual((spc["provider"], spc["parameters"]["usePodIdentity"]), ("aws", "true"))
        objects = yaml_lite.load_all(spc["parameters"]["objects"])[0]
        files = {o["objectAlias"] for o in objects} | {j["objectAlias"] for o in objects for j in o.get("jmesPath", [])}
        for name, value in env_of(self.containers["worker"]).items():
            if name.endswith("_FILE"):
                self.assertIn(value.rsplit("/", 1)[1], files, name)
        self.assertNotIn("secretObjects", spc)

    def test_worker_shutdown_window(self):
        pod, c = self.pods["worker"], self.containers["worker"]
        env = env_of(c)
        self.assertEqual(env["EXECUTIONS_TIMEOUT"], "600")
        self.assertEqual(env["N8N_GRACEFUL_SHUTDOWN_TIMEOUT"], "630")
        self.assertEqual(c["lifecycle"]["preStop"]["sleep"]["seconds"], 5)
        self.assertEqual(pod["terminationGracePeriodSeconds"], 650)
        _, prod = render("-f", str(CHART_DIR / "values-prod.yaml"))
        prod_pod = by_name(prod)[("Deployment", "n8n-worker")]["spec"]["template"]["spec"]
        self.assertEqual(prod_pod["terminationGracePeriodSeconds"], 1200 + 30 + 5 + 15)

    def test_scaled_object(self):
        so = self.objs[("ScaledObject", "n8n-worker")]["spec"]
        self.assertEqual((so["minReplicaCount"], so["maxReplicaCount"]), (0, 10))
        self.assertEqual((so["pollingInterval"], so["cooldownPeriod"]), (15, 300))
        wait, active = so["triggers"]
        self.assertEqual(wait["type"], "redis")
        self.assertEqual(wait["metadata"]["listName"], "bull:jobs:wait")
        self.assertEqual(wait["metadata"]["listLength"], "10")
        self.assertEqual(wait["metadata"]["activationListLength"], "0")
        self.assertEqual(wait["metadata"]["enableTLS"], "true")
        self.assertEqual(active["metadata"]["listName"], "bull:jobs:active")
        self.assertEqual(wait["authenticationRef"]["name"], "n8n-redis")
        behavior = so["advanced"]["horizontalPodAutoscalerConfig"]["behavior"]
        self.assertEqual(behavior["scaleDown"]["stabilizationWindowSeconds"], 300)

    def test_trigger_auth_uses_keda_identity_not_a_secret(self):
        ta = self.objs[("TriggerAuthentication", "n8n-redis")]["spec"]
        self.assertEqual(list(ta), ["awsSecretManager"])
        self.assertEqual(ta["awsSecretManager"]["podIdentity"], {"provider": "aws", "identityOwner": "keda"})
        self.assertEqual(ta["awsSecretManager"]["secrets"][0]["name"], "n8n/redis-auth")
        self.assertEqual(ta["awsSecretManager"]["secrets"][0]["parameter"], "password")

    def test_ingress_routes(self):
        rules = self.objs[("Ingress", "n8n")]["spec"]["rules"][0]["http"]["paths"]
        routes = [(p["path"], p["backend"]["service"]["name"]) for p in rules]
        self.assertEqual(routes[-1], ("/", "n8n-main"), "catch-all last")
        to_webhook = {p for p, s in routes if s == "n8n-webhook"}
        self.assertEqual(to_webhook, {"/webhook", "/webhook-waiting", "/form", "/form-waiting", "/mcp"})
        self.assertNotIn("/webhook-test", to_webhook, "test webhooks exist only on main")
        self.assertEqual(self.objs[("Ingress", "n8n")]["spec"]["ingressClassName"], "alb")

    def test_hardening_and_probes(self):
        for role, pod in self.pods.items():
            with self.subTest(role=role):
                c = self.containers[role]
                self.assertFalse(pod["automountServiceAccountToken"])
                self.assertEqual(pod["securityContext"]["runAsUser"], 1000)
                self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
                sc = c["securityContext"]
                self.assertTrue(sc["readOnlyRootFilesystem"])
                self.assertFalse(sc["allowPrivilegeEscalation"])
                self.assertEqual(sc["capabilities"]["drop"], ["ALL"])
                mounts = {m["mountPath"]: m for m in c["volumeMounts"]}
                self.assertEqual(set(mounts), {"/mnt/secrets", "/home/node/.n8n", "/home/node/.cache", "/tmp"})
                self.assertTrue(mounts["/mnt/secrets"]["readOnly"])
                self.assertEqual(c["readinessProbe"]["httpGet"]["path"], "/healthz/readiness")
                self.assertEqual(c["livenessProbe"]["httpGet"]["path"], "/healthz")
                self.assertIn("cpu", c["resources"]["requests"])
                self.assertIn("memory", c["resources"]["limits"])
        self.assertEqual(env_of(self.containers["worker"])["QUEUE_HEALTH_CHECK_ACTIVE"], "true")

    def test_pdbs_hpa_and_network_policies(self):
        self.assertEqual(self.objs[("PodDisruptionBudget", "n8n-main")]["spec"]["maxUnavailable"], 1)
        self.assertEqual(self.objs[("PodDisruptionBudget", "n8n-webhook")]["spec"]["minAvailable"], 1)
        hpa = self.objs[("HorizontalPodAutoscaler", "n8n-webhook")]["spec"]
        self.assertEqual(hpa["metrics"][0]["resource"]["name"], "cpu")
        ingress = self.objs[("NetworkPolicy", "n8n-ingress")]["spec"]
        self.assertEqual(ingress["ingress"][0]["from"], [{"ipBlock": {"cidr": "10.0.0.0/16"}}])
        self.assertNotIn("ingress", self.objs[("NetworkPolicy", "n8n-worker-ingress")]["spec"])
        egress = self.objs[("NetworkPolicy", "n8n-egress")]["spec"]["egress"]
        data = egress[1]
        self.assertEqual(sorted(p["port"] for p in data["ports"]), [5432, 6379])
        self.assertTrue(all(peer["ipBlock"]["cidr"].startswith("10.0.10") for peer in data["to"]))
        self.assertIn("169.254.0.0/16", egress[2]["to"][0]["ipBlock"]["except"])

    def test_prod_overlay(self):
        _, docs = render("-f", str(CHART_DIR / "values-prod.yaml"))
        objs = by_name(docs)
        self.assertEqual(objs[("PodDisruptionBudget", "n8n-main")]["spec"]["maxUnavailable"], 0)
        self.assertEqual(objs[("ScaledObject", "n8n-worker")]["spec"]["maxReplicaCount"], 30)
        sgp = objs[("SecurityGroupPolicy", "n8n")]["spec"]
        self.assertEqual(sgp["securityGroups"]["groupIds"], ["sg-0123456789abcdef0"])

    def test_policy_clean_on_both_value_sets(self):
        self.assertEqual([f.text() for f in check_chart_policy.check_text(self.text, "chart")], [])
        prod, _ = render("-f", str(CHART_DIR / "values-prod.yaml"))
        self.assertEqual([f.text() for f in check_chart_policy.check_text(prod, "prod")], [])

    def test_schema_rejects_unsafe_values(self):
        for args in (["--set", "main.replicas=2"], ["--set", "image.tag=latest"],
                     ["--set", "redis.tls=false"], ["--set", "keda.cooldownPeriod=10"],
                     ["--set", "publicUrl=http://n8n.example.com/"]):
            with self.subTest(args=args):
                proc = subprocess.run([HELM, "template", "x", str(CHART_DIR), *args],
                                      capture_output=True, text=True, timeout=120, check=False)
                self.assertNotEqual(proc.returncode, 0)

    def test_checksum_follows_spc_mapping(self):
        key = "checksum/secretproviderclass"
        base = self.objs[("Deployment", "n8n-worker")]["spec"]["template"]["metadata"]["annotations"][key]
        _, moved = render("--set", "secrets.redisAuth.secretName=n8n/other")
        new = by_name(moved)[("Deployment", "n8n-worker")]["spec"]["template"]["metadata"]["annotations"][key]
        self.assertNotEqual(base, new)


class ChartTerraformAgreementTests(unittest.TestCase):
    """Names that must match across Terraform and the chart (no helm needed)."""

    def tf_default(self, var):
        text = (MODULE_DIR / "variables.tf").read_text()
        block = text[text.index(f'variable "{var}"'):]
        return re.search(r'default\s*=\s*"([^"]+)"', block).group(1)

    def test_defaults_agree(self):
        values = yaml_lite.load_all((CHART_DIR / "values.yaml").read_text())[0]
        self.assertEqual(values["serviceAccount"]["name"], self.tf_default("service_account"))
        self.assertEqual(values["secrets"]["encryptionKey"]["secretName"], self.tf_default("encryption_key_secret_name"))
        self.assertEqual(values["secrets"]["db"]["secretName"], self.tf_default("db_app_secret_name"))
        self.assertEqual(values["secrets"]["redisAuth"]["secretName"], self.tf_default("redis_auth_secret_name"))


if __name__ == "__main__":
    unittest.main()
