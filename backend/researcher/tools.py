"""
Tools for the sidechart Researcher agent
"""
import os
import ipaddress
from html import unescape
from typing import Dict, Any
from datetime import datetime, UTC
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup
from agents import function_tool
from tenacity import retry, stop_after_attempt, wait_exponential

# Configuration from environment
SIDECHART_API_ENDPOINT = os.getenv("SIDECHART_API_ENDPOINT")
SIDECHART_API_KEY = os.getenv("SIDECHART_API_KEY")
BROWSER_SEARCH_ENDPOINT = "https://www.bing.com/search"


def _parse_browser_search_results(
    response_text: str, max_results: int
) -> list[Dict[str, str]]:
    """Parse Bing's RSS search response into compact agent-friendly results."""
    root = ElementTree.fromstring(response_text)
    results = []
    for item in root.findall(".//item")[:max_results]:
        title = item.findtext("title", default="").strip()
        url = item.findtext("link", default="").strip()
        raw_snippet = item.findtext("description", default="")
        snippet = BeautifulSoup(unescape(raw_snippet), "html.parser").get_text(
            " ", strip=True
        )
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})
    return results


def _browser_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Execute a browser search independently of the agent SDK wrapper."""
    query = query.strip()
    if not query:
        return {"success": False, "error": "A non-empty search query is required."}

    result_limit = min(max(max_results, 1), 10)
    try:
        with httpx.Client(
            follow_redirects=True,
            headers={"User-Agent": "SideChart Researcher/1.0"},
            timeout=20.0,
        ) as client:
            response = client.get(
                BROWSER_SEARCH_ENDPOINT,
                params={"q": query, "format": "rss"},
            )
            response.raise_for_status()
        results = _parse_browser_search_results(response.text, result_limit)
        if not results:
            return {
                "success": False,
                "query": query,
                "error": "The search provider returned no results.",
            }
        return {"success": True, "query": query, "results": results}
    except (httpx.HTTPError, ElementTree.ParseError, ValueError) as exc:
        return {"success": False, "query": query, "error": str(exc)}


@function_tool
def browser_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search the public web for current sources and return titles, URLs, and snippets.

    Args:
        query: A focused web search query.
        max_results: Number of results to return, from 1 through 10.

    Returns:
        Search results suitable for subsequent browsing and source verification.
    """
    return _browser_search(query, max_results)


def _is_public_web_url(url: str) -> bool:
    """Reject non-web and directly addressed private-network URLs."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False
    if hostname == "localhost" or hostname.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
    )


def _find_text_matches(page_text: str, pattern: str) -> list[str]:
    """Return compact, de-duplicated excerpts around a case-insensitive pattern."""
    normalized_text = " ".join(page_text.split())
    folded_text = normalized_text.casefold()
    folded_pattern = pattern.casefold()
    matches = []
    search_from = 0
    while len(matches) < 10:
        index = folded_text.find(folded_pattern, search_from)
        if index < 0:
            break
        start = max(0, index - 180)
        end = min(len(normalized_text), index + len(pattern) + 180)
        excerpt = normalized_text[start:end]
        if excerpt not in matches:
            matches.append(excerpt)
        search_from = index + max(len(folded_pattern), 1)
    return matches


def _browser_find(url: str, pattern: str) -> Dict[str, Any]:
    """Fetch a public page and find text excerpts independently of Playwright state."""
    url = url.strip()
    pattern = pattern.strip()
    if not _is_public_web_url(url):
        return {"success": False, "error": "A public HTTP(S) URL is required."}
    if not pattern:
        return {"success": False, "url": url, "error": "A pattern is required."}

    try:
        with httpx.Client(
            follow_redirects=True,
            headers={"User-Agent": "SideChart Researcher/1.0"},
            timeout=20.0,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
        soup = BeautifulSoup(response.text[:2_000_000], "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        matches = _find_text_matches(soup.get_text(" ", strip=True), pattern)
        return {
            "success": True,
            "url": str(response.url),
            "title": soup.title.get_text(" ", strip=True) if soup.title else "",
            "pattern": pattern,
            "matches": matches,
            "match_count": len(matches),
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {"success": False, "url": url, "pattern": pattern, "error": str(exc)}


@function_tool
def browser_find(url: str, pattern: str) -> Dict[str, Any]:
    """Find text on a public web page and return matching excerpts.

    Args:
        url: The complete HTTP or HTTPS URL of the page to inspect.
        pattern: The word or phrase to find on the page.

    Returns:
        Page metadata and up to ten matching text excerpts.
    """
    return _browser_find(url, pattern)

def _ingest(document: Dict[str, Any]) -> Dict[str, Any]:
    """Internal function to make the actual API call."""
    with httpx.Client() as client:
        response = client.post(
            SIDECHART_API_ENDPOINT,
            json=document,
            headers={"x-api-key": SIDECHART_API_KEY},
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
    Ingest a financial document into the SIDECHART knowledge base.
    
    Args:
        topic: The topic or subject of the analysis (e.g., "AAPL Stock Analysis", "Trading strategy for a specific time horizon")
        analysis: Detailed analysis or advice with specific data and insights
    
    Returns:
        Dictionary with success status and document ID
    """
    if not SIDECHART_API_ENDPOINT or not SIDECHART_API_KEY:
        return {
            "success": False,
            "error": "SIDECHART API not configured. Running in local mode."
        }
    
    document = {
        "text": analysis,
        "metadata": {
            "topic": topic,
            "timestamp": datetime.now(UTC).isoformat()
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
