output "vpc_id" {
  description = "Spoke VPC ID."
  value       = aws_vpc.this.id
}

output "cidr" {
  description = "Spoke CIDR (from the address plan)."
  value       = local.cidr
}

output "environment" {
  description = "Spoke environment (decides the TGW route table in the hub)."
  value       = local.environment
}

output "transit_gateway_attachment_id" {
  description = "Record this in the hub's spoke_attachment_ids to associate and propagate the spoke."
  value       = aws_ec2_transit_gateway_vpc_attachment.this.id
}

output "private_subnet_ids" {
  description = "Workload subnet IDs."
  value       = aws_subnet.private[*].id
}
