# Containers only. There is deliberately no aws_secretsmanager_secret_version:
# a version resource puts the plaintext in state. Values are put out of band
# (docs/operations.md, "Install"):
#   encryption key  openssl rand -base64 48, once, before n8n first starts
#   redis auth      openssl rand -hex 32, before the replication group exists
#   db app creds    after RDS exists, when the n8n role is created in Postgres

resource "aws_secretsmanager_secret" "encryption_key" {
  name                    = var.encryption_key_secret_name
  description             = "${var.name}: n8n N8N_ENCRYPTION_KEY. Never rotate casually; see docs/operations.md."
  kms_key_id              = aws_kms_key.n8n.arn
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret" "db_app" {
  name                    = var.db_app_secret_name
  description             = "${var.name}: n8n application role on RDS, JSON {username, password}."
  kms_key_id              = aws_kms_key.n8n.arn
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret" "redis_auth" {
  name                    = var.redis_auth_secret_name
  description             = "${var.name}: ElastiCache AUTH token (plain string). Read by n8n (CSI) and by KEDA (awsSecretManager)."
  kms_key_id              = aws_kms_key.n8n.arn
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

# Read at apply time and handed to a write-only argument: neither the plan nor
# the state ever contains the token. The secret must already hold a value, so
# the first apply is two-phase (docs/operations.md).
ephemeral "aws_secretsmanager_secret_version" "redis_auth" {
  secret_id = aws_secretsmanager_secret.redis_auth.id
}
