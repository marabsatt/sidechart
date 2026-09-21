import os
from typing import Dict, Any
from datetime import datetime, timezone

try:
    import httpx
except ModuleNotFoundError:
    httpx = None

try:
    from agents import function_tool
except (ImportError, ModuleNotFoundError):
    def function_tool(func):
        return func

try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ModuleNotFoundError:
    def retry(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def stop_after_attempt(*args, **kwargs):
        return None

    def wait_exponential(*args, **kwargs):
        return None

# Configuration from environment
RESEARCHER_API_ENDPOINT = os.getenv("RESEARCHER_API_ENDPOINT")
RESEARCHER_API_KEY = os.getenv("RESEARCHER_API_KEY")


def _ingest(document: Dict[str, Any]) -> Dict[str, Any]:
    """Internal function to make the actual API call."""
    if httpx is None:
        raise RuntimeError("httpx is required to ingest research documents")

    with httpx.Client() as client:
        response = client.post(
            RESEARCHER_API_ENDPOINT,
            json=document,
            headers={"x-api-key": RESEARCHER_API_KEY},
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
def ingest_with_retries(document: Dict[str, Any]) -> Dict[str, Any]:
    """Ingest with retry logic for SageMaker cold starts."""
    return _ingest(document)


@function_tool
def ingest_financial_document(topic: str, analysis: str) -> Dict[str, Any]:
    """
    Ingest a financial document into the RESEARCHER knowledge base.
    
    Args:
        topic: The topic or subject of the analysis (e.g., "AAPL Stock Analysis", "Company's Filings")
        analysis: Detailed analysis or advice with specific data and insights
    
    Returns:
        Dictionary with success status and document ID
    """
    if not RESEARCHER_API_ENDPOINT or not RESEARCHER_API_KEY:
        return {
            "success": False,
            "error": "RESEARCHER API not configured. Running in local mode."
        }
    
    document = {
        "text": analysis,
        "metadata": {
            "topic": topic,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    }
    
    try:
        result = ingest_with_retries(document)
        return {
            "success": True,
            "document_id": result.get("document_id"),  # Changed from documentId
            "message": f"Successfully ingested analysis for {topic}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
