terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.100.0, < 7.0.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

data "aws_caller_identity" "current" {}

data "terraform_remote_state" "database" {
  backend = "local"

  config = {
    path = abspath("${path.module}/../database/terraform.tfstate")
  }
}

data "terraform_remote_state" "agents" {
  backend = "local"

  config = {
    path = abspath("${path.module}/../agents/terraform.tfstate")
  }
}

data "terraform_remote_state" "researcher" {
  backend = "local"

  config = {
    path = abspath("${path.module}/../researcher/terraform.tfstate")
  }
}

data "aws_lambda_function" "supervisor_agent" {
  function_name = data.terraform_remote_state.agents.outputs.lambda_functions["supervisor_agent"]
}

data "aws_lambda_function" "ibkr_order_api" {
  function_name = data.terraform_remote_state.agents.outputs.lambda_functions["ibkr_order_api"]
}

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

data "aws_cloudfront_response_headers_policy" "security_headers" {
  name = "Managed-SecurityHeadersPolicy"
}

locals {
  name_prefix = "sidechart"
  common_tags = {
    Project   = "sidechart"
    ManagedBy = "terraform"
    Component = "frontend"
  }

  frontend_dir = abspath("${path.module}/../../frontend")
  frontend_source_files = [
    for file in sort(tolist(fileset(local.frontend_dir, "**"))) : file
    if !startswith(file, ".next/")
    && !startswith(file, "node_modules/")
    && !startswith(file, "out/")
  ]
  frontend_source_hash = sha256(join("", [
    for file in local.frontend_source_files :
    "${file}:${filesha256("${local.frontend_dir}/${file}")}"
  ]))

  researcher_url    = trimsuffix(data.terraform_remote_state.researcher.outputs.researcher_url, "/")
  researcher_domain = trimprefix(local.researcher_url, "https://")
  frontend_bucket = coalesce(
    var.frontend_bucket_name,
    "${local.name_prefix}-frontend-${data.aws_caller_identity.current.account_id}"
  )
}

resource "aws_s3_bucket" "frontend" {
  bucket        = local.frontend_bucket
  force_destroy = var.frontend_bucket_force_destroy
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name_prefix}-frontend-oac"
  description                       = "Private S3 access for the SideChart frontend"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_apigatewayv2_api" "main" {
  name          = "${local.name_prefix}-frontend-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_credentials = false
    allow_headers     = ["authorization", "content-type"]
    allow_methods     = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    allow_origins     = ["*"]
    max_age           = 300
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 100
  }
}

resource "aws_apigatewayv2_integration" "supervisor_agent" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = data.aws_lambda_function.supervisor_agent.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "supervisor_agent" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /agents/supervisor/run"
  target    = "integrations/${aws_apigatewayv2_integration.supervisor_agent.id}"
}

resource "aws_lambda_permission" "supervisor_agent_api" {
  statement_id  = "AllowSideChartFrontendApi"
  action        = "lambda:InvokeFunction"
  function_name = data.aws_lambda_function.supervisor_agent.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/POST/agents/supervisor/run"
}

resource "aws_apigatewayv2_integration" "ibkr_order_api" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = data.aws_lambda_function.ibkr_order_api.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "ibkr_order_api" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /broker/ibkr/orders"
  target    = "integrations/${aws_apigatewayv2_integration.ibkr_order_api.id}"
}

resource "aws_lambda_permission" "ibkr_order_api" {
  statement_id  = "AllowSideChartApprovedOrderApi"
  action        = "lambda:InvokeFunction"
  function_name = data.aws_lambda_function.ibkr_order_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/POST/broker/ibkr/orders"
}

# The browser calls /api/*. CloudFront keeps the selected API cache behavior,
# removes the prefix, and forwards the original backend route to its origin.
resource "aws_cloudfront_function" "strip_api_prefix" {
  name    = "${local.name_prefix}-strip-api-prefix"
  runtime = "cloudfront-js-2.0"
  comment = "Remove the frontend-only /api prefix before origin forwarding"
  publish = true
  code    = <<-JAVASCRIPT
    function handler(event) {
      var request = event.request;
      if (request.uri === '/api' || request.uri === '/api/') {
        request.uri = '/';
      } else if (request.uri.indexOf('/api/') === 0) {
        request.uri = request.uri.substring(4);
      }
      return request;
    }
  JAVASCRIPT
}

resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  comment             = "SideChart frontend and API"
  price_class         = var.cloudfront_price_class
  http_version        = "http2and3"

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "frontend-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
    # Zero means CloudFront does not impose a response-completion deadline.
    response_completion_timeout = 0

    s3_origin_config {
      origin_access_identity = ""
    }
  }

  origin {
    domain_name                 = replace(aws_apigatewayv2_api.main.api_endpoint, "https://", "")
    origin_id                   = "frontend-api"
    response_completion_timeout = 0

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # The researcher service exposes the complete local FastAPI route set.
  # CloudFront allows a longer origin read timeout than HTTP API integrations,
  # which is important for market pipelines and synchronous research runs.
  origin {
    domain_name                 = local.researcher_domain
    origin_id                   = "researcher-api"
    response_completion_timeout = 0

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "https-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_keepalive_timeout = 5
      # Cold starts load the market-analysis stack before the origin can send
      # its first response byte. The account's standard CloudFront quota allows
      # up to 120 seconds, which covers the measured cold pipeline duration.
      origin_read_timeout = 120
    }
  }

  default_cache_behavior {
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "frontend-s3"
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_optimized.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
  }

  ordered_cache_behavior {
    path_pattern               = "/api/agents/supervisor/run"
    allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "frontend-api"
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.strip_api_prefix.arn
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/api/broker/ibkr/orders"
    allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "frontend-api"
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.strip_api_prefix.arn
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/api/*"
    allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "researcher-api"
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.strip_api_prefix.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
    # CloudFront fixes this value to TLSv1 for its default certificate. A
    # custom ACM certificate is required before a stricter minimum can apply.
    minimum_protocol_version = "TLSv1"
  }

  depends_on = [
    aws_apigatewayv2_route.ibkr_order_api,
    aws_apigatewayv2_route.supervisor_agent,
    aws_apigatewayv2_stage.default,
  ]
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontReadOnly"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.frontend.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.main.arn
          }
        }
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

resource "terraform_data" "frontend_deployment" {
  count = var.deploy_frontend ? 1 : 0

  triggers_replace = {
    frontend_source_hash = local.frontend_source_hash
    deployment_script    = filesha256("${path.module}/deploy_frontend.py")
    api_base_url         = "/api"
    long_api_base_url    = local.researcher_url
    bucket               = aws_s3_bucket.frontend.id
    distribution_id      = aws_cloudfront_distribution.main.id
  }

  provisioner "local-exec" {
    working_dir = path.module
    command = join(" ", [
      "python3",
      "deploy_frontend.py",
      "--frontend-dir", local.frontend_dir,
      "--api-base-url", "/api",
      "--long-running-api-base-url", local.researcher_url,
      "--bucket", aws_s3_bucket.frontend.id,
      "--distribution-id", aws_cloudfront_distribution.main.id,
      "--region", var.aws_region,
    ])
  }

  depends_on = [aws_s3_bucket_policy.frontend]
}
