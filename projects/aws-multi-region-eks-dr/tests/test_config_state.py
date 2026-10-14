"""Config validation, the state file and the audit log on disk."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from helpers import DR, EXAMPLE_CONFIG, GCID, PRIMARY, build

from failover.audit import AuditLog
from failover.config import ConfigError, parse_config
from failover.state import StateStore

BASE = json.loads(EXAMPLE_CONFIG.read_text())


def mutate(fn):
    data = copy.deepcopy(BASE)
    fn(data)
    return data


class ConfigTests(unittest.TestCase):
    def test_example_config_parses(self):
        c = parse_config(BASE)
        self.assertEqual((c.primary_region, c.dr_region, c.global_cluster_id), (PRIMARY, DR, GCID))
        self.assertEqual(c.other(PRIMARY), DR)
        self.assertEqual(c.regions[DR].active_workers, 2)

    def test_rejections(self):
        cases = {
            "same regions": lambda d: d.update(dr_region=PRIMARY),
            "bad region": lambda d: d.update(primary_region="useast1"),
            "missing gcid": lambda d: d.pop("global_cluster_id"),
            "zero lag": lambda d: d.update(max_replication_lag_seconds=0),
            "extra region": lambda d: d["regions"].update({"eu-west-1": d["regions"][PRIMARY]}),
            "zero workers": lambda d: d["regions"][DR]["active_scale"].update(workers=0),
            "missing context": lambda d: d["regions"][DR].pop("kube_context"),
        }
        for name, fn in cases.items():
            with self.subTest(name), self.assertRaises(ConfigError):
                parse_config(mutate(fn))

    def test_other_rejects_unknown_region(self):
        with self.assertRaises(ConfigError):
            parse_config(BASE).other("eu-west-1")


class StateFileTests(unittest.TestCase):
    def test_atomic_save_and_reload(self):
        with tempfile.TemporaryDirectory() as d:
            store = StateStore(Path(d) / "nested" / "state.json")
            state = store.load(GCID, PRIMARY)
            self.assertEqual(state["writer_region"], PRIMARY)
            state["epoch"] = 3
            store.save(state)
            self.assertEqual(store.load(GCID, PRIMARY)["epoch"], 3)
            self.assertEqual([p.name for p in (Path(d) / "nested").iterdir()], ["state.json"])

    def test_state_for_another_cluster_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            store = StateStore(Path(d) / "state.json")
            store.save(store.load("other-global", PRIMARY))
            with self.assertRaises(ValueError):
                store.load(GCID, PRIMARY)

    def test_audit_log_lines_are_json_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "audit.jsonl"
            orch, _, _, _ = build("healthy", audit=AuditLog(path))
            orch.execute("planned", GCID, target=DR)
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 14)  # start + 6 x (started, completed) + end
            for line in lines:
                record = json.loads(line)
                self.assertEqual(set(record) - {"epoch"}, {
                    "ts", "actor", "global_cluster_id", "event", "run_id", "mode", "source", "target",
                    "step", "status", "detail"})


if __name__ == "__main__":
    unittest.main()
