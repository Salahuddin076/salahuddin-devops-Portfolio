"""Text-level guards on Terraform invariants that `terraform validate` alone
cannot see: redundancy of the VPN connectivity, and deny-by-default
segmentation with no accidental 0.0.0.0/0 in the regulated zone."""

from __future__ import annotations

import unittest

from helpers import TERRAFORM

CONNECTIVITY = TERRAFORM / "modules" / "connectivity"
SEGMENTATION = TERRAFORM / "modules" / "segmentation"
REFERENCE = TERRAFORM / "examples" / "reference"


def read_dir(path):
    return "\n".join(p.read_text() for p in sorted(path.glob("*.tf")))


class ConnectivityModuleTests(unittest.TestCase):
    main = (CONNECTIVITY / "main.tf").read_text()
    variables = (CONNECTIVITY / "variables.tf").read_text()
    outputs = (CONNECTIVITY / "outputs.tf").read_text()

    def test_requires_at_least_two_on_prem_gateways(self) -> None:
        self.assertIn("length(var.on_prem_gateways) >= 2", self.variables)
        self.assertIn("single point of failure", self.variables)

    def test_on_prem_ips_restricted_to_documentation_ranges(self) -> None:
        self.assertIn("192\\\\.0\\\\.2\\\\.|198\\\\.51\\\\.100\\\\.|203\\\\.0\\\\.113\\\\.", self.variables)

    def test_one_vpn_connection_per_customer_gateway(self) -> None:
        self.assertIn('resource "aws_customer_gateway" "this"', self.main)
        self.assertIn('resource "aws_vpn_connection" "this"', self.main)
        self.assertIn("for_each = aws_customer_gateway.this", self.main)

    def test_tunnel_count_output_doubles_connection_count(self) -> None:
        self.assertIn('value       = length(aws_vpn_connection.this) * 2', self.outputs)

    def test_route_propagation_is_scoped_to_named_route_tables(self) -> None:
        self.assertIn('resource "aws_vpn_gateway_route_propagation" "this"', self.main)
        self.assertIn("for_each = toset(var.route_table_ids)", self.main)


class SegmentationModuleTests(unittest.TestCase):
    main = (SEGMENTATION / "main.tf").read_text()
    variables = (SEGMENTATION / "variables.tf").read_text()

    def test_zone_is_restricted_to_edge_or_regulated(self) -> None:
        self.assertIn('contains(["edge", "regulated"], var.zone)', self.variables)

    def test_security_group_has_no_default_allow_all_block(self) -> None:
        # No bare `ingress { ... 0.0.0.0/0 ... }` or unconditional egress
        # block outside the dynamic blocks driven by allowed_ingress/egress.
        self.assertEqual(self.main.count("dynamic \"ingress\""), 1)
        self.assertEqual(self.main.count("dynamic \"egress\""), 1)
        self.assertNotIn('cidr_blocks = ["0.0.0.0/0"]', self.main)

    def test_regulated_zone_precondition_blocks_open_ingress_and_egress(self) -> None:
        self.assertIn('var.zone != "regulated" || alltrue', self.main)
        self.assertIn('!contains(coalesce(rule.cidr_blocks, []), "0.0.0.0/0")', self.main)
        self.assertEqual(self.main.count('!contains(coalesce(rule.cidr_blocks, []), "0.0.0.0/0")'), 2)

    def test_exactly_one_of_cidr_or_security_group_enforced(self) -> None:
        self.assertIn("Each allowed_ingress/allowed_egress entry must set exactly one", self.main)

    def test_network_acl_has_explicit_deny_all_floor(self) -> None:
        self.assertIn('resource "aws_network_acl_rule" "deny_all_ingress"', self.main)
        self.assertIn('resource "aws_network_acl_rule" "deny_all_egress"', self.main)
        self.assertIn('rule_action    = "deny"', self.main)
        self.assertIn("rule_number    = 32766", self.main)

    def test_network_acl_optional_and_defaults_on(self) -> None:
        self.assertIn('variable "enable_network_acl"', self.variables)
        self.assertRegex(self.variables, r'variable "enable_network_acl" \{[^}]*default\s+= true')


class ReferenceRootTests(unittest.TestCase):
    main = (REFERENCE / "main.tf").read_text()
    variables = (REFERENCE / "variables.tf").read_text()

    def test_wires_both_modules_and_both_zones(self) -> None:
        self.assertIn('source = "../../modules/connectivity"', self.main)
        self.assertIn('zone             = "edge"', self.main)
        self.assertIn('zone             = "regulated"', self.main)

    def test_only_the_regulated_route_table_gets_on_prem_propagation(self) -> None:
        self.assertIn("route_table_ids  = [aws_route_table.regulated.id]", self.main)
        self.assertNotIn("aws_route_table.edge.id]", self.main.replace("route_table_ids  = [aws_route_table.regulated.id]", ""))

    def test_no_module_references_the_others_sg_id_both_ways(self) -> None:
        # Guards the fix for a module dependency cycle: regulated_zone may
        # depend on edge_zone's output, but edge_zone must not depend on
        # regulated_zone's output (that would be a cycle Terraform rejects).
        self.assertIn("module.edge_zone.security_group_id", self.main)
        self.assertNotIn("module.regulated_zone.security_group_id", self.main)

    def test_default_on_prem_gateways_are_documentation_safe(self) -> None:
        self.assertIn("203.0.113.10", self.variables)
        self.assertIn("203.0.113.11", self.variables)
        self.assertNotIn("0.0.0.0/0", self.variables)


if __name__ == "__main__":
    unittest.main()
