output "cloudfront_url" {
  description = "Public URL for the deployed SideChart frontend"
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "api_gateway_url" {
  description = "API Gateway URL used for dedicated agent integrations behind CloudFront"
  value       = aws_apigatewayv2_api.main.api_endpoint
}

output "s3_bucket_name" {
  description = "Private S3 bucket containing the exported Next.js application"
  value       = aws_s3_bucket.frontend.id
}

output "connected_resources" {
  description = "Backend resources connected to the frontend API layer"
  value = {
    aurora_cluster_arn  = data.terraform_remote_state.database.outputs.aurora_cluster_arn
    database_name       = data.terraform_remote_state.database.outputs.database_name
    sqs_queue_url       = data.terraform_remote_state.agents.outputs.sqs_queue_url
    researcher_url      = local.researcher_url
    sell_side_function  = data.terraform_remote_state.agents.outputs.lambda_functions["sell_side_agent"]
    supervisor_function = data.aws_lambda_function.supervisor_agent.function_name
  }
}

output "deployment_status" {
  description = "Whether Terraform is configured to publish the local frontend during apply"
  value       = var.deploy_frontend ? "Local frontend build and upload enabled" : "Infrastructure only; frontend upload disabled"
}

output "setup_instructions" {
  description = "Commands and URLs for validating the deployment"
  value       = <<-EOT
    SideChart frontend deployment complete.

    Frontend: https://${aws_cloudfront_distribution.main.domain_name}
    API health: https://${aws_cloudfront_distribution.main.domain_name}/api/health
    S3 bucket: ${aws_s3_bucket.frontend.id}

    Terraform builds frontend/ with NEXT_PUBLIC_API_BASE_URL=/api, uploads the
    generated frontend/out directory, and invalidates CloudFront whenever the
    local frontend source hash changes.
  EOT
}
