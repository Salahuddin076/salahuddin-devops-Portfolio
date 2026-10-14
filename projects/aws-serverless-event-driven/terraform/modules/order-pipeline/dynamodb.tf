# Single table, two item types:
#   IDEMPOTENCY#<key>  status, request_hash, result, lock_expires_at, expires_at (TTL)
#   ORDER#<orderId>    order state; no expires_at, so orders never expire
resource "aws_dynamodb_table" "orders" {
  name         = "${var.name_prefix}-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  # Encryption at rest is always on (AWS owned key). A customer managed key
  # is a one-line change if key policy control or CloudTrail key usage
  # records are required.

  deletion_protection_enabled = var.table_deletion_protection

  tags = var.tags
}
