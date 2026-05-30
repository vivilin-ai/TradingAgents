"""BatchRunner: run TradingAgentsGraph for one or many tickers.

Output directory structure (all relative to config["reports_root"]):
  manual/<DATE>_<TICKER>/complete_report.md   — single-stock
  batch/<DATE>/{summary.md, TICKER.md, …}    — multi-ticker batch
  scheduled/<task_name>/<DATE>/{…}           — scheduled task
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients import create_llm_client

from .watchlist import load_watchlist
from .summary import generate_summary

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _latest_trading_day(d: Optional[datetime.date] = None) -> datetime.date:
    d = d or datetime.date.today()
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


def _resolve_date(trade_date: Optional[str]) -> str:
    if trade_date:
        return trade_date
    return _latest_trading_day().strftime("%Y-%m-%d")


def _output_dir(
    config: dict,
    mode: str,
    trade_date: str,
    ticker: Optional[str] = None,
    task_name: Optional[str] = None,
) -> Path:
    root = Path(config["reports_root"]).expanduser()
    if mode == "manual" and ticker:
        return root / "manual" / f"{trade_date}_{ticker}"
    if mode == "batch":
        return root / "batch" / trade_date
    if mode == "scheduled" and task_name:
        return root / "scheduled" / task_name / trade_date
    return root / "manual" / trade_date


def _build_report(state: dict[str, Any], ticker: str, trade_date: str) -> str:
    sections: list[str] = [
        f"# Trading Analysis: {ticker}",
        f"",
        f"**Date:** {trade_date}",
        f"",
    ]

    analyst_parts = []
    for key, title in [
        ("market_report", "Market Analysis"),
        ("sentiment_report", "Social Sentiment"),
        ("news_report", "News Analysis"),
        ("fundamentals_report", "Fundamentals Analysis"),
    ]:
        if state.get(key):
            analyst_parts.append(f"### {title}\n\n{state[key]}")
    if analyst_parts:
        sections += ["## I. Analyst Team Reports", ""] + analyst_parts

    debate = (state.get("investment_debate_state") or {})
    research_parts = []
    for key, title in [
        ("bull_history", "Bull Researcher"),
        ("bear_history", "Bear Researcher"),
        ("judge_decision", "Research Manager"),
    ]:
        if debate.get(key):
            research_parts.append(f"### {title}\n\n{debate[key]}")
    if research_parts:
        sections += ["", "## II. Research Team", ""] + research_parts

    if state.get("trader_investment_plan"):
        sections += ["", "## III. Trader", "", state["trader_investment_plan"]]

    risk = (state.get("risk_debate_state") or {})
    risk_parts = []
    for key, title in [
        ("aggressive_history", "Aggressive Analyst"),
        ("conservative_history", "Conservative Analyst"),
        ("neutral_history", "Neutral Analyst"),
    ]:
        if risk.get(key):
            risk_parts.append(f"### {title}\n\n{risk[key]}")
    if risk_parts:
        sections += ["", "## IV. Risk Management", ""] + risk_parts

    if state.get("final_trade_decision"):
        sections += ["", "## V. Portfolio Manager Decision", "", state["final_trade_decision"]]

    return "\n".join(sections)


# ── BatchRunner ───────────────────────────────────────────────────────────────

class BatchRunner:
    """Run TradingAgents analysis for one or many tickers.

    Args:
        config: Merged TradingAgents config dict (defaults to DEFAULT_CONFIG).
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}

    # ── Public API ────────────────────────────────────────────────────────────

    def run_single(
        self,
        ticker: str,
        trade_date: Optional[str] = None,
        mode: str = "manual",
        task_name: Optional[str] = None,
        position: Optional[dict] = None,
        on_complete: Optional[Callable[[dict], None]] = None,
    ) -> dict[str, Any]:
        """Analyse a single ticker.

        Args:
            ticker:      Ticker symbol (e.g. "NVDA").
            trade_date:  Date string YYYY-MM-DD; defaults to last trading day.
            mode:        "manual" | "scheduled".  Determines output sub-directory.
            task_name:   Required when mode=="scheduled".
            position:    Optional dict with keys ``cost`` (float) and ``qty``
                         (float) representing the user's current holding.  When
                         None, the PM is told the user has no position.
            on_complete: Optional callback called with the result dict when done.

        Returns:
            Result dict with keys: ticker, date, rating, final_state,
            report_path, pm_decision, error.
        """
        from .watchlist import format_position_context
        trade_date = _resolve_date(trade_date)
        out_dir = _output_dir(self.config, mode, trade_date, ticker=ticker, task_name=task_name)
        extra_context = format_position_context(ticker, position)
        result = self._run_one(ticker, trade_date, out_dir, extra_context=extra_context)
        if on_complete:
            try:
                on_complete(result)
            except Exception as exc:
                logger.warning("on_complete callback raised: %s", exc)
        return result

    def run_batch(
        self,
        tickers: Optional[list[str]] = None,
        trade_date: Optional[str] = None,
        mode: str = "batch",
        task_name: Optional[str] = None,
        narrative: bool = True,
        on_ticker_done: Optional[Callable[[dict], None]] = None,
        on_complete: Optional[Callable[[list[dict], Path], None]] = None,
    ) -> tuple[list[dict[str, Any]], Path]:
        """Analyse multiple tickers and generate a summary.

        Args:
            tickers:       List of tickers. If None, loads from watchlist.
            trade_date:    Date string YYYY-MM-DD.
            mode:          "batch" | "scheduled".
            task_name:     Required when mode=="scheduled".
            narrative:     Include LLM cross-ticker narrative in summary.
            on_ticker_done: Called after each ticker completes.
            on_complete:   Called with (results, summary_path) when all done.

        Returns:
            (results, summary_path)
        """
        trade_date = _resolve_date(trade_date)

        if tickers is None:
            wl = load_watchlist(self.config["watchlist_path"])
            tickers = wl.get("tickers", [])

        if not tickers:
            logger.warning("No tickers to analyse.")
            out_dir = _output_dir(self.config, mode, trade_date, task_name=task_name)
            out_dir.mkdir(parents=True, exist_ok=True)
            summary_path = out_dir / "summary.md"
            summary_path.write_text("# Batch Analysis\n\nNo tickers configured.", encoding="utf-8")
            return [], summary_path

        out_dir = _output_dir(self.config, mode, trade_date, task_name=task_name)
        out_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Batch start: %d tickers → %s", len(tickers), out_dir)
        results: list[dict[str, Any]] = []

        for ticker in tickers:
            result = self._run_one(ticker, trade_date, out_dir)
            results.append(result)
            status = result.get("rating", "—") if not result.get("error") else f"ERR: {result['error'][:60]}"
            logger.info("[%s] %s", ticker, status)
            if on_ticker_done:
                try:
                    on_ticker_done(result)
                except Exception as exc:
                    logger.warning("on_ticker_done callback raised: %s", exc)

        # Write errors file if needed
        errors = [r for r in results if r.get("error")]
        if errors:
            self._write_errors(errors, out_dir)

        # Summary
        llm = self._make_narrative_llm() if narrative else None
        from datetime import date as _date
        iso_week = datetime.date.fromisoformat(trade_date).isocalendar()
        iso_label = f"{iso_week[0]}-W{iso_week[1]:02d}"

        summary_md = generate_summary(
            results=results,
            trade_date=trade_date,
            iso_week=iso_label,
            narrative=narrative,
            llm=llm,
        )
        summary_path = out_dir / "summary.md"
        summary_path.write_text(summary_md, encoding="utf-8")
        logger.info("Summary written → %s", summary_path)

        if on_complete:
            try:
                on_complete(results, summary_path)
            except Exception as exc:
                logger.warning("on_complete callback raised: %s", exc)

        return results, summary_path

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _run_one(
        self,
        ticker: str,
        trade_date: str,
        out_dir: Path,
        extra_context: str = "",
    ) -> dict[str, Any]:
        """Run a single ticker; return result dict even on failure."""
        try:
            graph = TradingAgentsGraph(
                selected_analysts=self._analysts(),
                config=self.config,
            )
            final_state, rating = graph.propagate(ticker, trade_date, extra_context=extra_context)

            out_dir.mkdir(parents=True, exist_ok=True)
            report_md = _build_report(final_state, ticker, trade_date)
            report_path = out_dir / f"{ticker}.md"
            report_path.write_text(report_md, encoding="utf-8")

            pm_decision = final_state.get("final_trade_decision", "")

            return {
                "ticker": ticker,
                "date": trade_date,
                "rating": rating,
                "final_state": final_state,
                "report_path": str(report_path),
                "pm_decision": pm_decision,
                "error": None,
            }

        except Exception as exc:
            logger.error("Failed to analyse %s: %s", ticker, exc, exc_info=True)
            return {
                "ticker": ticker,
                "date": trade_date,
                "rating": "Hold",
                "final_state": None,
                "report_path": None,
                "pm_decision": None,
                "error": str(exc),
            }

    def _analysts(self) -> list[str]:
        """Load analyst list from watchlist or fall back to all four."""
        try:
            wl = load_watchlist(self.config["watchlist_path"])
            return wl.get("analysts", ["market", "social", "news", "fundamentals"])
        except Exception:
            return ["market", "social", "news", "fundamentals"]

    def _make_narrative_llm(self) -> Any:
        try:
            client = create_llm_client(
                provider=self.config["llm_provider"],
                model=self.config["deep_think_llm"],
                base_url=self.config.get("backend_url"),
            )
            return client.get_llm()
        except Exception as exc:
            logger.warning("Could not create narrative LLM: %s", exc)
            return None

    def _write_errors(self, errors: list[dict], out_dir: Path) -> None:
        lines = ["# Errors", "", "| Ticker | Error |", "|--------|-------|"]
        for r in errors:
            lines.append(f"| {r['ticker']} | {r['error'][:300]} |")
        (out_dir / "errors.md").write_text("\n".join(lines), encoding="utf-8")
