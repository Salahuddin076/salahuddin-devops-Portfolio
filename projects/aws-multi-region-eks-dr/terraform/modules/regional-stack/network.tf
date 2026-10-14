# Three-tier VPC across three AZs:
#   public  /20s - ALBs (created by the AWS Load Balancer Controller) and NAT
#   private /19s - EKS nodes and pods (VPC CNI gives pods VPC IPs, hence the size)
#   data    /22s - Aurora and Valkey, no route to the internet at all
#
# Subnet tags are what the Load Balancer Controller uses to discover where to
# put the ALB it creates from the Ingress (kubernetes.io/role/elb).

data "aws_availability_zones" "available" {
  state = "available"

  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  azs     = slice(data.aws_availability_zones.available.names, 0, var.az_count)
  az_keys = { for i, az in local.azs : az => i }

  # /16 example: public 10.x.0.0/20..10.x.32.0/20, private 10.x.64.0/19..,
  # data 10.x.192.0/22.. Offsets keep the tiers apart for any /16-/20 input.
  public_cidrs  = { for az, i in local.az_keys : az => cidrsubnet(var.vpc_cidr, 4, i) }
  private_cidrs = { for az, i in local.az_keys : az => cidrsubnet(var.vpc_cidr, 3, i + 2) }
  data_cidrs    = { for az, i in local.az_keys : az => cidrsubnet(var.vpc_cidr, 6, i + 48) }

  nat_azs = var.nat_gateway_per_az ? local.azs : [local.azs[0]]

  cluster_name = "${var.name}-eks"
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.tags, { Name = "${var.name}-vpc" })
}

# Lock down the default security group: nothing should use it.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name}-default-unused" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name}-igw" })
}

resource "aws_subnet" "public" {
  for_each = local.public_cidrs

  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = each.value

  tags = merge(var.tags, {
    Name                                          = "${var.name}-public-${each.key}"
    tier                                          = "public"
    "kubernetes.io/role/elb"                      = "1"
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  })
}

resource "aws_subnet" "private" {
  for_each = local.private_cidrs

  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = each.value

  tags = merge(var.tags, {
    Name                                          = "${var.name}-private-${each.key}"
    tier                                          = "private"
    "kubernetes.io/role/internal-elb"             = "1"
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  })
}

resource "aws_subnet" "data" {
  for_each = local.data_cidrs

  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = each.value

  tags = merge(var.tags, {
    Name = "${var.name}-data-${each.key}"
    tier = "data"
  })
}

resource "aws_eip" "nat" {
  for_each = toset(local.nat_azs)

  domain = "vpc"
  tags   = merge(var.tags, { Name = "${var.name}-nat-${each.key}" })
}

resource "aws_nat_gateway" "this" {
  for_each = toset(local.nat_azs)

  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = aws_subnet.public[each.key].id

  tags       = merge(var.tags, { Name = "${var.name}-nat-${each.key}" })
  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name}-public" })
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

# One private route table per AZ. With a single NAT gateway every AZ routes to
# it (cross-AZ egress); with one per AZ, each AZ keeps its own egress path.
resource "aws_route_table" "private" {
  for_each = local.private_cidrs

  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name}-private-${each.key}" })
}

resource "aws_route" "private_nat" {
  for_each = aws_route_table.private

  route_table_id         = each.value.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[var.nat_gateway_per_az ? each.key : local.azs[0]].id
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[each.key].id
}

# Data subnets: local routes only.
resource "aws_route_table" "data" {
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name}-data" })
}

resource "aws_route_table_association" "data" {
  for_each = aws_subnet.data

  subnet_id      = each.value.id
  route_table_id = aws_route_table.data.id
}

# S3 gateway endpoint: image layers from ECR and app traffic to S3 skip NAT.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for rt in aws_route_table.private : rt.id]

  tags = merge(var.tags, { Name = "${var.name}-s3" })
}

# Data tier security groups. Ingress only from the EKS cluster security group,
# which the managed nodes (and therefore the pods) use.
resource "aws_security_group" "db" {
  name        = "${var.name}-aurora"
  description = "Aurora PostgreSQL: 5432 from EKS nodes and pods only"
  vpc_id      = aws_vpc.this.id
  tags        = merge(var.tags, { Name = "${var.name}-aurora" })
}

resource "aws_vpc_security_group_ingress_rule" "db_from_eks" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "PostgreSQL from the EKS cluster security group"
}

resource "aws_security_group" "cache" {
  name        = "${var.name}-valkey"
  description = "Valkey: 6379 from EKS nodes and pods only"
  vpc_id      = aws_vpc.this.id
  tags        = merge(var.tags, { Name = "${var.name}-valkey" })
}

resource "aws_vpc_security_group_ingress_rule" "cache_from_eks" {
  security_group_id            = aws_security_group.cache.id
  referenced_security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  description                  = "Valkey from the EKS cluster security group"
}

# Aurora's subnet group lives here (it is regional and tied to this VPC); the
# global-data module places the regional Aurora cluster into it.
resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-aurora"
  subnet_ids = [for s in aws_subnet.data : s.id]
  tags       = var.tags
}
