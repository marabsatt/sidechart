"""Generate the current SideChart analysis, HITL, and execution data flow."""

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Aurora
from diagrams.aws.integration import SQS
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import CloudFront
from diagrams.aws.general import Client, TraditionalServer, User


OUTPUT = Path(__file__).resolve().with_name("data_flow")

with Diagram(
    "SideChart - Current Data Flow",
    filename=str(OUTPUT), show=False, direction="LR", outformat=["png", "svg"],
    graph_attr={
        "splines": "ortho", "nodesep": "0.55", "ranksep": "0.85",
        "pad": "0.35", "compound": "true", "newrank": "true",
        "fontsize": "18", "bgcolor": "white",
    },
    node_attr={"fontsize": "10"},
    edge_attr={"fontsize": "8", "arrowsize": "0.65"},
):
    operator = User("Portfolio operator")
    browser = Client("SideChart browser app")
    edge = CloudFront("CloudFront / API routing")
    operator >> browser >> edge

    with Cluster("Analysis and Agent Reasoning"):
        researcher = Lambda("Researcher + market pipeline")
        bedrock = Bedrock("Amazon Bedrock")
        supervisor = Lambda("Supervisor agent")
        human_review = Client("Human review decision")
        researcher >> bedrock
        supervisor >> bedrock
        supervisor >> Edge(label="proposal") >> human_review

    edge >> researcher
    edge >> supervisor
    researcher >> Edge(label="research result") >> browser
    browser >> Edge(label="research + pipeline context") >> supervisor
    operator >> human_review

    with Cluster("Single Source of Truth"):
        database = Aurora("Aurora PostgreSQL\nsignals / reviews / orders / fills")

    human_review >> Edge(label="approve / reject / modify") >> database

    with Cluster("Approved Paper-Order Path"):
        order_api = Lambda("Approved-order API")
        commands = SQS("IBKR commands FIFO")
        connector = Client("Local connector\ndurable outbox")
        gateway = TraditionalServer("IB Gateway paper")
        broker = Client("Interactive Brokers")
        events = SQS("IBKR events FIFO")
        processor = Lambda("Event processor")
        order_api >> commands >> connector >> gateway >> broker
        connector >> events >> processor

    database >> Edge(label="approved review") >> order_api
    processor >> Edge(label="status / fills / positions") >> database
