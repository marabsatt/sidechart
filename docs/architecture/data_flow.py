from diagrams import Cluster, Diagram, Edge
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import EventbridgeScheduler, SQS, StepFunctions
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import APIGateway
from diagrams.aws.storage import S3
from diagrams.aws.general import Client, TraditionalServer, User
from diagrams.programming.language import Python


graph_attr = {
	"splines": "ortho",
	"nodesep": "0.55",
	"ranksep": "0.85",
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
	"Slithery Trades - Data Flow",
	filename="data_flow",
	show=False,
	direction="TB",
	outformat="png",
	graph_attr=graph_attr,
	node_attr=node_attr,
	edge_attr=edge_attr,
):
	user = User("Portfolio Operator")
	client = Client("Web UI / API Client")
	api_gateway = APIGateway("API Gateway")
	scheduler = EventbridgeScheduler("Scheduled Analysis")
	workflow = StepFunctions("Analysis Workflow")

	user >> client >> api_gateway
	api_gateway >> Edge(label="analysis request") >> workflow
	scheduler >> Edge(label="scheduled run") >> workflow

	with Cluster("Input and Market Data"):
		portfolio_input = Python("Portfolio / Watchlist Input")
		market_data_provider = TraditionalServer("Market Data Provider")
		ingestion = Python("Market Data Ingestion")
		normalized_data = Python("Validated / Normalized Data")

		portfolio_input >> workflow
		market_data_provider >> ingestion >> normalized_data

	with Cluster("Agentic Intelligence Plane"):
		research_agent = Bedrock("Market Research Agent")
		portfolio_agent = Bedrock("Portfolio Analysis Agent")
		quantitative_agent = Bedrock("Quantitative Analysis Agent")
		synthesis_agent = Bedrock("Recommendation Synthesis Agent")

		research_agent >> synthesis_agent
		portfolio_agent >> synthesis_agent
		quantitative_agent >> synthesis_agent

	with Cluster("Decision and Risk Controls"):
		recommendation = Python("Trade Recommendation")
		risk_validator = Python("Risk Validation")
		paper_order = SQS("Paper Order Queue")

		recommendation >> risk_validator
		risk_validator >> Edge(label="approved") >> paper_order

	with Cluster("Paper Trading"):
		paper_broker = TraditionalServer("Paper Broker / IB Gateway")
		execution = Python("Paper Execution Service")
		reconciliation = Python("Fill Reconciliation")

		paper_order >> execution >> paper_broker
		paper_broker >> reconciliation

	with Cluster("Authoritative State"):
		object_store = S3("Raw Data / Audit Lake")
		operational_state = Dynamodb("Portfolio / Order State")

	with Cluster("Observability"):
		metrics = Python("Metrics / Dashboards API")
		audit_events = Python("Structured Logs / Traces")

	workflow >> Edge(label="fetch") >> ingestion
	normalized_data >> Edge(label="market context") >> research_agent
	normalized_data >> Edge(label="price history") >> quantitative_agent
	portfolio_input >> Edge(label="holdings") >> portfolio_agent
	workflow >> Edge(label="invoke agents") >> research_agent
	workflow >> Edge(label="invoke agents") >> portfolio_agent
	workflow >> Edge(label="invoke agents") >> quantitative_agent
	synthesis_agent >> Edge(label="proposed action") >> recommendation

	risk_validator >> Edge(
		label="rejected: return reason",
		style="dashed",
	) >> client
	reconciliation >> Edge(label="fills / positions") >> client
	metrics >> Edge(label="metrics / dashboards") >> client

	ingestion >> Edge(style="dashed", label="raw / normalized") >> object_store
	portfolio_input >> Edge(style="dashed", label="portfolio snapshot") >> operational_state
	risk_validator >> Edge(style="dashed", label="risk decision") >> operational_state
	reconciliation >> Edge(style="dashed", label="orders / fills") >> operational_state

	workflow >> Edge(style="dashed", label="run status") >> audit_events
	audit_events >> metrics
	risk_validator >> Edge(style="dashed", label="validation metrics") >> metrics
	reconciliation >> Edge(style="dashed", label="execution metrics") >> metrics
