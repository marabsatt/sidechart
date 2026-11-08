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
    planner    = aws_lambda_function.planner.function_name
    classifier     = aws_lambda_function.classifier.function_name
    reporter   = aws_lambda_function.reporter.function_name
    charter    = aws_lambda_function.charter.function_name
    sell_side_agent = aws_lambda_function.sell_side_agent.function_name
    supervisor = aws_lambda_function.supervisor.function_name
  }
}

output "setup_instructions" {
  description = "Instructions for testing the agents"
  value = <<-EOT
    
    ✅ Agent infrastructure deployed successfully!
    
    Lambda Functions:
    - Planner (Orchestrator): ${aws_lambda_function.planner.function_name}
    - Classifier: ${aws_lambda_function.classifier.function_name}
    - Reporter: ${aws_lambda_function.reporter.function_name}
    - Charter: ${aws_lambda_function.charter.function_name}
    - Sell Side Agent: ${aws_lambda_function.sell_side_agent.function_name}
    - Supervisor: ${aws_lambda_function.supervisor.function_name}
    
    SQS Queue: ${aws_sqs_queue.analysis_jobs.name}
    
    To test the system:
    1. First, package and deploy each agent's code:
       cd backend/planner && uv run package_docker.py --deploy
       cd backend/classifier && uv run package_docker.py --deploy
       cd backend/reporter && uv run package_docker.py --deploy
       cd backend/charter && uv run package_docker.py --deploy
       cd backend/sell_side_agent && uv run package_docker.py --deploy
       cd backend/supervisor && uv run package_docker.py --deploy
    
    2. Run the full integration test:
       cd backend/planner
       uv run run_full_test.py
    
    3. Monitor progress in CloudWatch Logs:
       - /aws/lambda/sidechart-planner
       - /aws/lambda/sidechart-classifier
       - /aws/lambda/sidechart-reporter
       - /aws/lambda/sidechart-charter
       - /aws/lambda/sidechart-sell_side_agent
       - /aws/lambda/sidechart-supervisor
    
    Bedrock Model: ${var.bedrock_model_id}
    Region: ${var.bedrock_region}
  EOT
}