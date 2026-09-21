"use client";

import { FormEvent, type ReactNode, useMemo, useState } from "react";

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
  candidate_tickers?: string[];
  allocation_tickers?: string[];
  signal_fallback?: boolean;
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

type AgentRunResult = {
  output: string;
  context?: string;
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000";

const DEFAULT_TICKERS = "AAPL, MSFT, NVDA, AMZN, GOOGL, META, JPM, XOM";
const RATIONALE_REQUIREMENTS = [
  "3-6 concise paragraphs explaining the allocation decision",
  "cite supporting research, signal, and performance evidence",
  "identify unavailable data instead of guessing",
  "include the informational-analysis disclaimer",
];

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

function summarizeText(value: string, maxLength = 520) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "No sell-side agent information supplied.";
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength).trim()}...`;
}

function buildSupervisorBrief(researchNote: string) {
  return [
    "Condensed sell-side context:",
    summarizeText(researchNote),
    "",
    "Rationale section should return:",
    ...RATIONALE_REQUIREMENTS.map((item) => `- ${item}`),
  ].join("\n");
}

function latestMonthlyReturns(rows: MarketRow[], candidateTickers: string[]) {
  const candidates = new Set(candidateTickers);
  const byTicker = new Map<string, MarketRow[]>();

  for (const row of rows) {
    if (!candidates.has(row.ticker)) {
      continue;
    }
    const tickerRows = byTicker.get(row.ticker) ?? [];
    tickerRows.push(row);
    byTicker.set(row.ticker, tickerRows);
  }

  return Array.from(byTicker.entries())
    .map(([ticker, tickerRows]) => {
      const sortedRows = tickerRows
        .filter((row) => typeof row.close === "number")
        .sort((first, second) => String(first.date).localeCompare(String(second.date)));
      const latest = sortedRows.at(-1);
      const previous = sortedRows.at(-2);
      const latestClose = Number(latest?.close ?? 0);
      const previousClose = Number(previous?.close ?? 0);
      return {
        ticker,
        monthlyReturn:
          latestClose > 0 && previousClose > 0
            ? (latestClose - previousClose) / previousClose
            : Number.NEGATIVE_INFINITY,
      };
    })
    .filter((row) => Number.isFinite(row.monthlyReturn))
    .sort((first, second) => second.monthlyReturn - first.monthlyReturn);
}

function sameTickerSet(first: string[], second: string[]) {
  if (first.length !== second.length) {
    return false;
  }
  const firstSet = new Set(first);
  return second.every((ticker) => firstSet.has(ticker));
}

function splitTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableSeparator(line: string) {
  const cells = splitTableRow(line);
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isTableStart(lines: string[], index: number) {
  return Boolean(
    lines[index]?.includes("|") &&
      lines[index + 1]?.includes("|") &&
      isTableSeparator(lines[index + 1]),
  );
}

function isMarkdownBoundary(lines: string[], index: number) {
  const line = lines[index] ?? "";
  return (
    /^#{1,4}\s+/.test(line) ||
    /^[-*]\s+/.test(line) ||
    /^\d+\.\s+/.test(line) ||
    isTableStart(lines, index)
  );
}

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    return part;
  });
}

function renderMemoHeading(level: number, content: ReactNode[], key: string) {
  if (level <= 1) {
    return (
      <h2 className="memo-heading" key={key}>
        {content}
      </h2>
    );
  }
  if (level === 2) {
    return (
      <h3 className="memo-heading" key={key}>
        {content}
      </h3>
    );
  }
  if (level === 3) {
    return (
      <h4 className="memo-heading" key={key}>
        {content}
      </h4>
    );
  }
  return (
    <h5 className="memo-heading" key={key}>
      {content}
    </h5>
  );
}

function MarkdownMemo({
  content,
  placeholder,
}: {
  content: string;
  placeholder: string;
}) {
  const source = content.trim();
  if (!source) {
    return (
      <div className="agent-output">
        <p className="memo-placeholder">{placeholder}</p>
      </div>
    );
  }

  const lines = source.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      const headers = splitTableRow(lines[index]);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].includes("|")) {
        const row = splitTableRow(lines[index]);
        if (!isTableSeparator(lines[index]) && row.length > 1) {
          rows.push(row);
        }
        index += 1;
      }
      blocks.push(
        <div className="memo-table-wrap" key={`table-${index}`}>
          <table className="memo-table">
            <thead>
              <tr>
                {headers.map((header, cellIndex) => (
                  <th key={`${header}-${cellIndex}`}>
                    {renderInlineMarkdown(header, `table-head-${index}-${cellIndex}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`row-${index}-${rowIndex}`}>
                  {headers.map((_, cellIndex) => (
                    <td key={`cell-${index}-${rowIndex}-${cellIndex}`}>
                      {renderInlineMarkdown(
                        row[cellIndex] ?? "",
                        `table-cell-${index}-${rowIndex}-${cellIndex}`,
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      blocks.push(
        renderMemoHeading(
          heading[1].length,
          renderInlineMarkdown(heading[2], `heading-${index}`),
          `heading-${index}`,
        ),
      );
      index += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul className="memo-list" key={`ul-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`ul-${index}-${itemIndex}`}>
              {renderInlineMarkdown(item, `ul-${index}-${itemIndex}`)}
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ol className="memo-list" key={`ol-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`ol-${index}-${itemIndex}`}>
              {renderInlineMarkdown(item, `ol-${index}-${itemIndex}`)}
            </li>
          ))}
        </ol>,
      );
      continue;
    }

    const paragraphLines = [line];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isMarkdownBoundary(lines, index)
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    blocks.push(
      <p className="memo-paragraph" key={`p-${index}`}>
        {renderInlineMarkdown(paragraphLines.join(" "), `p-${index}`)}
      </p>,
    );
  }

  return <div className="agent-output">{blocks}</div>;
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
  const [researchAgentOutput, setResearchAgentOutput] = useState("");
  const [supervisorAgentOutput, setSupervisorAgentOutput] = useState("");
  const [executionPreview, setExecutionPreview] =
    useState<ExecutionPreview | null>(null);

  const tickers = useMemo(() => parseTickers(tickersInput), [tickersInput]);
  const weights = pipeline?.weights ?? [];
  const bullish = pipeline?.bullish_tickers ?? signals?.bullish_tickers ?? [];
  const bearish = pipeline?.bearish_tickers ?? signals?.bearish_tickers ?? [];
  const latestSignals = (pipeline?.signals_data ?? signals?.signals_data ?? [])
    .slice(-10)
    .reverse();
  const supervisorBrief = useMemo(
    () => buildSupervisorBrief(researchNote),
    [researchNote],
  );

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
      const workingTickers =
        tickers.length > 0 ? tickers : await discoverBullishUniverse();
      const response = await apiRequest<{
        data: MarketRow[];
        failed_tickers: [string, string][];
      }>("/market-data", {
        method: "POST",
        body: JSON.stringify({
          tickers: workingTickers,
          period: "1y",
          interval: "1d",
        }),
      });
      setMarketData(response.data);
      setMessage(
        `Loaded ${response.data.length.toLocaleString()} market rows for ${workingTickers.length} tickers.`,
      );
      setWorkflowState("ready");
    } catch (error) {
      setWorkflowState("error");
      setMessage(error instanceof Error ? error.message : "Market data failed.");
    }
  }

  async function discoverBullishUniverse() {
    setWorkflowState("loading");
    setMessage(
      "Universe is empty. Discovering bullish stocks with the strongest latest monthly returns...",
    );

    const response = await apiRequest<{ data: MarketRow[] }>("/market-data", {
      method: "POST",
      body: JSON.stringify({
        tickers: null,
        period: "3y",
        interval: "1mo",
      }),
    });

    if (response.data.length === 0) {
      throw new Error("No market data returned for automatic universe discovery.");
    }

    setMarketData(response.data);

    const signalResponse = await apiRequest<SignalsResult>("/signals/generate", {
      method: "POST",
      body: JSON.stringify({ market_data: response.data }),
    });

    setSignals(signalResponse);

    const rankedTickers = latestMonthlyReturns(
      response.data,
      signalResponse.bullish_tickers,
    )
      .slice(0, Math.max(numSignals, 1))
      .map((row) => row.ticker);

    if (rankedTickers.length === 0) {
      throw new Error("No bullish stocks with valid monthly returns were found.");
    }

    setTickersInput(rankedTickers.join(", "));
    setMessage(
      `Universe populated with ${rankedTickers.length} bullish stocks ranked by latest monthly return.`,
    );
    return rankedTickers;
  }

  function applyPipelineResult(response: PipelineResult) {
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
  }

  async function ensurePipelineResults(workingTickers: string[]) {
    const pipelineTickers =
      pipeline?.allocation_tickers ?? pipeline?.weights?.map((row) => row.ticker) ?? [];
    if (pipeline?.weights?.length && sameTickerSet(pipelineTickers, workingTickers)) {
      return pipeline;
    }

    setMessage("Running analysis pipeline before agent synthesis...");
    const response = await apiRequest<PipelineResult>("/pipeline/dev/analyze", {
      method: "POST",
      body: JSON.stringify({
        tickers: workingTickers,
        lookback_days: lookbackDays,
        num_signals: numSignals,
      }),
    });
    applyPipelineResult(response);
    return response;
  }

  async function generateSignals() {
    setWorkflowState("loading");
    try {
      let rows = marketData;
      let workingTickers = tickers;
      if (workingTickers.length === 0) {
        workingTickers = await discoverBullishUniverse();
        rows = [];
      }
      if (rows.length === 0) {
        setMessage("Requesting market data before signal generation...");
        const response = await apiRequest<{ data: MarketRow[] }>("/market-data", {
          method: "POST",
          body: JSON.stringify({
            tickers: workingTickers,
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
      const workingTickers =
        tickers.length > 0 ? tickers : await discoverBullishUniverse();
      const response = await apiRequest<PipelineResult>("/pipeline/dev/analyze", {
        method: "POST",
        body: JSON.stringify({
          tickers: workingTickers,
          lookback_days: lookbackDays,
          num_signals: numSignals,
        }),
      });
      applyPipelineResult(response);
      setMessage(
        response.status === "success"
          ? `Pipeline complete with ${response.weights?.length ?? 0} target positions.`
          : response.status === "fallback"
            ? `No daily bullish signals found; using ${response.candidate_tickers?.length ?? 0} pre-screened candidates for allocation.`
          : response.error ?? `Pipeline returned ${response.status ?? "partial"} status.`,
      );
      setWorkflowState(response.status === "failed" ? "error" : "ready");
    } catch (error) {
      setWorkflowState("error");
      setMessage(error instanceof Error ? error.message : "Pipeline failed.");
    }
  }

  async function runResearchAgent() {
    setWorkflowState("loading");
    setMessage("Running sell-side research agent...");
    try {
      const workingTickers =
        tickers.length > 0 ? tickers : await discoverBullishUniverse();
      const pipelineResults = await ensurePipelineResults(workingTickers);
      const response = await apiRequest<AgentRunResult>("/agents/research/run", {
        method: "POST",
        body: JSON.stringify({
          tickers: workingTickers,
          source_context: researchNote,
          pipeline_results: pipelineResults,
          lookback_days: lookbackDays,
          num_signals: numSignals,
        }),
      });

      setResearchAgentOutput(response.output);
      setResearchNote(response.output);
      setMessage("Sell-side research agent output generated.");
      setWorkflowState("ready");
    } catch (error) {
      setWorkflowState("error");
      setMessage(
        error instanceof Error ? error.message : "Research agent run failed.",
      );
    }
  }

  async function runSupervisorAgent() {
    setWorkflowState("loading");
    setMessage("Running supervisor agent...");
    try {
      const workingTickers =
        tickers.length > 0 ? tickers : await discoverBullishUniverse();
      const pipelineResults = await ensurePipelineResults(workingTickers);
      const sellsideResearch =
        researchAgentOutput || researchNote || "No sell-side research output supplied.";
      const response = await apiRequest<AgentRunResult>("/agents/supervisor/run", {
        method: "POST",
        body: JSON.stringify({
          tickers: workingTickers,
          sellside_research: sellsideResearch,
          pipeline_results: pipelineResults,
          lookback_days: lookbackDays,
          num_signals: numSignals,
        }),
      });

      setSupervisorContext(response.context ?? "");
      setSupervisorAgentOutput(response.output);
      setMessage("Supervisor agent output generated.");
      setWorkflowState("ready");
    } catch (error) {
      setWorkflowState("error");
      setMessage(
        error instanceof Error ? error.message : "Supervisor agent run failed.",
      );
    }
  }

  async function buildSupervisorContext() {
    setWorkflowState("loading");
    setMessage("Building supervisor context...");
    try {
      const workingTickers =
        tickers.length > 0 ? tickers : await discoverBullishUniverse();
      const response = await apiRequest<{ context: string }>(
        "/agents/supervisor/context",
        {
          method: "POST",
          body: JSON.stringify({
            tickers: workingTickers,
            sellside_research: supervisorBrief,
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
    setWorkflowState("loading");
    setMessage("Preparing dry-run execution preview...");
    try {
      const executionTickers =
        tickers.length > 0 ? tickers : await discoverBullishUniverse();
      const divisor = Math.min(executionTickers.length, Math.max(1, numSignals));
      const targetWeights =
        weights.length > 0
          ? weights
          : executionTickers.slice(0, divisor).map((ticker) => ({
              ticker,
              weights: 1 / divisor,
            }));

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
            <div className="field">
              <label htmlFor="supervisor-brief">Supervisor rationale brief</label>
              <textarea
                id="supervisor-brief"
                value={supervisorBrief}
                readOnly
                rows={8}
                className="readonly-textarea"
              />
            </div>
            <div className="button-stack">
              <button type="button" onClick={runResearchAgent}>
                Run research agent
              </button>
              <button type="button" onClick={runSupervisorAgent}>
                Run supervisor agent
              </button>
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
                  <p className="eyebrow">Research Agent</p>
                  <h2>Sell-side output</h2>
                </div>
              </div>
              <MarkdownMemo
                content={researchAgentOutput}
                placeholder="Run the research agent to generate sell-side analysis."
              />
            </section>

            <section className="panel text-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Supervisor Agent</p>
                  <h2>Rebalance rationale</h2>
                </div>
              </div>
              <MarkdownMemo
                content={supervisorAgentOutput}
                placeholder="Run the supervisor agent to generate the proposal and rationale."
              />
            </section>
          </div>

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
