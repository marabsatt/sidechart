"""Generate the deployed SideChart AWS system architecture diagram."""

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECR, Lambda
from diagrams.aws.database import Aurora
from diagrams.aws.integration import SQS
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock, Sagemaker
from diagrams.aws.network import APIGateway, CloudFront
from diagrams.aws.security import IAM, SecretsManager
from diagrams.aws.storage import S3
from diagrams.aws.general import Client, TraditionalServer, User
from diagrams.programming.language import Python


OUTPUT = Path(__file__).resolve().with_name("system_architecture")
GRAPH = {
    "splines": "ortho", "nodesep": "0.55", "ranksep": "0.85",
    "pad": "0.35", "compound": "true", "newrank": "true",
    "fontsize": "18", "bgcolor": "white",
}
NODE = {"fontsize": "10"}
EDGE = {"fontsize": "8", "arrowsize": "0.65"}


with Diagram(
    "SideChart - Deployed AWS System Architecture",
    filename=str(OUTPUT), show=False, direction="TB", outformat=["png", "svg"],
    graph_attr=GRAPH, node_attr=NODE, edge_attr=EDGE,
):
    operator = User("Portfolio Operator")

    with Cluster("Public Web Edge"):
        cloudfront = CloudFront("CloudFront\n/api routing")
        frontend = S3("Private S3\nNext.js export")
        http_api = APIGateway("HTTP API\nselected routes")
        cloudfront >> Edge(label="static UI") >> frontend
        cloudfront >> Edge(label="supervisor + orders") >> http_api

    operator >> Client("Browser") >> cloudfront

    with Cluster("AWS Lambda Application Layer"):
        researcher = Lambda("Researcher service\nFastAPI + Function URL")
        supervisor = Lambda("Supervisor agent")
        order_api = Lambda("Approved-order API")
        ingestion_api = APIGateway("Ingestion REST API\nAPI key")
        ingestion = Lambda("Document ingestion")
        http_api >> Edge(label="POST supervisor") >> supervisor
        http_api >> Edge(label="POST approved order") >> order_api
        ingestion_api >> ingestion

    cloudfront >> Edge(label="general /api/*") >> researcher

    with Cluster("Asynchronous Lambda Workflows"):
        analysis_queue = SQS("Analysis jobs + DLQ")
        planner = Lambda("Planner / orchestrator")
        specialists = Lambda("Classifier | Reporter | Charter")
        ibkr_commands = SQS("IBKR commands FIFO + DLQ")
        ibkr_events = SQS("IBKR events FIFO + DLQ")
        event_processor = Lambda("IBKR event processor")
        analysis_queue >> planner >> Edge(label="sync invoke") >> specialists
        ibkr_events >> event_processor

    order_api >> Edge(label="approved commands") >> ibkr_commands

    with Cluster("Authoritative Data and AI Services"):
        aurora = Aurora("Aurora PostgreSQL\nData API / HITL source of truth")
        secrets = SecretsManager("DB credentials")
        vectors = S3("S3 Vectors\nresearch index")
        embeddings = Sagemaker("Serverless embedding endpoint")
        bedrock = Bedrock("Amazon Bedrock")
        secrets >> Edge(style="dashed", label="credentials") >> aurora
        ingestion >> embeddings
        ingestion >> vectors

    order_api >> Edge(label="validate review + create order") >> aurora
    event_processor >> Edge(label="orders / fills / positions") >> aurora
    researcher >> Edge(label="research inference") >> bedrock
    supervisor >> Edge(label="supervisor inference") >> bedrock
    planner >> Edge(label="agent inference") >> bedrock
    specialists >> Edge(label="agent inference") >> bedrock
    specialists >> Edge(style="dashed", label="retrieval") >> vectors
    specialists >> Edge(style="dashed", label="embeddings") >> embeddings

    with Cluster("Local Broker Boundary (outside AWS)"):
        connector = Python("SideChart IBKR connector\nSQLite journal / outbound only")
        gateway = TraditionalServer("IB Gateway\n127.0.0.1:4002 paper")
        ibkr = Client("Interactive Brokers")
        connector >> gateway >> ibkr

    ibkr_commands >> Edge(label="HTTPS long poll") >> connector
    connector >> Edge(label="status / fills / positions") >> ibkr_events

    with Cluster("Deployment, Access, and Observability"):
        ecr = ECR("ECR container images")
        iam = IAM("Connector IAM role\ntrust/profile setup required")
        logs = Cloudwatch("CloudWatch Logs")

    ecr >> Edge(style="dashed", label="images") >> researcher
    ecr >> Edge(style="dashed", label="images") >> planner
    iam >> Edge(style="dashed", label="temporary credentials") >> connector
    researcher >> Edge(style="dashed") >> logs
    planner >> Edge(style="dashed") >> logs
    event_processor >> Edge(style="dashed") >> logs
