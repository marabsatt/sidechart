terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  agent_directories = {
    planner              = "planner"
    classifier           = "classifier"
    reporter             = "reporter"
    charter              = "charter"
    sell_side_agent      = "sell_side_agent"
    supervisor_agent     = "supervisor_agent"
    ibkr_event_processor = "ibkr_event_processor"
    ibkr_order_api       = "ibkr_order_api"
  }

  agent_repository_names = {
    planner              = "sidechart-planner"
    classifier           = "sidechart-classifier"
    reporter             = "sidechart-reporter"
    charter              = "sidechart-charter"
    sell_side_agent      = "sidechart-sell-side-agent"
    supervisor_agent     = "sidechart-supervisor-agent"
    ibkr_event_processor = "sidechart-ibkr-event-processor"
    ibkr_order_api       = "sidechart-ibkr-order-api"
  }

  agent_source_files = {
    for agent, directory in local.agent_directories :
    agent => sort([
      for file in fileset("${path.module}/../../backend/${directory}", "**") : file
      if !can(regex("(^|/)(__pycache__|\\.pytest_cache)(/|$)|\\.(pyc|zip)$", file))
    ])
  }

  shared_source_files = sort([
    for file in fileset("${path.module}/../../src", "**") : file
    if !can(regex("(^|/)(__pycache__|\\.pytest_cache)(/|$)|\\.pyc$", file))
  ])

  shared_source_hash = sha256(join("", concat(
    [
      filesha256("${path.module}/../../pyproject.toml"),
      filesha256("${path.module}/../../uv.lock"),
      filesha256("${path.module}/../../.dockerignore"),
    ],
    [
      for file in local.shared_source_files :
      filesha256("${path.module}/../../src/${file}")
    ]
  )))

  agent_source_hashes = {
    for agent, directory in local.agent_directories :
    agent => sha256(join("", concat(
      [
        for file in local.agent_source_files[agent] :
        filesha256("${path.module}/../../backend/${directory}/${file}")
      ],
      contains(["sell_side_agent", "supervisor_agent"], agent) ? [local.shared_source_hash] : []
    )))
  }

  agent_image_tags = {
    for agent, source_hash in local.agent_source_hashes :
    agent => substr(source_hash, 0, 32)
  }

  common_environment = {
    AURORA_CLUSTER_ARN  = var.aurora_cluster_arn
    AURORA_SECRET_ARN   = var.aurora_secret_arn
    AURORA_DATABASE     = "sidechart"
    DATABASE_NAME       = "sidechart"
    BEDROCK_MODEL_ID    = var.bedrock_model_id
    BEDROCK_REGION      = var.bedrock_region
    DEFAULT_AWS_REGION  = var.aws_region
    LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
    LANGFUSE_SECRET_KEY = var.langfuse_secret_key
    LANGFUSE_HOST       = var.langfuse_host
    OPENAI_API_KEY      = var.openai_api_key
  }

  lambda_agents = {
    planner = {
      function_name     = "sidechart-planner"
      timeout           = 900
      memory_size       = 2048
      ephemeral_storage = 2048
      environment = merge(local.common_environment, {
        VECTOR_BUCKET      = var.vector_bucket
        SAGEMAKER_ENDPOINT = var.sagemaker_endpoint
        TAGGER_FUNCTION    = "sidechart-classifier"
        REPORTER_FUNCTION  = "sidechart-reporter"
        CHARTER_FUNCTION   = "sidechart-charter"
      })
    }
    classifier = {
      function_name     = "sidechart-classifier"
      timeout           = 300
      memory_size       = 1024
      ephemeral_storage = 1024
      environment       = local.common_environment
    }
    reporter = {
      function_name     = "sidechart-reporter"
      timeout           = 300
      memory_size       = 1024
      ephemeral_storage = 1024
      environment = merge(local.common_environment, {
        VECTOR_BUCKET      = var.vector_bucket
        SAGEMAKER_ENDPOINT = var.sagemaker_endpoint
      })
    }
    charter = {
      function_name     = "sidechart-charter"
      timeout           = 300
      memory_size       = 1024
      ephemeral_storage = 1024
      environment       = local.common_environment
    }
    sell_side_agent = {
      function_name     = "sidechart-sell-side-agent"
      timeout           = 900
      memory_size       = 2048
      ephemeral_storage = 2048
      environment       = local.common_environment
    }
    supervisor_agent = {
      function_name     = "sidechart-supervisor-agent"
      timeout           = 900
      memory_size       = 2048
      ephemeral_storage = 2048
      environment       = local.common_environment
    }
    ibkr_event_processor = {
      function_name     = "sidechart-ibkr-event-processor"
      timeout           = 60
      memory_size       = 512
      ephemeral_storage = 512
      environment = {
        AURORA_CLUSTER_ARN = var.aurora_cluster_arn
        AURORA_SECRET_ARN  = var.aurora_secret_arn
        AURORA_DATABASE    = "sidechart"
        DEFAULT_AWS_REGION = var.aws_region
      }
    }
    ibkr_order_api = {
      function_name     = "sidechart-ibkr-order-api"
      timeout           = 30
      memory_size       = 512
      ephemeral_storage = 512
      environment = {
        AURORA_CLUSTER_ARN     = var.aurora_cluster_arn
        AURORA_SECRET_ARN      = var.aurora_secret_arn
        AURORA_DATABASE        = "sidechart"
        DEFAULT_AWS_REGION     = var.aws_region
        IBKR_COMMAND_QUEUE_URL = aws_sqs_queue.ibkr_commands.url
        IBKR_ACCOUNT_MODE      = "PAPER"
      }
    }
  }
}

# Async orchestration queue.
resource "aws_sqs_queue" "analysis_jobs_dlq" {
  name = "sidechart-analysis-jobs-dlq"

  tags = {
    Project = "sidechart"
  }
}

resource "aws_sqs_queue" "analysis_jobs" {
  name                       = "sidechart-analysis-jobs"
  delay_seconds              = 0
  max_message_size           = 262144
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 10
  visibility_timeout_seconds = 910

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.analysis_jobs_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Project = "sidechart"
  }
}

# The IBKR bridge uses dedicated queues. Reusing analysis_jobs would create
# competing consumers and allow the local connector to steal planner work.
resource "aws_sqs_queue" "ibkr_commands_dlq" {
  name                        = "sidechart-ibkr-commands-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  message_retention_seconds   = 1209600

  tags = { Project = "sidechart", Component = "ibkr-connector" }
}

resource "aws_sqs_queue" "ibkr_commands" {
  name                        = "sidechart-ibkr-commands.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  message_retention_seconds   = 86400
  receive_wait_time_seconds   = 20
  visibility_timeout_seconds  = 60

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ibkr_commands_dlq.arn
    maxReceiveCount     = 5
  })

  tags = { Project = "sidechart", Component = "ibkr-connector" }
}

resource "aws_sqs_queue" "ibkr_events_dlq" {
  name                        = "sidechart-ibkr-events-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  message_retention_seconds   = 1209600

  tags = { Project = "sidechart", Component = "ibkr-connector" }
}

resource "aws_sqs_queue" "ibkr_events" {
  name                        = "sidechart-ibkr-events.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  message_retention_seconds   = 1209600
  receive_wait_time_seconds   = 20
  visibility_timeout_seconds  = 90

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ibkr_events_dlq.arn
    maxReceiveCount     = 5
  })

  tags = { Project = "sidechart", Component = "ibkr-connector" }
}

# This role is intentionally usable only through IAM Roles Anywhere. The local
# connector gets temporary credentials and no direct database access.
resource "aws_iam_role" "ibkr_connector" {
  name = "sidechart-ibkr-connector-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "rolesanywhere.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:SetSourceIdentity", "sts:TagSession"]
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })

  tags = { Project = "sidechart", Component = "ibkr-connector" }
}

resource "aws_iam_role_policy" "ibkr_connector" {
  name = "sidechart-ibkr-connector-queues"
  role = aws_iam_role.ibkr_connector.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage", "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.ibkr_commands.arn
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.ibkr_events.arn
      }
    ]
  })
}

resource "aws_iam_role" "ibkr_event_processor" {
  name = "sidechart-ibkr-event-processor-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRole",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
  tags = { Project = "sidechart", Component = "ibkr-connector" }
}

resource "aws_iam_role_policy_attachment" "ibkr_event_processor_basic" {
  role       = aws_iam_role.ibkr_event_processor.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "ibkr_event_processor" {
  name = "sidechart-ibkr-event-processor"
  role = aws_iam_role.ibkr_event_processor.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.ibkr_events.arn
      },
      {
        Effect = "Allow"
        Action = [
          "rds-data:ExecuteStatement", "rds-data:BeginTransaction",
          "rds-data:CommitTransaction", "rds-data:RollbackTransaction"
        ]
        Resource = var.aurora_cluster_arn
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = var.aurora_secret_arn
      }
    ]
  })
}

resource "aws_iam_role" "ibkr_order_api" {
  name = "sidechart-ibkr-order-api-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRole",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
  tags = { Project = "sidechart", Component = "ibkr-connector" }
}

resource "aws_iam_role_policy_attachment" "ibkr_order_api_basic" {
  role       = aws_iam_role.ibkr_order_api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "ibkr_order_api" {
  name = "sidechart-ibkr-order-api"
  role = aws_iam_role.ibkr_order_api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.ibkr_commands.arn
      },
      {
        Effect = "Allow"
        Action = [
          "rds-data:ExecuteStatement", "rds-data:BeginTransaction",
          "rds-data:CommitTransaction", "rds-data:RollbackTransaction"
        ]
        Resource = var.aurora_cluster_arn
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = var.aurora_secret_arn
      }
    ]
  })
}

# Shared Lambda execution role.
resource "aws_iam_role" "lambda_agents_role" {
  name = "sidechart-lambda-agents-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })

  tags = {
    Project = "sidechart"
  }
}

resource "aws_iam_role_policy" "lambda_agents_policy" {
  name = "sidechart-lambda-agents-policy"
  role = aws_iam_role.lambda_agents_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
        ]
        Resource = aws_sqs_queue.analysis_jobs.arn
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:sidechart-*"
      },
      {
        Effect = "Allow"
        Action = [
          "rds-data:ExecuteStatement",
          "rds-data:BatchExecuteStatement",
          "rds-data:BeginTransaction",
          "rds-data:CommitTransaction",
          "rds-data:RollbackTransaction",
        ]
        Resource = var.aurora_cluster_arn
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = var.aurora_secret_arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::${var.vector_bucket}",
          "arn:aws:s3:::${var.vector_bucket}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3vectors:QueryVectors",
          "s3vectors:GetVectors",
        ]
        Resource = "arn:aws:s3vectors:${var.aws_region}:${data.aws_caller_identity.current.account_id}:bucket/${var.vector_bucket}/index/*"
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:InvokeEndpoint"]
        Resource = "arn:aws:sagemaker:${var.aws_region}:${data.aws_caller_identity.current.account_id}:endpoint/${var.sagemaker_endpoint}"
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:*:inference-profile/*",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_agents_basic" {
  role       = aws_iam_role.lambda_agents_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Retained for compatibility with previously uploaded ZIP artifacts. New
# deployments use ECR container images and do not read this bucket.
resource "aws_s3_bucket" "lambda_packages" {
  bucket = "sidechart-lambda-packages-${data.aws_caller_identity.current.account_id}"

  tags = {
    Project = "sidechart"
    Legacy  = "true"
  }
}

# Stop managing the legacy ZIP objects without deleting them. They are no
# longer deployment inputs, but retaining them makes this migration
# non-destructive and leaves rollback artifacts available.
removed {
  from = aws_s3_object.lambda_packages

  lifecycle {
    destroy = false
  }
}

# One ECR repository per Lambda keeps deployments and lifecycle policies
# isolated while allowing images up to Lambda's 10 GB container-image limit.
resource "aws_ecr_repository" "agent_images" {
  for_each = local.agent_repository_names

  name                 = each.value
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Project = "sidechart"
    Agent   = each.key
  }
}

resource "aws_ecr_lifecycle_policy" "agent_images" {
  for_each   = aws_ecr_repository.agent_images
  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the ten newest Lambda images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository_policy" "lambda_pull" {
  for_each   = aws_ecr_repository.agent_images
  repository = each.value.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "LambdaECRImageRetrievalPolicy"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = [
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
      ]
      Condition = {
        StringLike = {
          "aws:SourceArn" = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:sidechart-*"
        }
      }
    }]
  })
}

# Terraform builds and pushes each content-addressed image after its repository
# exists. A source change creates a new immutable tag and updates the Lambda.
resource "terraform_data" "agent_image" {
  for_each = local.agent_directories

  triggers_replace = {
    source_hash    = local.agent_source_hashes[each.key]
    repository_url = aws_ecr_repository.agent_images[each.key].repository_url
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/../.."
    command = join(" ", [
      "python3",
      "backend/build_agent_image.py",
      "--agent", each.key,
      "--repository-url", aws_ecr_repository.agent_images[each.key].repository_url,
      "--tag", local.agent_image_tags[each.key],
      "--region", var.aws_region,
      "--push",
    ])
  }

  depends_on = [aws_ecr_repository_policy.lambda_pull]
}

resource "aws_lambda_function" "agent" {
  for_each = local.lambda_agents

  function_name = each.value.function_name
  role = each.key == "ibkr_event_processor" ? aws_iam_role.ibkr_event_processor.arn : (
    each.key == "ibkr_order_api" ? aws_iam_role.ibkr_order_api.arn : aws_iam_role.lambda_agents_role.arn
  )
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.agent_images[each.key].repository_url}:${local.agent_image_tags[each.key]}"
  architectures = ["x86_64"]
  timeout       = each.value.timeout
  memory_size   = each.value.memory_size

  ephemeral_storage {
    size = each.value.ephemeral_storage
  }

  environment {
    variables = each.value.environment
  }

  tags = {
    Project = "sidechart"
    Agent   = each.key
  }

  depends_on = [
    terraform_data.agent_image,
    aws_iam_role_policy.lambda_agents_policy,
    aws_iam_role_policy_attachment.lambda_agents_basic,
  ]
}

resource "aws_lambda_event_source_mapping" "planner_sqs" {
  event_source_arn = aws_sqs_queue.analysis_jobs.arn
  function_name    = aws_lambda_function.agent["planner"].arn
  batch_size       = 1
}

resource "aws_lambda_event_source_mapping" "ibkr_events" {
  event_source_arn        = aws_sqs_queue.ibkr_events.arn
  function_name           = aws_lambda_function.agent["ibkr_event_processor"].arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]

  depends_on = [aws_iam_role_policy.ibkr_event_processor]
}

resource "aws_cloudwatch_log_group" "agent_logs" {
  for_each = local.lambda_agents

  name              = "/aws/lambda/${each.value.function_name}"
  retention_in_days = 7

  tags = {
    Project = "sidechart"
    Agent   = each.key
  }
}

# Preserve existing Terraform state addresses during the ZIP-to-image migration.
moved {
  from = aws_lambda_function.planner
  to   = aws_lambda_function.agent["planner"]
}

moved {
  from = aws_lambda_function.classifier
  to   = aws_lambda_function.agent["classifier"]
}

moved {
  from = aws_lambda_function.reporter
  to   = aws_lambda_function.agent["reporter"]
}

moved {
  from = aws_lambda_function.charter
  to   = aws_lambda_function.agent["charter"]
}

moved {
  from = aws_lambda_function.sell_side_agent
  to   = aws_lambda_function.agent["sell_side_agent"]
}

moved {
  from = aws_lambda_function.supervisor
  to   = aws_lambda_function.agent["supervisor_agent"]
}
