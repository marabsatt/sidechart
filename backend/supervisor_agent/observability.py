"""Optional Langfuse observability for the supervisor Lambda."""

from contextlib import contextmanager
import logging
import os


logger = logging.getLogger(__name__)


@contextmanager
def observe():
    client = None
    if os.getenv("LANGFUSE_SECRET_KEY"):
        try:
            import logfire
            from langfuse import get_client

            logfire.configure(
                service_name="sidechart_supervisor_agent",
                send_to_logfire=False,
            )
            logfire.instrument_openai_agents()
            client = get_client()
        except Exception as exc:
            logger.warning("Supervisor observability setup failed: %s", exc)
    try:
        yield
    finally:
        if client:
            client.flush()
