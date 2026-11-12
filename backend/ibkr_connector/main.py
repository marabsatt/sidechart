#!/usr/bin/env python3
"""Run the SideChart IBKR connector."""

import logging

from dotenv import load_dotenv

from .config import ConnectorConfig
from .service import ConnectorService


def main() -> None:
    load_dotenv(override=False)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ConnectorService(ConnectorConfig.from_env()).run()


if __name__ == "__main__":
    main()
