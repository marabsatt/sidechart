variable "aws_region" {
  description = "AWS region containing the SideChart backend resources"
  type        = string
  default     = "us-east-1"
}

variable "frontend_bucket_name" {
  description = "Optional globally unique S3 bucket name; defaults to sidechart-frontend-<account-id>"
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.frontend_bucket_name == null || can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.frontend_bucket_name))
    error_message = "frontend_bucket_name must be a valid lowercase S3 bucket name."
  }
}

variable "frontend_bucket_force_destroy" {
  description = "Allow Terraform to delete the frontend bucket even when it contains deployed files"
  type        = bool
  default     = false
}

variable "cloudfront_price_class" {
  description = "CloudFront edge-location price class"
  type        = string
  default     = "PriceClass_100"

  validation {
    condition = contains(
      ["PriceClass_100", "PriceClass_200", "PriceClass_All"],
      var.cloudfront_price_class
    )
    error_message = "cloudfront_price_class must be PriceClass_100, PriceClass_200, or PriceClass_All."
  }
}

variable "deploy_frontend" {
  description = "Build the local Next.js app, sync it to S3, and invalidate CloudFront during apply"
  type        = bool
  default     = true
}
