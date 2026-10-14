output "transit_gateway_id" {
  description = "Transit Gateway ID, passed to spoke VPCs."
  value       = aws_ec2_transit_gateway.this.id
}

output "transit_gateway_arn" {
  description = "Transit Gateway ARN."
  value       = aws_ec2_transit_gateway.this.arn
}

output "route_table_ids" {
  description = "Environment -> TGW route table ID."
  value       = { for k, rt in aws_ec2_transit_gateway_route_table.this : k => rt.id }
}

output "propagation_matrix" {
  description = "Attachment environment -> route tables it propagates into. prod and nonprod never appear in each other's list."
  value       = local.propagate_into
}

output "egress_vpc_id" {
  description = "Centralized egress VPC ID."
  value       = aws_vpc.egress.id
}

output "nat_gateway_public_ips" {
  description = "Public IPs all spoke egress leaves from (for partner allow-lists)."
  value       = aws_eip.nat[*].public_ip
}

output "ram_resource_share_arn" {
  description = "RAM share for the Transit Gateway."
  value       = aws_ram_resource_share.tgw.arn
}
