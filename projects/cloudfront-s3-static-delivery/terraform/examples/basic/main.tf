module "static_site" {
  source = "../../modules/static-site"
  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  name_prefix    = var.name_prefix
  domain_names   = var.domain_names
  hosted_zone_id = var.hosted_zone_id
  price_class    = var.price_class

  # Optional CLOUDFRONT-scope web ACL (us-east-1), for example from the
  # cloud-security-waf-automation project's waf module with
  # scope = "CLOUDFRONT" and an aws.us_east_1 provider.
  web_acl_arn = var.web_acl_arn

  access_logs = { retention_days = 30 }

  tags = {
    cost-center = "web-platform"
  }
}

module "deployer" {
  source = "../../modules/github-oidc-deployer"

  role_name                  = "${var.name_prefix}-github-deploy"
  github_repository          = var.github_repository
  allowed_branches           = ["main"]
  github_environments        = var.github_environments
  create_oidc_provider       = var.existing_oidc_provider_arn == null
  existing_oidc_provider_arn = var.existing_oidc_provider_arn

  bucket_arn       = module.static_site.bucket_arn
  distribution_arn = module.static_site.distribution_arn

  tags = {
    cost-center = "web-platform"
  }
}
