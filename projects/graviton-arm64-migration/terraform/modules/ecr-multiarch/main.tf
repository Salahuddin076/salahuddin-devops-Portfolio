# One ECR repository per service, holding one multi-arch manifest list per
# tag. `docker buildx build --platform linux/amd64,linux/arm64 --push` writes
# a single tag here; the registry serves the right platform's image to each
# puller. Nothing in this module distinguishes architectures — that's the
# point: the registry side of the migration is a one-time setup, not a
# per-architecture resource.

resource "aws_ecr_repository" "this" {
  name                 = var.name
  image_tag_mutability = var.image_tag_mutability

  image_scanning_configuration {
    scan_on_push = var.scan_on_push
  }

  encryption_configuration {
    encryption_type = var.kms_key_arn == null ? "AES256" : "KMS"
    kms_key         = var.kms_key_arn
  }

  tags = var.tags
}

# Enhanced (continuous) scanning is opt-in and configured at the registry
# scope via a scanning configuration resource, filtered to this repository.
resource "aws_ecr_registry_scanning_configuration" "this" {
  count = var.enhanced_scanning ? 1 : 0

  scan_type = "ENHANCED"

  rule {
    scan_frequency = "CONTINUOUS_SCAN"
    repository_filter {
      filter      = aws_ecr_repository.this.name
      filter_type = "WILDCARD"
    }
  }
}

resource "aws_ecr_lifecycle_policy" "untagged" {
  count      = var.untagged_image_expiry_days > 0 ? 1 : 0
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire untagged images (orphaned buildx manifest-list layers) after ${var.untagged_image_expiry_days} days"
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = var.untagged_image_expiry_days
      }
      action = {
        type = "expire"
      }
    }]
  })
}
