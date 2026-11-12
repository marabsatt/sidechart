# SideChart IBKR Connector

This service runs on the same computer as IB Gateway. It only makes outbound
AWS requests and connects to Gateway over localhost; do not expose an IBKR API
port to the internet.

## First paper-mode run

1. Deploy `terraform/agents` and apply database migration
   `003_ibkr_connector.sql` with `backend/database/run_migrations.py`.
2. Configure IB Gateway for paper trading, enable socket clients, use port
   `4002`, and allow `127.0.0.1`.
3. Copy `.env.example` values into the repository `.env`, using the queue URLs
   from `terraform output -json ibkr_connector`.
4. Authenticate with AWS SSO for development, or configure IAM Roles Anywhere
   as a `credential_process` for an always-on installation.
5. Sync the existing project environment and run from the repository root:

   ```bash
   uv sync
   uv run python -m backend.ibkr_connector.main
   ```

The connector refuses live mode unless `IBKR_ALLOW_LIVE_TRADING=true`. Creating
the file at `IBKR_KILL_SWITCH_PATH` immediately blocks all new commands.

## Command contract

Commands must be written by the AWS approval/order API, not directly by the
browser. Every command contains stable UUIDs, an expiry, and the intended
account mode. The SQLite journal records `SUBMITTING` before calling IBKR. If a
restart makes submission ambiguous and the order cannot be found by `orderRef`,
the connector emits `MANUAL_RECONCILIATION_REQUIRED` instead of resubmitting.
