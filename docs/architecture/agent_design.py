"""Generate the SideChart AWS agent architecture diagram."""

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Aurora
from diagrams.aws.integration import SQS
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock, Sagemaker
from diagrams.aws.network import APIGateway
from diagrams.aws.storage import S3
from diagrams.aws.general import Client, TraditionalServer, User


OUTPUT = Path(__file__).resolve().with_name("agent_architecture")
GRAPH = {
    "splines": "ortho", "nodesep": "0.55", "ranksep": "0.85",
    "pad": "0.35", "compound": "true", "newrank": "true",
    "fontsize": "18", "bgcolor": "white",
}
NODE = {"fontsize": "10"}
EDGE = {"fontsize": "8", "arrowsize": "0.65"}


with Diagram(
    "SideChart - AWS Agent Architecture",
    filename=str(OUTPUT), show=False, direction="TB", outformat=["png", "svg"],
    graph_attr=GRAPH, node_attr=NODE, edge_attr=EDGE,
):
    human = User("Human supervisor")
    web_app = Client("SideChart web app")

    with Cluster("Agent Entry Points"):
        researcher_url = APIGateway("Researcher Function URL\nlong-running routes")
        frontend_api = APIGateway("Frontend HTTP API")
        analysis_jobs = SQS("Analysis jobs queue")
    web_app >> researcher_url
    web_app >> frontend_api

    with Cluster("Interactive Research and HITL Agents"):
        researcher = Lambda("Researcher service\nSell-side research + tools")
        sell_side = Lambda("Sell-side agent Lambda\nstandalone invocation")
        supervisor = Lambda("Supervisor agent Lambda\ndraft rebalance only")
        researcher_url >> researcher
        frontend_api >> Edge(label="POST /agents/supervisor/run") >> supervisor
        researcher >> Edge(label="research returned via web app") >> web_app
        web_app >> Edge(label="research + pipeline context") >> supervisor

    with Cluster("Asynchronous Agent Orchestration"):
        planner = Lambda("Planner agent\norchestrator")
        classifier = Lambda("Classifier agent")
        reporter = Lambda("Reporter agent")
        charter = Lambda("Charter agent")
        analysis_jobs >> planner
        planner >> Edge(label="invoke") >> classifier
        planner >> Edge(label="invoke") >> reporter
        planner >> Edge(label="invoke") >> charter

    with Cluster("Model and Tool Plane"):
        bedrock = Bedrock("Amazon Bedrock\nLiteLLM / Agents SDK")
        web_sources = TraditionalServer("Web sources\nPlaywright MCP")
        market_data = TraditionalServer("Market data\nyfinance")
        embeddings = Sagemaker("SageMaker embeddings")
        vectors = S3("S3 Vectors\nretrieval")

    researcher >> bedrock
    researcher >> web_sources
    researcher >> market_data
    sell_side >> bedrock
    supervisor >> bedrock
    planner >> bedrock
    classifier >> bedrock
    reporter >> bedrock
    charter >> bedrock
    reporter >> Edge(style="dashed", label="context") >> vectors
    reporter >> Edge(style="dashed", label="embeddings") >> embeddings

    with Cluster("HITL State and Execution Handoff"):
        database = Aurora("Aurora PostgreSQL\nresearch_signals\nsupervisor_reviews")
        order_api = Lambda("Approved-order API\nnon-agent safety boundary")
        command_queue = SQS("IBKR command FIFO")
        human >> Edge(label="approve / reject / modify") >> database
        database >> Edge(label="approved review") >> order_api
        order_api >> Edge(label="immutable order command") >> command_queue

    supervisor >> Edge(label="human-reviewable proposal") >> human

    with Cluster("Agent Operations"):
        logs = Cloudwatch("CloudWatch logs")
        tracing = TraditionalServer("Optional Langfuse tracing")

    researcher >> Edge(style="dashed") >> logs
    planner >> Edge(style="dashed") >> logs
    supervisor >> Edge(style="dashed") >> logs
    sell_side >> Edge(style="dashed") >> tracing
    supervisor >> Edge(style="dashed") >> tracing
