"use client";

import { FormEvent, type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

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
  screened_bullish_tickers?: string[];
  bearish_tickers?: string[];
  top_performers?: string[];
  market_data?: MarketRow[];
  signals_data?: MarketRow[];
  weights?: WeightRow[];
  candidate_tickers?: string[];
  allocation_tickers?: string[];
  signal_fallback?: boolean;
  requested_positions?: number;
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

type IbkrConnectionStatus = {
  connected: boolean;
  host?: string | null;
  port?: number | null;
  client_id?: number | null;
  connected_at?: string | null;
  mode?: string | null;
  message?: string;
};

type TradeRecord = {
  symbol?: string | null;
  action?: string | null;
  order_id?: number | null;
  order_type?: string | null;
  quantity?: number | null;
  tif?: string | null;
  status?: string | null;
  filled?: number | null;
  remaining?: number | null;
  avg_fill_price?: number | null;
};

type OrderSizing = {
  account_value: number;
  market_price: number;
  target_notional: number;
  quantity: number;
};

type OrderExecutionResult = {
  dry_run: boolean;
  trade?: TradeRecord;
  sizing?: OrderSizing;
};

type HoldingRow = {
  account?: string | null;
  symbol: string;
  exchange?: string | null;
  currency?: string | null;
  position: number;
  avg_cost?: number | null;
};

type AgentRunResult = {
  output: string;
  context?: string;
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000";

const DEFAULT_TICKERS = "AAPL, MSFT, NVDA, AMZN, GOOGL, META, JPM, XOM";
const DEFAULT_RESEARCH_CONTEXT =
  "Loading default sell-side research instructions...";

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
      const monthlyCloses = new Map<string, number>();
      for (const row of sortedRows) {
        const month = String(row.date).slice(0, 7);
        monthlyCloses.set(month, Number(row.close));
      }
      const currentMonth = new Date().toISOString().slice(0, 7);
      const completedMonths = Array.from(monthlyCloses.entries())
        .filter(([month]) => month < currentMonth)
        .map(([, close]) => close);
      const closes = completedMonths.length >= 2
        ? completedMonths
        : Array.from(monthlyCloses.values());
      const latestClose = closes.at(-1) ?? 0;
      const previousClose = closes.at(-2) ?? 0;
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

type ChartBounds = {
  min: number;
  max: number;
  top: number;
  height: number;
};

function chartNumber(row: MarketRow, key: string) {
  const value = Number(row[key]);
  return Number.isFinite(value) ? value : null;
}

function chartBounds(rows: MarketRow[], keys: string[], top: number, height: number): ChartBounds {
  const values = rows.flatMap((row) =>
    keys
      .map((key) => chartNumber(row, key))
      .filter((value): value is number => value !== null),
  );
  if (values.length === 0) {
    return { min: 0, max: 1, top, height };
  }
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const spread = rawMax - rawMin || Math.max(Math.abs(rawMax) * 0.05, 1);
  return {
    min: rawMin - spread * 0.08,
    max: rawMax + spread * 0.08,
    top,
    height,
  };
}

function chartX(index: number, count: number, width: number, left: number) {
  return left + (count <= 1 ? width / 2 : (index / (count - 1)) * width);
}

function chartY(value: number, bounds: ChartBounds) {
  return bounds.top + bounds.height - ((value - bounds.min) / (bounds.max - bounds.min)) * bounds.height;
}

function chartTicks(bounds: ChartBounds, count = 4) {
  return Array.from({ length: count + 1 }, (_, index) => {
    const value = bounds.max - ((bounds.max - bounds.min) * index) / count;
    return { value, y: chartY(value, bounds) };
  });
}

function chartTickIndices(count: number, desired = 6) {
  if (count <= 1) return [0];
  const tickCount = Math.min(desired, count);
  return Array.from({ length: tickCount }, (_, index) =>
    Math.round((index * (count - 1)) / (tickCount - 1)),
  );
}

function formatChartValue(value: number, decimals: number) {
  return value.toFixed(decimals);
}

function formatChartDate(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "2-digit",
  }).format(parsed);
}

function chartPath(
  rows: MarketRow[],
  key: string,
  bounds: ChartBounds,
  left: number,
  width: number,
) {
  const points = rows
    .map((row, index) => {
      const value = chartNumber(row, key);
      return value === null
        ? null
        : `${chartX(index, rows.length, width, left).toFixed(2)},${chartY(value, bounds).toFixed(2)}`;
    })
    .filter((point): point is string => point !== null);
  return points.length > 1 ? `M ${points.join(" L ")}` : "";
}

function SignalChart({ ticker, rows }: { ticker: string; rows: MarketRow[] }) {
  const sortedRows = [...rows]
    .filter((row) => row.date)
    .sort((first, second) => String(first.date).localeCompare(String(second.date)))
    .slice(-90);
  const left = 78;
  const width = 874;
  const panelHeight = 132;
  const priceBounds = chartBounds(sortedRows, ["close", "_EMA_5", "_EMA_15"], 28, panelHeight);
  const rawMacdBounds = chartBounds(sortedRows, ["_MACD", "_Signal_Line", "_MACD_Hist"], 192, panelHeight);
  const macdBounds = {
    ...rawMacdBounds,
    min: Math.min(rawMacdBounds.min, 0),
    max: Math.max(rawMacdBounds.max, 0),
  };
  const rsiBounds = { min: 0, max: 100, top: 356, height: panelHeight };
  const zeroY = chartY(0, macdBounds);
  const barWidth = Math.max(2, width / Math.max(sortedRows.length, 1) - 2);
  const priceTicks = chartTicks(priceBounds);
  const macdTicks = chartTicks(macdBounds);
  const rsiTicks = chartTicks(rsiBounds, 4);
  const dateIndices = chartTickIndices(sortedRows.length);

  if (sortedRows.length < 2) {
    return <p className="empty-state">No indicator history available for {ticker}.</p>;
  }

  return (
    <div className="signal-chart-wrap">
      <div className="chart-heading">
        <strong>{ticker} indicator history</strong>
        <span>{sortedRows.length} observations</span>
      </div>
      <svg className="signal-chart" viewBox="0 0 980 560" role="img" aria-label={`${ticker} price, EMA, MACD, and RSI chart`}>
        <line className="chart-divider" x1="0" y1="176" x2="980" y2="176" />
        <line className="chart-divider" x1="0" y1="340" x2="980" y2="340" />
        <text className="chart-label" x="8" y="18">PRICE / EMA</text>
        <text className="chart-label" x="8" y="182">MACD</text>
        <text className="chart-label" x="8" y="346">RSI</text>
        {[...priceTicks, ...macdTicks, ...rsiTicks].map((tick, index) => {
          return (
            <line
              className="chart-grid horizontal-grid"
              key={`horizontal-grid-${index}`}
              x1={left}
              y1={tick.y}
              x2={left + width}
              y2={tick.y}
            />
          );
        })}
        {dateIndices.map((index) => {
          const x = chartX(index, sortedRows.length, width, left);
          return (
            <g key={`vertical-grid-${index}`}>
              <line className="chart-grid vertical-grid" x1={x} y1={priceBounds.top} x2={x} y2={rsiBounds.top + rsiBounds.height} />
              <text className="chart-axis-label date-axis-label" x={x} y="516" textAnchor="middle">
                {formatChartDate(String(sortedRows[index].date))}
              </text>
            </g>
          );
        })}
        {priceTicks.map((tick, index) => (
          <text className="chart-axis-label" key={`price-axis-${index}`} x={left - 8} y={tick.y + 4} textAnchor="end">
            {formatChartValue(tick.value, 2)}
          </text>
        ))}
        {macdTicks.map((tick, index) => (
          <text className="chart-axis-label" key={`macd-axis-${index}`} x={left - 8} y={tick.y + 4} textAnchor="end">
            {formatChartValue(tick.value, 3)}
          </text>
        ))}
        {rsiTicks.map((tick, index) => (
          <text className="chart-axis-label" key={`rsi-axis-${index}`} x={left - 8} y={tick.y + 4} textAnchor="end">
            {formatChartValue(tick.value, 0)}
          </text>
        ))}
        <line className="chart-axis" x1={left} y1={priceBounds.top + priceBounds.height} x2={left + width} y2={priceBounds.top + priceBounds.height} />
        <line className="chart-axis" x1={left} y1={macdBounds.top + macdBounds.height} x2={left + width} y2={macdBounds.top + macdBounds.height} />
        <line className="chart-axis" x1={left} y1={rsiBounds.top + rsiBounds.height} x2={left + width} y2={rsiBounds.top + rsiBounds.height} />
        <path className="chart-line price-line" d={chartPath(sortedRows, "close", priceBounds, left, width)} />
        <path className="chart-line ema-fast-line" d={chartPath(sortedRows, "_EMA_5", priceBounds, left, width)} />
        <path className="chart-line ema-slow-line" d={chartPath(sortedRows, "_EMA_15", priceBounds, left, width)} />
        {sortedRows.map((row, index) => {
          const value = chartNumber(row, "_MACD_Hist");
          if (value === null) return null;
          const x = chartX(index, sortedRows.length, width, left) - barWidth / 2;
          const y = chartY(value, macdBounds);
          return (
            <rect
              className={value >= 0 ? "macd-bar positive-bar" : "macd-bar negative-bar"}
              key={`macd-bar-${index}`}
              x={x}
              y={Math.min(y, zeroY)}
              width={barWidth}
              height={Math.max(1, Math.abs(y - zeroY))}
            />
          );
        })}
        <line className="chart-zero" x1={left} y1={zeroY} x2={left + width} y2={zeroY} />
        <path className="chart-line macd-line" d={chartPath(sortedRows, "_MACD", macdBounds, left, width)} />
        <path className="chart-line signal-line" d={chartPath(sortedRows, "_Signal_Line", macdBounds, left, width)} />
        <line className="chart-guide" x1={left} y1={chartY(70, rsiBounds)} x2={left + width} y2={chartY(70, rsiBounds)} />
        <line className="chart-guide" x1={left} y1={chartY(30, rsiBounds)} x2={left + width} y2={chartY(30, rsiBounds)} />
        <path className="chart-line rsi-fast-line" d={chartPath(sortedRows, "_FAST_RSI", rsiBounds, left, width)} />
        <path className="chart-line rsi-slow-line" d={chartPath(sortedRows, "_SLOW_RSI", rsiBounds, left, width)} />
        <text className="chart-axis-label date-axis-title" x={left + width / 2} y="544" textAnchor="middle">DATE</text>
      </svg>
      <div className="chart-legend" aria-hidden="true">
        <span><i className="legend-swatch price-line" />Price</span>
        <span><i className="legend-swatch ema-fast-line" />EMA 5</span>
        <span><i className="legend-swatch ema-slow-line" />EMA 15</span>
        <span><i className="legend-swatch macd-line" />MACD</span>
        <span><i className="legend-swatch signal-line" />Signal</span>
        <span><i className="legend-swatch rsi-fast-line" />RSI 5</span>
        <span><i className="legend-swatch rsi-slow-line" />RSI 15</span>
      </div>
    </div>
  );
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
  const [lookbackMonths, setLookbackMonths] = useState(3);
  const [numSignals, setNumSignals] = useState(8);
  const [researchNote, setResearchNote] = useState(DEFAULT_RESEARCH_CONTEXT);

  const [backendState, setBackendState] = useState<ApiState>("idle");
  const [workflowState, setWorkflowState] = useState<ApiState>("idle");
  const [ibkrState, setIbkrState] = useState<ApiState>("idle");
  const [message, setMessage] = useState("Ready to connect to SideChart API.");

  const [signals, setSignals] = useState<SignalsResult | null>(null);
  const [pipeline, setPipeline] = useState<PipelineResult | null>(null);
  const [researchAgentOutput, setResearchAgentOutput] = useState("");
  const [supervisorAgentOutput, setSupervisorAgentOutput] = useState("");
  const [executionPreview, setExecutionPreview] =
    useState<ExecutionPreview | null>(null);
  const [ibkrStatus, setIbkrStatus] = useState<IbkrConnectionStatus | null>(
    null,
  );
  const [executingTicker, setExecutingTicker] = useState<string | null>(null);
  const [lastOrderResult, setLastOrderResult] =
    useState<OrderExecutionResult | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [holdings, setHoldings] = useState<HoldingRow[]>([]);
  const [holdingsState, setHoldingsState] = useState<ApiState>("idle");
  const [sellAmounts, setSellAmounts] = useState<Record<string, string>>({});
  const [executingSellTicker, setExecutingSellTicker] = useState<string | null>(null);

  const tickers = useMemo(() => parseTickers(tickersInput), [tickersInput]);
  const weights = pipeline?.weights ?? [];
  const bullish = pipeline?.bullish_tickers ?? signals?.bullish_tickers ?? [];
  const bearish = pipeline?.bearish_tickers ?? signals?.bearish_tickers ?? [];
  const selectedIndicatorRows = useMemo(
    () =>
      (pipeline?.signals_data ?? signals?.signals_data ?? []).filter(
        (row) => row.ticker === selectedTicker,
      ),
    [pipeline?.signals_data, signals?.signals_data, selectedTicker],
  );

  const allocationTotal = weights.reduce(
    (total, row) => total + Number(row.weights ?? 0),
    0,
  );
  const ibkrConnected = ibkrState === "ready" && Boolean(ibkrStatus?.connected);

  const refreshHoldings = useCallback(async (force = false) => {
    if (!force && !ibkrConnected) {
      setMessage("Connect to IBKR before loading current holdings.");
      return;
    }

    setHoldingsState("loading");
    try {
      const response = await apiRequest<{ holdings: HoldingRow[] }>(
        "/portfolio/holdings",
      );
      setHoldings(response.holdings ?? []);
      setHoldingsState("ready");
      setMessage(
        response.holdings.length
          ? `Loaded ${response.holdings.length} current IBKR holdings.`
          : "IBKR is connected, but no current holdings were returned.",
      );
    } catch (error) {
      setHoldingsState("error");
      setMessage(error instanceof Error ? error.message : "Holdings query failed.");
    }
  }, [ibkrConnected]);

  useEffect(() => {
    let isMounted = true;

    async function loadResearchPrompt() {
      try {
        const response = await apiRequest<{ prompt: string }>(
          "/agents/research/prompt",
        );
        if (isMounted && response.prompt) {
          setResearchNote((current) =>
            current === DEFAULT_RESEARCH_CONTEXT ? response.prompt : current,
          );
        }
      } catch {
        if (isMounted) {
          setResearchNote((current) =>
            current === DEFAULT_RESEARCH_CONTEXT
              ? "Default sell-side research instructions could not be loaded."
              : current,
          );
        }
      }
    }

    loadResearchPrompt();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    apiRequest<IbkrConnectionStatus>("/broker/ibkr/status")
      .then((status) => {
        setIbkrStatus(status);
        setIbkrState(status.connected ? "ready" : "idle");
        if (status.connected) {
          void refreshHoldings(true);
        }
      })
      .catch(() => setIbkrState("error"));
  }, [refreshHoldings]);

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

  async function connectIbkr() {
    setIbkrState("loading");
    setMessage("Connecting to IBKR Trader Workstation or Gateway...");
    try {
      const response = await apiRequest<IbkrConnectionStatus>(
        "/broker/ibkr/connect",
        {
          method: "POST",
          body: JSON.stringify({}),
        },
      );
      setIbkrStatus(response);
      setIbkrState(response.connected ? "ready" : "error");
      setBackendState("ready");
      setMessage(
        response.message ??
          `IBKR connected on ${response.host ?? "127.0.0.1"}:${response.port ?? ""}.`,
      );
      if (response.connected) {
        await refreshHoldings(true);
      }
    } catch (error) {
      setIbkrState("error");
      setMessage(error instanceof Error ? error.message : "IBKR connection failed.");
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
        period: "5y",
        interval: "1mo",
      }),
    });

    if (response.data.length === 0) {
      throw new Error("No market data returned for automatic universe discovery.");
    }

    const availableTickers = Array.from(new Set(response.data.map((row) => row.ticker)));
    const rankedTickers = latestMonthlyReturns(response.data, availableTickers)
      .slice(0, Math.max(numSignals * 3, numSignals, 1))
      .map((row) => row.ticker);

    if (rankedTickers.length === 0) {
      throw new Error("No bullish stocks with valid monthly returns were found.");
    }

    setTickersInput(rankedTickers.join(", "));
    setMessage(`Universe populated with ${rankedTickers.length} highest monthly performers for signal screening.`);
    return rankedTickers;
  }

  function applyPipelineResult(response: PipelineResult) {
    setPipeline(response);
    if (response.allocation_tickers?.length) {
      setTickersInput(response.allocation_tickers.join(", "));
    }
    if (response.weights?.[0]?.ticker) {
      setSelectedTicker(response.weights[0].ticker);
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
    if (
      pipeline?.weights?.length &&
      pipeline.requested_positions === numSignals &&
      sameTickerSet(pipelineTickers, workingTickers)
    ) {
      return pipeline;
    }

    setMessage("Running analysis pipeline before agent synthesis...");
    const response = await apiRequest<PipelineResult>("/pipeline/dev/analyze", {
      method: "POST",
      body: JSON.stringify({
        tickers: workingTickers,
        lookback_months: lookbackMonths,
        num_signals: numSignals,
      }),
    });
    applyPipelineResult(response);
    return response;
  }

  async function generateSignals() {
    setWorkflowState("loading");
    try {
      let workingTickers = tickers;
      if (workingTickers.length === 0) {
        workingTickers = await discoverBullishUniverse();
      }
      setMessage("Requesting completed-month market data before signal generation...");
      const response = await apiRequest<{ data: MarketRow[] }>("/market-data", {
        method: "POST",
        body: JSON.stringify({
          tickers: workingTickers,
          period: "5y",
          interval: "1mo",
        }),
      });
      const rows = response.data;

      if (rows.length === 0) {
        setWorkflowState("error");
        setMessage("No market rows available for signal generation.");
        return;
      }

      setWorkflowState("loading");
      setMessage("Generating technical signals...");
      const rankedTickers = latestMonthlyReturns(rows, workingTickers)
        .slice(0, Math.max(numSignals * 3, numSignals, 1))
        .map((row) => row.ticker);
      const signalRows = rows.filter((row) => rankedTickers.includes(row.ticker));
      if (rankedTickers.length > 0) {
        setTickersInput(rankedTickers.join(", "));
      }

      const signalResponse = await apiRequest<SignalsResult>("/signals/generate", {
        method: "POST",
        body: JSON.stringify({ market_data: signalRows }),
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
      const workingTickers = tickers;
      const response = await apiRequest<PipelineResult>("/pipeline/dev/analyze", {
        method: "POST",
        body: JSON.stringify({
          tickers: workingTickers,
          lookback_months: lookbackMonths,
          num_signals: numSignals,
        }),
      });
      applyPipelineResult(response);
      setMessage(
        response.status === "success"
          ? `Pipeline complete with ${response.weights?.length ?? 0} bullish target positions.`
          : response.status === "partial"
            ? `Found ${response.weights?.length ?? 0} bullish positions of ${numSignals} requested in the available market data.`
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
          lookback_months: lookbackMonths,
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
          lookback_months: lookbackMonths,
          num_signals: numSignals,
        }),
      });

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

  async function executeTickerTrade(row: WeightRow) {
    if (!ibkrConnected) {
      setMessage("Connect to IBKR before executing trades.");
      return;
    }

    setExecutingTicker(row.ticker);
    setMessage(
      `Sizing ${row.ticker} order from ${formatPercent(row.weights)} target weight...`,
    );
    try {
      const response = await apiRequest<OrderExecutionResult>("/orders/buy", {
        method: "POST",
        body: JSON.stringify({
          ticker: row.ticker,
          target_weight: row.weights,
          dry_run: false,
        }),
      });
      setLastOrderResult(response);
      setMessage(
        `IBKR order ${response.trade?.order_id ?? "pending"}: ${response.trade?.quantity ?? response.sizing?.quantity ?? 0} shares of ${row.ticker} from ${formatPercent(row.weights)} target weight. Status: ${response.trade?.status ?? "pending"}.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Trade execution failed.");
    } finally {
      setExecutingTicker(null);
    }
  }

  async function executeSell(symbol: string, quantity?: number) {
    if (!ibkrConnected) {
      setMessage("Connect to IBKR before executing sells.");
      return;
    }

    const holding = holdings.find((row) => row.symbol === symbol);
    const availableShares = Math.max(0, Math.floor(Number(holding?.position ?? 0)));
    if (availableShares <= 0) {
      setMessage(`No long shares are available to sell for ${symbol}.`);
      return;
    }
    if (quantity !== undefined && (!Number.isInteger(quantity) || quantity < 1 || quantity > availableShares)) {
      setMessage(`Sell quantity for ${symbol} must be between 1 and ${availableShares} shares.`);
      return;
    }

    setExecutingSellTicker(symbol);
    setMessage(
      quantity === undefined
        ? `Submitting an order to sell all ${availableShares} shares of ${symbol}...`
        : `Submitting an order to sell ${quantity} shares of ${symbol}...`,
    );
    try {
      const body: { ticker: string; quantity?: number; dry_run: boolean } = {
        ticker: symbol,
        dry_run: false,
      };
      if (quantity !== undefined) {
        body.quantity = quantity;
      }
      const response = await apiRequest<OrderExecutionResult>("/orders/sell", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setLastOrderResult(response);
      setMessage(
        `IBKR sell order ${response.trade?.order_id ?? "pending"}: ${response.trade?.quantity ?? 0} shares of ${symbol}. Status: ${response.trade?.status ?? "pending"}.`,
      );
      await refreshHoldings(true);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sell execution failed.");
    } finally {
      setExecutingSellTicker(null);
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
                <label htmlFor="lookback">Lookback (in months)</label>
                <input
                  id="lookback"
                  type="number"
                  min={1}
                  value={lookbackMonths}
                  onChange={(event) => setLookbackMonths(Number(event.target.value))}
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
              <button type="button" onClick={runResearchAgent}>
                Run research agent
              </button>
              <button type="button" onClick={runSupervisorAgent}>
                Run supervisor agent
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
                      <div className="allocation-row-header">
                        <div className="allocation-row-label">
                          <button
                            type="button"
                            className={`ticker-select ${selectedTicker === row.ticker ? "selected" : ""}`}
                            onClick={() => setSelectedTicker(row.ticker)}
                            aria-pressed={selectedTicker === row.ticker}
                          >
                            {row.ticker}
                          </button>
                          <span>{formatPercent(row.weights)}</span>
                        </div>
                        <button
                          type="button"
                          className="trade-button"
                          onClick={() => executeTickerTrade(row)}
                          disabled={!ibkrConnected || Boolean(executingTicker) || row.weights <= 0}
                        >
                          {executingTicker === row.ticker
                            ? "Executing..."
                            : "Execute trade"}
                        </button>
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

          <section className="panel holdings-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Interactive Brokers</p>
                <h2>Current holdings</h2>
              </div>
              <div className="holdings-actions">
                <span className={`pill ${holdingsState}`}>
                  {holdingsState === "ready" ? `${holdings.length} positions` : holdingsState}
                </span>
                <button
                  type="button"
                  onClick={() => refreshHoldings()}
                  disabled={!ibkrConnected || holdingsState === "loading"}
                >
                  Refresh holdings
                </button>
              </div>
            </div>
            {holdings.length > 0 ? (
              <div className="holdings-list">
                {holdings.map((holding) => {
                  const availableShares = Math.max(0, Math.floor(Number(holding.position ?? 0)));
                  const enteredAmount = sellAmounts[holding.symbol] ?? "";
                  const sellAmount = Number(enteredAmount);
                  const isSelling = executingSellTicker === holding.symbol;
                  return (
                    <div className="holding-row" key={`${holding.account ?? "account"}-${holding.symbol}`}>
                      <div className="holding-identity">
                        <strong>{holding.symbol}</strong>
                        <span>{availableShares.toLocaleString()} shares</span>
                      </div>
                      <div className="holding-actions">
                        <input
                          aria-label={`Shares to sell for ${holding.symbol}`}
                          type="number"
                          min={1}
                          max={availableShares}
                          step={1}
                          value={enteredAmount}
                          onChange={(event) =>
                            setSellAmounts((current) => ({
                              ...current,
                              [holding.symbol]: event.target.value,
                            }))
                          }
                          placeholder="Shares"
                          disabled={isSelling || availableShares <= 0}
                        />
                        <button
                          type="button"
                          onClick={() => executeSell(holding.symbol, Math.floor(sellAmount))}
                          disabled={isSelling || availableShares <= 0 || !Number.isInteger(sellAmount) || sellAmount < 1 || sellAmount > availableShares}
                        >
                          Sell amount
                        </button>
                        <button
                          type="button"
                          onClick={() => executeSell(holding.symbol)}
                          disabled={isSelling || availableShares <= 0}
                        >
                          {isSelling ? "Selling..." : "Sell all"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="empty-state">
                {ibkrConnected
                  ? "No current holdings returned from IBKR."
                  : "Connect to IBKR to query current holdings."}
              </p>
            )}
          </section>

          <section className="panel table-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Latest Indicators</p>
                <h2>{selectedTicker ?? "Signal data snapshot"}</h2>
              </div>
            </div>
            {selectedTicker ? (
              <SignalChart ticker={selectedTicker} rows={selectedIndicatorRows} />
            ) : (
              <p className="empty-state chart-empty-state">
                Select a ticker in Draft portfolio weights to inspect its indicator history.
              </p>
            )}
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
                  <p className="eyebrow">Execution</p>
                  <h2>Dry-run preview</h2>
                </div>
                <div className="execution-actions">
                  <span className={`pill ${ibkrState}`}>
                    {ibkrConnected ? "connected" : ibkrState}
                  </span>
                  <button
                    type="button"
                    onClick={connectIbkr}
                    disabled={ibkrState === "loading"}
                  >
                    Connect to IBKR
                  </button>
                </div>
              </div>
              {lastOrderResult?.trade ? (
                <div className="execution-list latest-order">
                  <p>Last IBKR order #{lastOrderResult.trade.order_id ?? "pending"}</p>
                  <div className="execution-row">
                    <span>{lastOrderResult.trade.symbol ?? "--"}</span>
                    <strong>
                      {lastOrderResult.trade.action ?? "BUY"}{" "}
                      {lastOrderResult.trade.quantity ??
                        lastOrderResult.sizing?.quantity ??
                        "--"}
                    </strong>
                  </div>
                  {lastOrderResult.sizing ? (
                    <div className="execution-row">
                      <span>
                        ${lastOrderResult.sizing.target_notional.toLocaleString(
                          undefined,
                          { maximumFractionDigits: 2 },
                        )}
                      </span>
                      <strong>
                        @ $
                        {lastOrderResult.sizing.market_price.toLocaleString(
                          undefined,
                          { maximumFractionDigits: 2 },
                        )}
                      </strong>
                    </div>
                  ) : null}
                  <div className="execution-row">
                    <span>{lastOrderResult.trade.status ?? "submitted"}</span>
                    <strong>
                      {lastOrderResult.trade.order_type ?? "MKT"}{" "}
                      {lastOrderResult.trade.tif ?? "GTC"}
                    </strong>
                  </div>
                </div>
              ) : null}
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
