# SideChart

SideChart is an AI-assisted portfolio research and rebalance workflow. The current build connects a FastAPI backend, reusable trading/research contracts, OpenAI-powered agent synthesis, and a Next.js dashboard.

The application is still under active development. Outputs are intended for research, review, and paper-trading workflows only. They are not personalized investment advice, execution recommendations, or a guarantee of returns.

## Current Development Snapshot

SideChart now supports an end-to-end local workflow:

1. Load market data for a user-defined ticker universe.
2. If the Universe field is empty, discover bullish tickers from broad market data and rank them by recent monthly return.
3. Generate technical bullish/bearish classifications from RSI, EMA, MACD, price action, and volume confirmation.
4. Run the dev analysis pipeline across the active universe.
5. Generate risk based draft target weights.
6. Display optimized weights in the frontend Target Allocation panel.
7. Trigger researcher and supervisor agents from the frontend.
8. Render agent outputs as polished markdown memos.
9. Preview dry-run rebalance payloads before any paper execution path.

## Architecture

```text
frontend/             Next.js dashboard for financial workflows
backend/server.py     FastAPI API layer and local orchestration entrypoint
src/contracts/        Shared trading contracts
src/contracts/dev/    Dev market data, portfolio, risk, holdings, and pipeline modules
src/agents/research/  Sell-side researcher agent prompts/tools
src/agents/supervisor Supervisor agent prompts/tools and rebalance synthesis context
scripts/run_local.py  Local runner for backend and frontend together
```

## Backend

The backend is implemented in `backend/server.py` and exposes the project through a FastAPI API. It loads environment variables from `.env`, configures local CORS for the frontend, imports the local `src` contracts, and normalizes pandas outputs into JSON safe API responses.

Current backend capabilities include:

- Health check and API discovery.
- Market data retrieval from the dev market data contract.
- S&P 500 and Nasdaq-100 ticker discovery helpers.
- RSI, EMA, MACD, and full signal-generation endpoints.
- Dev analysis pipeline execution.
- Rebalance proposal construction.
- Current holdings retrieval through the dev holdings contract.
- Buy/sell order dry run endpoints.
- Rebalance execution dry run endpoint.
- Researcher agent prompt and run endpoint.
- Supervisor context and run endpoint.
- Optional document ingestion hooks for researcher/supervisor knowledge stores.

Important local endpoints:

```text
GET  /health
POST /market-data
POST /signals/generate
POST /pipeline/dev/analyze
POST /execution/rebalance
POST /agents/research/run
POST /agents/supervisor/run
GET  /docs
```

## Contracts

The contracts layer contains the reusable financial workflow logic.

### Market Data

`src/contracts/dev/market_data.py` retrieves yfinance OHLCV data and normalizes it into:

```text
ticker, date, open, high, low, close, volume
```

When no tickers are supplied, the module attempts to discover a broader universe from S&P 500 and Nasdaq-100 constituents, with a static large-cap fallback list. The automatic universe size is controlled with:

```text
MARKET_DATA_MAX_TICKERS=120
```

### Signals

`src/contracts/signals.py` generates bullish and bearish classifications using:

- Fast and slow RSI
- MACD line, signal line, and histogram
- Fast and slow EMA trend
- Latest price action
- Volume confirmation

The signal generator now validates required columns, coerces numeric fields, handles insufficient history explicitly, and adds a `_Signal` marker to the latest row.

### Pipeline

`src/contracts/dev/pipeline.py` orchestrates the current dev analysis flow:

1. Pull market data.
2. Generate technical signals.
3. Rank bullish candidates by recent return.
4. Optimize target weights for the active universe.
5. Return market data, signals, candidates, top performers, and weights.

The risk optimizer now applies weights across the active Universe rather than only the smaller top-performer set, so the frontend allocation table reflects all tickers under review.

### Risk

`src/contracts/dev/risk.py` uses Riskfolio-Lib to produce draft target weights. It now:

- Deduplicates and normalizes input tickers.
- Returns equal weights for insufficient data or optimizer failures.
- Completes the final weight table back to every requested ticker.
- Normalizes weights to sum to 100%.

## Agents

SideChart currently has two agent workflows.

### Research Agent

The research agent produces a portfolio universe sell-side research note. It is prompted to cover every ticker in the active Universe and structure output as:

- Executive Summary
- Coverage Matrix
- Ticker-by-Ticker Notes
- Portfolio Implications
- Compliance Note

The frontend calls:

```text
POST /agents/research/run
```

### Supervisor Agent

The supervisor agent consumes the research output, pipeline results, target weights, signals, and performance context. It produces a rebalance memo with:

- RebalanceProposal
- Rationale
- Target weight and action tables
- Assumptions
- Risks
- Data quality and open items

The frontend calls:

```text
POST /agents/supervisor/run
```

## Frontend

The frontend is a Next.js dashboard in `frontend/`. It is designed as a restrained, professional interface for finance users.

Current UI capabilities:

- Universe input box.
- Lookback (In Days) and position count controls.
- Backend health check.
- Market data loading.
- Automatic bullish-universe discovery when Universe is empty.
- Signal generation.
- Full analysis pipeline execution.
- Target Allocation panel with draft portfolio weights.
- Bullish/bearish signal book.
- Latest indicator snapshot table.
- Research context input.
- Supervisor rationale brief preview.
- Research agent trigger and rendered markdown output.
- Supervisor agent trigger and rendered markdown output.
- Raw supervisor context view.
- Dry-run rebalance preview.

The agent output panels render common markdown structures including headings, lists, bold text, inline code, and markdown tables.

## Local Development

Prerequisites:

- Python with `uv`
- Node.js
- npm

Install frontend dependencies if needed:

```bash
cd frontend
npm install
```

Run the backend and frontend together:

```bash
python scripts/run_local.py
```

The local runner starts:

```text
Backend:  http://127.0.0.1:8000
Frontend: http://localhost:3000
API docs: http://127.0.0.1:8000/docs
```

You can skip prerequisite checks with:

```bash
python scripts/run_local.py --skip-checks
```

## Environment Variables

Common environment variables:

```text
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
MARKET_DATA_MAX_TICKERS=120
IB_HOST=127.0.0.1
IB_PORT=7497
IB_CLIENT_ID=17
RESEARCHER_API_ENDPOINT=...
RESEARCHER_API_KEY=...
SUPERVISOR_API_ENDPOINT=...
SUPERVISOR_API_KEY=...
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Only `OPENAI_API_KEY` is required for live agent generation. Market data and most local backend routes can run without the research/supervisor ingestion keys.

## Validation Commands

Useful checks during development:

```bash
python3 -m py_compile backend/server.py src/contracts/signals.py src/contracts/dev/market_data.py src/contracts/dev/pipeline.py src/contracts/dev/risk.py
```

```bash
cd frontend
npm run lint
npx tsc --noEmit --incremental false
```

## Current Limitations

- Market data depends on yfinance availability and upstream ticker sources.
- Agent outputs depend on OpenAI API configuration and should be reviewed by a human.
- IBKR execution paths are present, but the current frontend path emphasizes dry-run previews.
- Research/valuation data is limited to the supplied context unless additional external data tools are connected.
- This project is not yet production hardened for authentication, audit logging, execution approvals, or portfolio accounting.

## Near-Term Next Steps

- Add persisted run history for research, supervisor outputs, and rebalance proposals.
- Add richer current holdings integration in the frontend.
- Add explicit approval states before any paper/live execution.
- Expand data quality reporting for failed tickers and stale market rows.
- Add focused tests for market discovery, signal classification, optimizer fallbacks, and agent endpoint payloads.
- Consider richer markdown rendering if agent output grows beyond the current supported subset.
