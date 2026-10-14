# Containers only. There is deliberately no aws_secretsmanager_secret_version:
# a version resource would put the plaintext in Terraform state (and in plan
# output when it changed). Values are written out of band with
# `aws secretsmanager put-secret-value` (docs/operations.md).

resource "aws_secretsmanager_secret" "db" {
  name                    = var.db_secret_name
  description             = "${var.name} DB credentials: JSON {username, password, host}. Value set out of band."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret" "api_key" {
  name                    = var.api_key_secret_name
  description             = "${var.name} third-party API key (plain string). Value set out of band."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

# Optional managed rotation of the DB credential with an existing Lambda.
# rotate_immediately = false: enabling rotation must not fire a rotation
# before the first value has been put (the Lambda's createSecret step needs
# an AWSCURRENT version to copy).
resource "aws_secretsmanager_secret_rotation" "db" {
  count = var.rotation_lambda_arn == null ? 0 : 1

  secret_id           = aws_secretsmanager_secret.db.id
  rotation_lambda_arn = var.rotation_lambda_arn
  rotate_immediately  = false

  rotation_rules {
    automatically_after_days = var.rotation_days
  }
}
