# ACM certificate for CloudFront. CloudFront only uses certificates from
# us-east-1, whatever region the rest of the stack is in, hence the alias.
# DNS validation: ACM gives one CNAME per name, written into the zone, and
# aws_acm_certificate_validation waits until ACM reports ISSUED. The
# distribution depends on that wait, so the first apply orders itself.

resource "aws_acm_certificate" "this" {
  provider = aws.us_east_1

  domain_name               = local.primary_domain
  subject_alternative_names = local.san_domains
  validation_method         = "DNS"
  key_algorithm             = "RSA_2048"

  tags = merge(local.tags, { Name = local.primary_domain })

  lifecycle {
    # A replacement certificate must exist before the old one is detached.
    create_before_destroy = true
  }
}

resource "aws_route53_record" "certificate_validation" {
  for_each = {
    for dvo in aws_acm_certificate.this.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id = var.hosted_zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 300

  # Re-validating (for example after a replacement) rewrites the same name.
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "this" {
  provider = aws.us_east_1

  certificate_arn         = aws_acm_certificate.this.arn
  validation_record_fqdns = [for r in aws_route53_record.certificate_validation : r.fqdn]
}

# Alias records: A and AAAA for every hostname, pointing at the distribution.
# Alias queries to CloudFront are free, unlike a CNAME.
resource "aws_route53_record" "alias" {
  for_each = local.alias_records

  zone_id = var.hosted_zone_id
  name    = each.value.name
  type    = each.value.type

  alias {
    name                   = aws_cloudfront_distribution.this.domain_name
    zone_id                = aws_cloudfront_distribution.this.hosted_zone_id
    evaluate_target_health = false
  }
}
