from diagrams import Cluster, Diagram, Edge
from diagrams.aws.network import APIGateway
from diagrams.aws.integration import SQS, StepFunctions, EventbridgeScheduler
from diagrams.aws.storage import S3
from diagrams.aws.database import Dynamodb
from diagrams.aws.ml import Bedrock
from diagrams.aws.general import Client, TraditionalServer, User
from diagrams.programming.language import Python


graph_attr = {
    "splines": "ortho",
    "nodesep": "0.65",
    "ranksep": "0.95",
    "pad": "0.35",
    "compound": "true",
    "newrank": "true",
    "fontsize": "16",
}

node_attr = {
    "fontsize": "11",
}

edge_attr = {
    "fontsize": "9",
    "arrowsize": "0.7",
}


with Diagram(
    "Slithery Trades - Agentic Trading Platform",
    filename="system_architecture",
    show=False,
    direction="TB",
    outformat="png",
    graph_attr=graph_attr,
    node_attr=node_attr,
    edge_attr=edge_attr,
):
    
    # Entry points
    
    operator = User("User / Portfolio Operator")
    api_gateway = APIGateway("API Gateway")
    scheduler = EventbridgeScheduler("EventBridge Scheduler")
    step_functions = StepFunctions("Step Functions")

    operator >> api_gateway
    api_gateway >> step_functions
    scheduler >> step_functions

    
    # Deterministic Trading Plane
    
    with Cluster("Deterministic Trading Plane"):
        market_data = Python("Market Data Service")
        signal_engine = Python("Signal Engine")
        portfolio_optimizer = Python("Portfolio Optimizer")
        risk_manager = Python("Risk Manager")

        live_approval = Python("Live-Trade Approval Gate")

        order_queue = SQS("SQS FIFO Order Queue")
        execution_service = Python("Execution Service")
        reconciliation_service = Python("Reconciliation Service")

        market_data >> signal_engine

        portfolio_optimizer >> risk_manager

        risk_manager >> Edge(label="paper") >> order_queue

        risk_manager >> Edge(label="live") >> live_approval
        live_approval >> order_queue

        order_queue >> execution_service

    
    # Agentic Intelligence Plane
    
    with Cluster("Agentic Intelligence Plane"):
        market_research_agent = Python("Market Research Agent")
        portfolio_supervisor_agent = Python(
            "Portfolio Supervisor Agent"
        )
        operations_agent = Python("Operations Agent")

        market_research_agent >> portfolio_supervisor_agent

    
    # Authoritative State
    
    with Cluster("Authoritative State"):
        s3 = S3("S3 Data / Audit Lake")
        db = Dynamodb("DynamoDB Operational State")

    
    # Broker Boundary
    
    with Cluster("Broker Boundary"):
        ib_gateway = TraditionalServer("IB Gateway / TWS")
        ibkr = Client("Interactive Brokers")

        ib_gateway >> ibkr

    
    # AI Platform
    
    with Cluster("AI Platform"):
        agent_core = Bedrock("Bedrock AgentCore")
        amazon_bedrock = Bedrock("Amazon Bedrock")

        agent_core >> amazon_bedrock

    
    # Primary workflow
    

    # Step Functions starts deterministic processing
    step_functions >> market_data

    # Step Functions also invokes the research workflow
    step_functions >> market_research_agent

    # Deterministic signals become an input to agent reasoning
    signal_engine >> portfolio_supervisor_agent

    # Agent synthesizes the portfolio view;
    # deterministic optimizer performs allocation calculation
    portfolio_supervisor_agent >> portfolio_optimizer

    # Approved order execution
    execution_service >> ib_gateway
    ibkr >> reconciliation_service

    # Reconciliation failures/events can be interpreted by Ops Agent
    reconciliation_service >> operations_agent

    
    # AI platform connections
    
    market_research_agent >> agent_core
    portfolio_supervisor_agent >> agent_core
    operations_agent >> agent_core

    
    # State / audit relationships
    # Dashed lines distinguish persistence from business flow.
    
    market_data >> Edge(
        style="dashed",
        label="raw / normalized",
    ) >> s3

    market_data >> Edge(
        style="dashed",
        label="metadata",
    ) >> db

    signal_engine >> Edge(
        style="dashed",
        label="signals",
    ) >> db

    portfolio_optimizer >> Edge(
        style="dashed",
        label="target portfolio",
    ) >> db

    risk_manager >> Edge(
        style="dashed",
        label="risk decision",
    ) >> db

    execution_service >> Edge(
        style="dashed",
        label="order state",
    ) >> db

    reconciliation_service >> Edge(
        style="dashed",
        label="fills / positions",
    ) >> db

    reconciliation_service >> Edge(
        style="dashed",
        label="audit",
    ) >> s3