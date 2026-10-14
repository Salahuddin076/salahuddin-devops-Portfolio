import unittest

import helpers  # noqa: F401
from yaml_subset import YamlSubsetError, YList, YMap, parse


class YamlSubsetTests(unittest.TestCase):
    def test_nested_mapping_and_lines(self):
        doc = parse("a: 1\nb:\n  c: two # comment\n  d: 'q: x'\n")
        self.assertEqual(doc["a"], "1")
        self.assertEqual(doc["b"]["c"], "two")
        self.assertEqual(doc["b"]["d"], "q: x")
        self.assertEqual(doc.lines["b"], 2)
        self.assertEqual(doc["b"].lines["d"], 4)

    def test_sequence_of_mappings(self):
        doc = parse("steps:\n  - uses: a/b@v1\n    with:\n      x: y\n  - run: echo hi\n")
        steps = doc["steps"]
        self.assertIsInstance(steps, YList)
        self.assertEqual(steps[0]["uses"], "a/b@v1")
        self.assertEqual(steps[0]["with"]["x"], "y")
        self.assertEqual(steps[1]["run"], "echo hi")
        self.assertEqual(steps.lines, [2, 5])

    def test_sequence_at_same_indent_as_key(self):
        doc = parse("paths:\n- a\n- b\nnext: 1\n")
        self.assertEqual(list(doc["paths"]), ["a", "b"])
        self.assertEqual(doc["next"], "1")

    def test_block_scalar_keeps_hash_and_blank_lines(self):
        doc = parse("run: |\n  echo a # not a comment\n\n  echo b\nnext: x\n")
        self.assertEqual(doc["run"], "echo a # not a comment\n\necho b")
        self.assertEqual(doc["next"], "x")

    def test_flow_values(self):
        doc = parse("branches: [main, 'dev']\nperms: {}\n")
        self.assertEqual(list(doc["branches"]), ["main", "dev"])
        self.assertIsInstance(doc["perms"], YMap)
        self.assertEqual(len(doc["perms"]), 0)

    def test_expression_and_url_values(self):
        doc = parse("a: ${{ github.sha }}\nb: https://example.com/x#frag\n")
        self.assertEqual(doc["a"], "${{ github.sha }}")
        self.assertEqual(doc["b"], "https://example.com/x#frag")

    def test_tab_indentation_rejected(self):
        with self.assertRaises(YamlSubsetError):
            parse("a:\n\tb: 1\n")

    def test_parses_every_repo_workflow(self):
        for path in sorted(helpers.REPO_WORKFLOWS.glob("*.yml")):
            with self.subTest(path=path.name):
                doc = parse(path.read_text(encoding="utf-8"))
                self.assertIn("jobs", doc)


if __name__ == "__main__":
    unittest.main()
