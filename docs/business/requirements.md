# SideChart Requirements

## 1. Purpose

SideChart is the next phase of the portfolio analysis project demonstrated in
[slithery-trades](https://github.com/marabsatt/slithery-trades). The earlier
project combined market data collection, portfolio optimization, Riskfolio-Lib,
and Interactive Brokers connectivity in a notebook workflow. SideChart will
turn that workflow into a service with agent-assisted analysis, explicit risk
controls, an API, and a basic user interface.

## 2. Product Scope

### In scope

- Market data ingestion and normalization
- Portfolio and watchlist management
- Specialized analysis agents
- Agent orchestration
- Explainable trade recommendations
- Pre-trade risk validation
- Paper-trading simulation and paper-broker integration
- Programmatic API access
- A basic web UI
- Structured logging and operational observability

### Out of scope for this phase

- Live order execution with real funds
- Automatic transfer of money or account credentials
- Fully autonomous trading without user review
- Guaranteed returns, investment advice, or prediction of market outcomes
- Mobile-native applications

## 3. Users

### Primary user

An individual investor or developer who wants to analyze a portfolio and
evaluate trade ideas using reproducible data, quantitative analysis, and a
paper-trading workflow.

### Secondary user

A developer or operator who needs to access analysis results through an API,
inspect agent decisions, and diagnose data or orchestration failures.

## 4. Functional Requirements

### FR-1: Market data ingestion

1. The system shall ingest historical OHLCV data for supported securities.
2. The system shall support a configurable market-data provider, initially
	supporting the data sources used by the predecessor project, including
	yfinance where appropriate.
3. The system shall normalize symbols, timestamps, currencies, and price data
	into a consistent internal schema.
4. The system shall validate data for missing values, duplicate records,
	invalid prices, stale timestamps, and provider errors.
5. The system shall retain source, retrieval time, interval, and data-quality
	status as metadata for each dataset.
6. The system shall cache or persist ingested data sufficiently to support
	repeatable analysis without unnecessarily re-fetching unchanged data.
7. The system shall clearly identify unavailable, delayed, or estimated data.

### FR-2: Portfolio and watchlist input

1. Users shall be able to create, view, update, and delete a portfolio.
2. A portfolio shall support symbols, quantities, average cost, cash balance,
	and optional account or tax-lot metadata.
3. Users shall be able to create and manage one or more watchlists.
4. Users shall be able to add and remove symbols from a watchlist.
5. The system shall validate symbols and reject malformed quantities or prices.
6. Users shall be able to import portfolio or watchlist data from a documented
	JSON or CSV format.
7. The system shall preserve the timestamp and origin of portfolio changes.

### FR-3: Analysis agents

The system shall provide specialized agents with narrow, inspectable
responsibilities:

1. A market data or technical analysis agent shall calculate supported
	indicators and summarize relevant price and volume behavior.
2. A portfolio analysis agent shall evaluate allocation, concentration,
	diversification, performance, and rebalancing needs.
3. A quantitative optimization agent shall support portfolio methods from the
	predecessor project, including mean-variance optimization, risk parity,
	and Sharpe-ratio-oriented analysis where sufficient data is available.
4. A fundamental or research agent may summarize configured research inputs,
	but shall distinguish sourced facts from model-generated interpretation.
5. Each agent shall return structured findings, inputs used, assumptions,
	confidence or data-quality indicators, and an explanation suitable for
	review by a user or another agent.
6. Agents shall fail explicitly when required data is missing or stale rather
	than inventing values.

### FR-4: Agent orchestration

1. The system shall coordinate analysis agents through a defined workflow.
2. The orchestrator shall pass a versioned analysis request and shared context
	to each participating agent.
3. The orchestrator shall support sequential execution and parallel execution
	where agent dependencies permit it.
4. The orchestrator shall enforce timeouts, retries, and bounded work for each
	agent.
5. The orchestrator shall record agent status, inputs, outputs, errors, and
	execution duration for every run.
6. A failed optional agent shall be represented as an incomplete result; it
	shall not be silently treated as a successful analysis.
7. The orchestrator shall support a correlation ID so all work for one
	analysis request can be traced end to end.

### FR-5: Trade recommendation generation

1. The system shall generate recommendations only from available portfolio,
	market, analysis, and risk results.
2. A recommendation shall include symbol, action, quantity or target weight,
	reference price or price range, rationale, expected holding context, and
	material assumptions.
3. Supported actions shall include at least `buy`, `sell`, `hold`, and
	`rebalance`.
4. Every recommendation shall include supporting agent findings and a
	human-readable explanation.
5. The system shall assign a recommendation status such as `draft`,
	`risk-approved`, `risk-rejected`, `paper-submitted`, or `expired`.
6. Recommendations shall expire after a configurable period or when their
	underlying market data is no longer valid.
7. The system shall never present a recommendation as a guarantee or as
	personalized financial advice.

### FR-6: Risk validation

1. Every recommendation shall pass risk validation before it can be submitted
	to the paper-trading system.
2. Risk checks shall include available cash, position size, concentration,
	portfolio exposure, and configurable maximum loss or volatility limits.
3. The system shall support configurable user risk limits and shall apply
	conservative defaults when limits are not configured.
4. The validator shall reject recommendations with missing prices, invalid
	quantities, stale data, insufficient cash, or violated limits.
5. A validation result shall include pass or fail status, each rule evaluated,
	the values used, and a clear rejection reason where applicable.
6. Risk validation shall be deterministic for the same inputs and rule version.
7. Risk validation shall be advisory and educational; users remain responsible
	for reviewing any paper-trading action.

### FR-7: Paper-trading only

1. The system shall operate exclusively in paper-trading mode for this phase.
2. The system shall reject live account identifiers, live order endpoints, and
	any execution request that is not explicitly supported by the paper-trading
	adapter.
3. The system shall support paper order creation, cancellation where
	supported, simulated fills, order status, positions, cash, and performance.
4. The system shall distinguish simulated results from market data and label
	all UI and API responses as paper-trading results.
5. The system shall maintain an immutable audit record for each paper order and
	simulated fill.
6. Enabling live trading shall require a future product decision and a separate
	security and risk review; it shall not be exposed as a hidden configuration
	switch.

### FR-8: API access

1. The system shall expose a versioned HTTP API for portfolios, watchlists,
	market data, analysis runs, recommendations, risk results, and paper orders.
2. The API shall return documented request and response schemas, validation
	errors, and stable resource identifiers.
3. Long-running analysis shall be asynchronous, with endpoints to start a run,
	retrieve status, and retrieve results.
4. The API shall support authentication for non-local use and shall not expose
	provider credentials or secrets in responses.
5. The API shall enforce authorization boundaries between users and their
	portfolios, watchlists, analyses, and orders.
6. The API shall provide health and readiness endpoints that do not disclose
	sensitive configuration.
7. The API shall document rate limits, pagination, timestamps, error formats,
	and paper-trading restrictions.

### FR-9: Basic UI

1. The UI shall provide a dashboard showing portfolio value, cash, allocation,
	watchlists, recent analysis runs, and paper-trading status.
2. Users shall be able to enter or import a portfolio and manage watchlists.
3. Users shall be able to start an analysis run and view its progress and
	completion status.
4. Users shall be able to inspect recommendations, supporting analysis,
	assumptions, risk checks, and rejection reasons.
5. Users shall be able to review paper orders, simulated fills, positions, and
	performance history.
6. The UI shall make paper-trading-only status visible wherever an order or
	recommendation is displayed.
7. The UI shall present unavailable data, partial agent results, and system
	errors clearly without implying successful analysis.

### FR-10: Logging and observability

1. The system shall emit structured logs for API requests, data-provider calls,
	analysis runs, agent execution, risk checks, and paper orders.
2. Logs shall include timestamp, severity, service or component, correlation
	ID, operation, duration, and outcome where applicable.
3. Logs shall exclude secrets, API keys, account credentials, and unnecessary
	personally identifiable information.
4. The system shall expose metrics for request volume and latency, provider
	failures, data freshness, agent failures, orchestration duration, risk
	rejection counts, and paper-order outcomes.
5. The system shall provide enough tracing or correlation data to follow one
	analysis from API request through recommendation and paper order.
6. The system shall record audit events separately from diagnostic logs for
	portfolio changes, recommendations, risk decisions, and paper orders.
7. Operators shall be able to identify degraded providers, failed workflows,
	and stale data through documented health signals.

## 5. Non-Functional Requirements

### NFR-1: Security

- Secrets shall be supplied through environment configuration or a secret
  manager and shall never be committed to source control.
- Inputs from users and external providers shall be validated at system
  boundaries.
- API access shall use authenticated and authorized requests outside local
  development.
- The system shall default to least-privilege access for external services.

### NFR-2: Reliability and recoverability

- External provider failures shall produce actionable errors and shall not
  corrupt portfolio or paper-order state.
- Retried operations shall be bounded and idempotent where they can create
  durable records.
- The system shall preserve enough state to inspect completed and failed
  analysis runs after a process restart.

### NFR-3: Reproducibility

- Analysis results shall record data timestamps, provider, agent versions, rule
  versions, configuration, and assumptions.
- A completed analysis shall be reproducible as far as the underlying provider
  data permits.

### NFR-4: Usability and accessibility

- Core portfolio, analysis, recommendation, and paper-order workflows shall be
  usable from a desktop browser.
- The UI shall provide clear loading, empty, partial, success, and error states.
- Important status and validation information shall not rely on color alone.

## 6. MVP Acceptance Criteria

The MVP is complete when a user can:

1. Add or import a portfolio and watchlist.
2. Ingest historical market data with visible freshness and data-quality status.
3. Run an orchestrated analysis involving at least two specialized agents.
4. View a structured, explainable recommendation.
5. See the risk rules and values used to approve or reject it.
6. Submit only an approved recommendation to paper trading.
7. Review the paper order, simulated fill, resulting position, and performance.
8. Perform the same core workflow through the versioned API.
9. Inspect logs or trace data for the complete analysis request.

## 7. Product Constraints and Assumptions

- This is an educational and research system, not a financial advisory service.
- Market data availability, licensing, latency, and accuracy depend on the
  configured provider.
- The initial implementation may use Interactive Brokers paper trading where
  configured, while preserving an adapter boundary for other paper brokers.
- The initial UI may be intentionally basic, but the API and internal result
  schemas should be designed for future clients.
