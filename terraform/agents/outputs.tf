output "sqs_queue_url" {
  description = "URL of the SQS queue for job submission"
  value       = aws_sqs_queue.analysis_jobs.url
}

output "sqs_queue_arn" {
  description = "ARN of the SQS queue"
  value       = aws_sqs_queue.analysis_jobs.arn
}

output "lambda_functions" {
  description = "Names of deployed Lambda functions"
  value = {
    for agent, function in aws_lambda_function.agent :
    agent => function.function_name
  }
}

output "ecr_repositories" {
  description = "ECR repository URLs used by the Lambda agent images"
  value = {
    for agent, repository in aws_ecr_repository.agent_images :
    agent => repository.repository_url
  }
}

output "setup_instructions" {
  description = "Instructions for testing the agents"
  value       = <<-EOT
    
    ✅ Agent infrastructure deployed successfully!
    
    Lambda Functions:
    - Planner (Orchestrator): ${aws_lambda_function.agent["planner"].function_name}
    - Classifier: ${aws_lambda_function.agent["classifier"].function_name}
    - Reporter: ${aws_lambda_function.agent["reporter"].function_name}
    - Charter: ${aws_lambda_function.agent["charter"].function_name}
    - Sell Side Agent: ${aws_lambda_function.agent["sell_side_agent"].function_name}
    - Supervisor: ${aws_lambda_function.agent["supervisor_agent"].function_name}
    
    SQS Queue: ${aws_sqs_queue.analysis_jobs.name}
    
    To test the system:
    Agent code is deployed as ECR container images. Terraform builds and pushes
    content-addressed images automatically during `terraform apply`.

    To deploy:
       cd terraform/agents
       terraform apply
    
    2. Run the full integration test:
       cd backend/planner
       uv run run_full_test.py
    
    3. Monitor progress in CloudWatch Logs:
       - /aws/lambda/sidechart-planner
       - /aws/lambda/sidechart-classifier
       - /aws/lambda/sidechart-reporter
       - /aws/lambda/sidechart-charter
       - /aws/lambda/sidechart-sell-side-agent
       - /aws/lambda/sidechart-supervisor-agent
    
    Bedrock Model: ${var.bedrock_model_id}
    Region: ${var.bedrock_region}
  EOT
}
