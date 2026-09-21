from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

import pandas as pd

from contracts.rebalance import RebalanceProposal


MAX_CONTEXT_ROWS = 20
DEFAULT_RESEARCH_PROMPT_FALLBACK = """
You are an institutional Sell-Side Equities Research Analyst. Your objective is
to discover material, stock-specific catalysts and convert them into an
actionable institutional investment thesis. Separate historical reported facts
from estimates, quantify available valuation evidence, state unavailable data
explicitly, and avoid definitive investment advice or return guarantees.
"""


def _empty_frame(columns: Iterable[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _coerce_dataframe(value: Any) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if isinstance(value, dict):
        return pd.DataFrame([value])
    if isinstance(value, list):
        return pd.DataFrame(value)
    return pd.DataFrame()


def _format_dataframe(value: Any, max_rows: int = MAX_CONTEXT_ROWS) -> str:
    df = _coerce_dataframe(value)
    if df.empty:
        return 'Unavailable'
    return df.head(max_rows).to_string(index=False)


def _latest_signals(signals_data: Any) -> pd.DataFrame:
    signals_df = _coerce_dataframe(signals_data)
    if signals_df.empty or 'ticker' not in signals_df.columns:
        return _empty_frame(
            [
                'ticker',
                'date',
                'close',
                '_FAST_RSI',
                '_SLOW_RSI',
                '_MACD',
                '_Signal_Line',
                '_MACD_Hist',
                '_EMA_5',
                '_EMA_15',
            ]
        )

    df = signals_df.copy()
    if 'date' in df.columns:
        df = df.sort_values(['ticker', 'date'])
    latest = df.groupby('ticker', as_index=False).tail(1)
    columns = [
        column
        for column in [
            'ticker',
            'date',
            'close',
            '_FAST_RSI',
            '_SLOW_RSI',
            '_MACD',
            '_Signal_Line',
            '_MACD_Hist',
            '_EMA_5',
            '_EMA_15',
        ]
        if column in latest.columns
    ]
    return latest[columns].sort_values('ticker')


def _performance_snapshot(market_data: Any, current_positions: Any = None) -> pd.DataFrame:
    market_df = _coerce_dataframe(market_data)
    positions_df = _coerce_dataframe(current_positions)

    if market_df.empty or not {'ticker', 'close'}.issubset(market_df.columns):
        return positions_df

    sort_columns = ['ticker']
    if 'date' in market_df.columns:
        sort_columns.append('date')

    rows = []
    for ticker, ticker_data in market_df.sort_values(sort_columns).groupby('ticker'):
        first_close = ticker_data['close'].iloc[0]
        last_close = ticker_data['close'].iloc[-1]
        if first_close and first_close > 0:
            lookback_return = (last_close - first_close) / first_close
        else:
            lookback_return = None

        rows.append(
            {
                'ticker': ticker,
                'first_close': first_close,
                'last_close': last_close,
                'lookback_return': lookback_return,
            }
        )

    performance_df = pd.DataFrame(rows)
    if positions_df.empty or 'ticker' not in positions_df.columns:
        return performance_df.sort_values('lookback_return', ascending=False)

    return positions_df.merge(performance_df, on='ticker', how='outer')


def _proposal_from_pipeline(
    pipeline_results: dict[str, Any],
    sellside_research: str,
) -> RebalanceProposal:
    target_weights = _coerce_dataframe(pipeline_results.get('weights'))
    if target_weights.empty:
        target_weights = _empty_frame(['ticker', 'weights'])

    source_signals = {
        'status': pipeline_results.get('status', 'not_run'),
        'bullish_tickers': pipeline_results.get('bullish_tickers', []),
        'bearish_tickers': pipeline_results.get('bearish_tickers', []),
        'top_performers': pipeline_results.get('top_performers', []),
    }

    return RebalanceProposal(
        target_weights=target_weights,
        rationale='Pending supervisor synthesis.',
        source_signals=source_signals,
        source_research=sellside_research,
        assumptions=[
            'Weights are draft targets from the analysis pipeline.',
            'Proposal requires human review and risk validation before execution.',
        ],
        risks=[
            'Market data, research, or portfolio positions may be stale.',
            'Optimization output may be incomplete if upstream data is unavailable.',
        ],
    )


def supervisor_agent(
    tickers: list[str] | None = None,
    sellside_research: str | None = None,
    pipeline_results: dict[str, Any] | None = None,
    current_positions: Any = None,
    lookback_days: int = 30,
    num_signals: int = 20,
) -> str:
    """
    Build instructions for the supervisor agent.

    The supervisor coordinates the rebalance/research cycle. It consumes the
    sell-side research agent output, technical signals, portfolio performance,
    and target weights, then emits a RebalanceProposal and rationale.
    """
    if pipeline_results is None:
        pipeline_results = {}
        if tickers:
            from contracts.prod.pipeline import run_analysis_pipeline

            pipeline_results = run_analysis_pipeline(
                tickers=tickers,
                lookback_days=lookback_days,
                num_signals=num_signals,
            )

    research_context = sellside_research or (
        'No completed sell-side research response was supplied. '
        'Use this research-agent prompt as the expected upstream mandate:\n'
        f'{DEFAULT_RESEARCH_PROMPT_FALLBACK.strip()}'
    )

    proposal = _proposal_from_pipeline(pipeline_results, research_context)
    latest_signals = _latest_signals(pipeline_results.get('signals_data'))
    performance_snapshot = _performance_snapshot(
        pipeline_results.get('market_data'),
        current_positions=current_positions,
    )

    return f'''The current date and time is {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.
You are the SideChart supervisor agent coordinating a rebalance and research cycle.

MISSION:
Synthesize the sell-side research output, technical signals, portfolio performance, current holdings, and optimizer weights into one explainable draft rebalance. You do not execute trades. You produce a human-reviewable RebalanceProposal and a concise rationale for why the allocation should be accepted, modified, or rejected.

INPUTS:
1. Sell-side research agent output:
{research_context}

2. Draft target weights from contracts.risk.port_opt via contracts.pipeline.run_analysis_pipeline:
{_format_dataframe(proposal.target_weights)}

3. Signal summary from contracts.signals.signal_generator:
Status: {proposal.source_signals['status']}
Bullish tickers: {proposal.source_signals['bullish_tickers']}
Bearish tickers: {proposal.source_signals['bearish_tickers']}
Latest indicator snapshot:
{_format_dataframe(latest_signals)}

4. Portfolio/performance snapshot from contracts.portfolio and market data:
Top performers: {proposal.source_signals['top_performers']}
Current positions plus lookback performance:
{_format_dataframe(performance_snapshot)}

SUPERVISOR RESPONSIBILITIES:
1. Reconcile research and signals. Flag tickers where fundamental research
   conflicts with technical momentum or portfolio performance.
2. Explain proposed allocation. Reference target weights, current exposures,
   recent performance, and the research thesis without inventing unavailable
   metrics.
3. Identify portfolio actions. Classify each material position as buy, sell,
   hold, reduce, increase, or exclude.
4. Surface risk and data quality. Note stale, missing, partial, or contradictory
   inputs, plus concentration and turnover concerns.
5. Preserve paper-trading guardrails. The proposal is advisory and must pass
   risk validation before any execution.

OUTPUT SPECIFICATION:
Return exactly two top-level sections formatted as a finance-professional memo.

RebalanceProposal:
- status: draft, needs_review, or rejected
- generated_at: ISO-8601 timestamp
- target_weights: markdown table with columns Ticker | Target Weight | Signal View | Research View | Proposed Action
- actions: markdown table with columns Ticker | Action | Current Weight | Target Weight | Weight Delta | Rationale
- assumptions: concise bullets
- risks: concise bullets covering portfolio, market, data-quality, and execution risks

Rationale:
1. Allocation Summary: 1-2 concise paragraphs explaining the portfolio-level decision.
2. Research / Signal Reconciliation: bullets or short paragraphs that cite the sell-side
   research output, bullish/bearish technical signals, latest indicator evidence, and
   top-performer/performance context.
3. Ticker-Level Review: compact markdown table with one row for each target-weight ticker.
4. Data Quality and Open Items: explicitly identify unavailable data instead of guessing.
5. Compliance Note: state that this is informational analysis only, not personalized
   investment advice, and not a guarantee of returns.
'''


def build_rebalance_proposal_context(*args: Any, **kwargs: Any) -> str:
    """Alias for callers that prefer an explicit orchestration name."""
    return supervisor_agent(*args, **kwargs)
