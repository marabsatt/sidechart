"use client";

import { FormEvent, useMemo, useState } from "react";

type ApiState = "idle" | "loading" | "ready" | "error";

type MarketRow = {
  ticker: string;
  date: string;
  close: number | null;
  volume: number | null;
  [key: string]: string | number | null | undefined;
};

type WeightRow = {
  ticker: string;
  weights: number;
};

type PipelineResult = {
  status?: string;
  error?: string;
  bullish_tickers?: string[];
  bearish_tickers?: string[];
  top_performers?: string[];
  market_data?: MarketRow[];
  signals_data?: MarketRow[];
  weights?: WeightRow[];
};

type SignalsResult = {
  bullish_tickers: string[];
  bearish_tickers: string[];
  signals_data: MarketRow[];
};

type ExecutionPreview = {
  dry_run: boolean;
  target_weights: WeightRow[];
  message?: string;
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000";

const DEFAULT_TICKERS = "AAPL, MSFT, NVDA, AMZN, GOOGL, META, JPM, XOM";

function parseTickers(value: string) {
  return Array.from(
    new Set(
      value
        .split(/[,\s]+/)
        .map((ticker) => ticker.trim().toUpperCase())
        .filter(Boolean),
    ),
  );
}

function formatPercent(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "0.0%";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function formatDateTime() {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date());
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
  } catch (error) {
    const reason = error instanceof Error ? error.message : "network request failed";
    throw new Error(
      `Unable to reach SideChart API at ${API_BASE}. Confirm the backend is running and that CORS_ORIGINS includes this frontend origin. Details: ${reason}`,
    );
  }

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : `Request failed with status ${response.status}`;
    throw new Error(detail);
  }
  return payload as T;
}

export default function Home() {
  const [tickersInput, setTickersInput] = useState(DEFAULT_TICKERS);
  const [lookbackDays, setLookbackDays] = useState(90);
  const [numSignals, setNumSignals] = useState(8);
  const [researchNote, setResearchNote] = useState(
    "No completed sell-side research note supplied yet.",
  );

  const [backendState, setBackendState] = useState<ApiState>("idle");
  const [workflowState, setWorkflowState] = useState<ApiState>("idle");
  const [message, setMessage] = useState("Ready to connect to SideChart API.");

  const [marketData, setMarketData] = useState<MarketRow[]>([]);
  const [signals, setSignals] = useState<SignalsResult | null>(null);
  const [pipeline, setPipeline] = useState<PipelineResult | null>(null);
  const [supervisorContext, setSupervisorContext] = useState("");
  const [executionPreview, setExecutionPreview] =
    useState<ExecutionPreview | null>(null);

  const tickers = useMemo(() => parseTickers(tickersInput), [tickersInput]);
  const weights = pipeline?.weights ?? [];
  const bullish = pipeline?.bullish_tickers ?? signals?.bullish_tickers ?? [];
  const bearish = pipeline?.bearish_tickers ?? signals?.bearish_tickers ?? [];
  const latestSignals = (pipeline?.signals_data ?? signals?.signals_data ?? [])
    .slice(-10)
    .reverse();

  const allocationTotal = weights.reduce(
    (total, row) => total + Number(row.weights ?? 0),
    0,
  );

  async function checkHealth() {
    setBackendState("loading");
    setMessage("Checking backend health...");
    try {
      const health = await apiRequest<{ status: string; timestamp: string }>(
        "/health",
      );
      setBackendState("ready");
      setMessage(`Backend ${health.status}. Last checked ${formatDateTime()}.`);
    } catch (error) {
      setBackendState("error");
      setMessage(error instanceof Error ? error.message : "Backend unavailable.");
    }
  }

  async function loadMarketData() {
    setWorkflowState("loading");
    setMessage("Requesting market data...");
    try {
      const response = await apiRequest<{
        data: MarketRow[];
        failed_tickers: [string, string][];
      }>("/market-data", {
        method: "POST",
        body: JSON.stringify({
          tickers,
          period: "1y",
          interval: "1d",
        }),
      });
      setMarketData(response.data);
      setMessage(
        `Loaded ${response.data.length.toLocaleString()} market rows for ${tickers.length} tickers.`,
      );
      setWorkflowState("ready");
    } catch (error) {
      setWorkflowState("error");
      setMessage(error instanceof Error ? error.message : "Market data failed.");
    }
  }

  async function generateSignals() {
    setWorkflowState("loading");
    try {
      let rows = marketData;
      if (rows.length === 0) {
        setMessage("Requesting market data before signal generation...");
        const response = await apiRequest<{ data: MarketRow[] }>("/market-data", {
          method: "POST",
          body: JSON.stringify({
            tickers,
            period: "1y",
            interval: "1d",
          }),
        });
        rows = response.data;
        setMarketData(rows);
      }

      if (rows.length === 0) {
        setWorkflowState("error");
        setMessage("No market rows available for signal generation.");
        return;
      }

      setWorkflowState("loading");
      setMessage("Generating technical signals...");
      const signalResponse = await apiRequest<SignalsResult>("/signals/generate", {
        method: "POST",
        body: JSON.stringify({ market_data: rows }),
      });
      setSignals(signalResponse);
      setMessage(
        `Signals complete: ${signalResponse.bullish_tickers.length} bullish, ${signalResponse.bearish_tickers.length} bearish.`,
      );
      setWorkflowState("ready");
    } catch (error) {
      setWorkflowState("error");
      setMessage(
        error instanceof Error ? error.message : "Signal generation failed.",
      );
    }
  }

  async function runPipeline(event?: FormEvent) {
    event?.preventDefault();
    setWorkflowState("loading");
    setMessage("Running analysis pipeline...");
    try {
      const response = await apiRequest<PipelineResult>("/pipeline/dev/analyze", {
        method: "POST",
        body: JSON.stringify({
          tickers,
          lookback_days: lookbackDays,
          num_signals: numSignals,
        }),
      });
      setPipeline(response);
      if (response.market_data) {
        setMarketData(response.market_data);
      }
      if (response.signals_data) {
        setSignals({
          bullish_tickers: response.bullish_tickers ?? [],
          bearish_tickers: response.bearish_tickers ?? [],
          signals_data: response.signals_data,
        });
      }
      setMessage(
        response.status === "success"
          ? `Pipeline complete with ${response.weights?.length ?? 0} target positions.`
          : response.error ?? `Pipeline returned ${response.status ?? "partial"} status.`,
      );
      setWorkflowState(response.status === "failed" ? "error" : "ready");
    } catch (error) {
      setWorkflowState("error");
      setMessage(error instanceof Error ? error.message : "Pipeline failed.");
    }
  }

  async function buildSupervisorContext() {
    setWorkflowState("loading");
    setMessage("Building supervisor context...");
    try {
      const response = await apiRequest<{ context: string }>(
        "/agents/supervisor/context",
        {
          method: "POST",
          body: JSON.stringify({
            tickers,
            sellside_research: researchNote,
            pipeline_results: pipeline ?? {
              status: "not_run",
              bullish_tickers: bullish,
              bearish_tickers: bearish,
              weights,
              market_data: marketData,
              signals_data: signals?.signals_data ?? [],
            },
            lookback_days: lookbackDays,
            num_signals: numSignals,
          }),
        },
      );
      setSupervisorContext(response.context);
      setMessage("Supervisor context generated.");
      setWorkflowState("ready");
    } catch (error) {
      setWorkflowState("error");
      setMessage(
        error instanceof Error ? error.message : "Supervisor context failed.",
      );
    }
  }

  async function previewExecution() {
    const divisor = Math.min(tickers.length, Math.max(1, numSignals));
    const targetWeights =
      weights.length > 0
        ? weights
        : tickers.slice(0, divisor).map((ticker) => ({
            ticker,
            weights: 1 / divisor,
          }));

    setWorkflowState("loading");
    setMessage("Preparing dry-run execution preview...");
    try {
      const response = await apiRequest<ExecutionPreview>("/execution/rebalance", {
        method: "POST",
        body: JSON.stringify({
          target_weights: targetWeights,
          dry_run: true,
        }),
      });
      setExecutionPreview(response);
      setMessage("Dry-run rebalance preview is ready.");
      setWorkflowState("ready");
    } catch (error) {
      setWorkflowState("error");
      setMessage(
        error instanceof Error ? error.message : "Execution preview failed.",
      );
    }
  }

  return (
    <main className="min-h-screen bg-[var(--app-bg)] text-[var(--ink)]">
      <header className="topbar">
        <div>
          <p className="eyebrow">SideChart Terminal</p>
          <h1>AI-assisted portfolio research and rebalance workflow</h1>
        </div>
        <div className="status-strip" aria-live="polite">
          <span className={`status-dot ${backendState}`} />
          <span>{message}</span>
        </div>
      </header>

      <section className="workspace">
        <aside className="control-rail">
          <form onSubmit={runPipeline} className="control-group">
            <div className="field">
              <label htmlFor="tickers">Universe</label>
              <textarea
                id="tickers"
                value={tickersInput}
                onChange={(event) => setTickersInput(event.target.value)}
                rows={4}
              />
            </div>

            <div className="field-grid">
              <div className="field">
                <label htmlFor="lookback">Lookback</label>
                <input
                  id="lookback"
                  type="number"
                  min={15}
                  value={lookbackDays}
                  onChange={(event) => setLookbackDays(Number(event.target.value))}
                />
              </div>
              <div className="field">
                <label htmlFor="signals">Positions</label>
                <input
                  id="signals"
                  type="number"
                  min={1}
                  value={numSignals}
                  onChange={(event) => setNumSignals(Number(event.target.value))}
                />
              </div>
            </div>

            <div className="button-stack">
              <button type="button" onClick={checkHealth}>
                Check API
              </button>
              <button type="button" onClick={loadMarketData}>
                Load market data
              </button>
              <button type="button" onClick={generateSignals}>
                Generate signals
              </button>
              <button type="submit" className="primary">
                Run analysis
              </button>
            </div>
          </form>

          <div className="control-group">
            <div className="field">
              <label htmlFor="research">Research context</label>
              <textarea
                id="research"
                value={researchNote}
                onChange={(event) => setResearchNote(event.target.value)}
                rows={6}
              />
            </div>
            <div className="button-stack">
              <button type="button" onClick={buildSupervisorContext}>
                Build supervisor context
              </button>
              <button type="button" onClick={previewExecution} className="primary">
                Preview rebalance
              </button>
            </div>
          </div>
        </aside>

        <section className="dashboard">
          <div className="metric-row">
            <div className="metric">
              <span>Universe</span>
              <strong>{tickers.length}</strong>
            </div>
            <div className="metric">
              <span>Bullish</span>
              <strong>{bullish.length}</strong>
            </div>
            <div className="metric">
              <span>Bearish</span>
              <strong>{bearish.length}</strong>
            </div>
            <div className="metric">
              <span>Allocated</span>
              <strong>{formatPercent(allocationTotal)}</strong>
            </div>
          </div>

          <div className="content-grid">
            <section className="panel allocation-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Target Allocation</p>
                  <h2>Draft portfolio weights</h2>
                </div>
                <span className={`pill ${workflowState}`}>{workflowState}</span>
              </div>

              {weights.length > 0 ? (
                <div className="allocation-list">
                  {weights.map((row) => (
                    <div className="allocation-row" key={row.ticker}>
                      <div>
                        <strong>{row.ticker}</strong>
                        <span>{formatPercent(row.weights)}</span>
                      </div>
                      <div className="bar-track">
                        <span
                          className="bar-fill"
                          style={{ width: `${Math.min(row.weights * 100, 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="empty-state">
                  Run analysis to populate optimized target weights.
                </p>
              )}
            </section>

            <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Signal Book</p>
                  <h2>Momentum classification</h2>
                </div>
              </div>
              <div className="signal-columns">
                <div>
                  <span className="column-label positive">Bullish</span>
                  <div className="ticker-list">
                    {(bullish.length ? bullish : ["--"]).map((ticker) => (
                      <span key={ticker}>{ticker}</span>
                    ))}
                  </div>
                </div>
                <div>
                  <span className="column-label negative">Bearish</span>
                  <div className="ticker-list">
                    {(bearish.length ? bearish.slice(0, 12) : ["--"]).map(
                      (ticker) => (
                        <span key={ticker}>{ticker}</span>
                      ),
                    )}
                  </div>
                </div>
              </div>
            </section>
          </div>

          <section className="panel table-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Latest Indicators</p>
                <h2>Signal data snapshot</h2>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Date</th>
                    <th>Close</th>
                    <th>Fast RSI</th>
                    <th>MACD Hist</th>
                    <th>Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {latestSignals.length > 0 ? (
                    latestSignals.map((row, index) => (
                      <tr key={`${row.ticker}-${row.date}-${index}`}>
                        <td>{row.ticker}</td>
                        <td>{row.date ? String(row.date).slice(0, 10) : "--"}</td>
                        <td>{Number(row.close ?? 0).toFixed(2)}</td>
                        <td>{Number(row._FAST_RSI ?? 0).toFixed(1)}</td>
                        <td>{Number(row._MACD_Hist ?? 0).toFixed(3)}</td>
                        <td>{Number(row.volume ?? 0).toLocaleString()}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={6}>No signal rows available.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <div className="content-grid lower-grid">
            <section className="panel text-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Supervisor</p>
                  <h2>Review context</h2>
                </div>
              </div>
              <pre>{supervisorContext || "Supervisor context will appear here."}</pre>
            </section>

            <section className="panel text-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Execution</p>
                  <h2>Dry-run preview</h2>
                </div>
              </div>
              {executionPreview ? (
                <div className="execution-list">
                  <p>{executionPreview.message}</p>
                  {executionPreview.target_weights.map((row) => (
                    <div className="execution-row" key={row.ticker}>
                      <span>{row.ticker}</span>
                      <strong>{formatPercent(row.weights)}</strong>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="empty-state">
                  Preview rebalance to validate the payload before paper execution.
                </p>
              )}
            </section>
          </div>
        </section>
      </section>
    </main>
  );
}
