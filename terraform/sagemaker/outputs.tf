
output "sagemaker_endpoint_name" {
  description = "SageMaker endpoint Name"
  value       = aws_sagemaker_endpoint.embedding_endpoint.name
}

output "sagemaker_endpoint_arn" {
  description = "ARN of the SageMaker endpoint"
  value       = aws_sagemaker_endpoint.embedding_endpoint.arn
}

output "setup_instructions" {
  description = "Instructions for setting up environment variables"
  value = <<-EOT
    
    ✅ SageMaker endpoint deployed successfully! 
    
    EOT
}