"""BatchRunner: run TradingAgentsGraph over a watchlist, one ticker at a time.

Each ticker is isolated inside its own try/except so a single failure does
not abort the batch.  Results are collected and returned as a list of dicts
that ``summary.generate_summary()`` can consume.
"""

from __future__ import annotations

import datetime
import logging
import re
from pathlib import Path
from typing import Any, Optional

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients import create_llm_client

from .watchlist import load_watchlist
from .summary import generate_summary

logger = logging.getLogger(__name__)


def _iso_week(d: datetime.date) -> str:
    """Return ISO week label like '2026-W22'."""
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _latest_trading_day(d: Optional[datetime.date] = None) -> datetime.date:
    """Return the most recent weekday on or before ``d``."""
    d = d or datetime.date.today()
    # Step back until we hit a weekday (Mon=0 … Fri=4)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


def _build_individual_report(state: dict[str, Any], ticker: str, trade_date: str) -> str:
    """Render a single ticker's full analysis as markdown."""
    sections: list[str] = [
        f"# Trading Analysis: {ticker}",
        f"",
        f"**Date:** {trade_date}  ",
        f"**Rating:** {state.get('final_trade_decision', '').splitlines()[0] if state.get('final_trade_decision') else '—'}",
        f"",
    ]

    # Analyst reports
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

    # Research team
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

    # Trader
    if state.get("trader_investment_plan"):
        sections += ["", "## III. Trader", "", state["trader_investment_plan"]]

    # Risk management
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

    # Portfolio manager final decision
    if state.get("final_trade_decision"):
        sections += [
            "",
            "## V. Portfolio Manager Decision",
            "",
            state["final_trade_decision"],
        ]

    return "\n".join(sections)


class BatchRunner:
    """Run the TradingAgents pipeline for each ticker in a watchlist.

    Args:
        config: TradingAgents configuration dict (defaults to DEFAULT_CONFIG).
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        trade_date: Optional[str] = None,
        narrative: bool = True,
        notify: bool = True,
    ) -> Path:
        """Run the full weekly batch and write reports.

        Args:
            trade_date: Analysis date as YYYY-MM-DD.  Defaults to the most
                        recent trading day.
            narrative:  Include LLM cross-ticker narrative in summary.
            notify:     Send completion notification.

        Returns:
            Path to the ``summary.md`` file that was written.
        """
        # Resolve date
        if trade_date:
            d = datetime.date.fromisoformat(trade_date)
        else:
            d = _latest_trading_day()
        trade_date_str = d.strftime("%Y-%m-%d")
        iso_week = _iso_week(d)

        # Resolve output directory
        reports_root = Path(self.config["weekly_reports_dir"]).expanduser()
        week_dir = reports_root / iso_week
        week_dir.mkdir(parents=True, exist_ok=True)

        # Load watchlist
        wl = load_watchlist(self.config["watchlist_path"])
        tickers: list[str] = wl.get("tickers", [])
        analysts: list[str] = wl.get("analysts", ["market", "social", "news", "fundamentals"])

        if not tickers:
            logger.warning("Watchlist is empty — nothing to run.")
            return week_dir / "summary.md"

        logger.info(
            "Starting weekly batch: %d tickers for %s → %s",
            len(tickers),
            trade_date_str,
            week_dir,
        )

        results: list[dict[str, Any]] = []

        for ticker in tickers:
            result = self._run_one(ticker, trade_date_str, analysts, week_dir)
            results.append(result)
            status = "OK" if not result.get("error") else f"ERROR: {result['error']}"
            logger.info("[%s] %s", ticker, status)

        # Write individual error log
        errors = [r for r in results if r.get("error")]
        if errors:
            self._write_errors(errors, week_dir)

        # Build and write summary
        llm = self._make_narrative_llm() if narrative else None
        summary_md = generate_summary(
            results=results,
            trade_date=trade_date_str,
            iso_week=iso_week,
            narrative=narrative,
            llm=llm,
        )
        summary_path = week_dir / "summary.md"
        summary_path.write_text(summary_md, encoding="utf-8")
        logger.info("Summary written → %s", summary_path)

        # Send notification
        if notify:
            self._notify(results, iso_week, trade_date_str, summary_path)

        return summary_path

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _run_one(
        self,
        ticker: str,
        trade_date: str,
        analysts: list[str],
        week_dir: Path,
    ) -> dict[str, Any]:
        """Run a single ticker; return a result dict even on failure."""
        try:
            # Enable checkpoint so a crash on this ticker can be resumed
            cfg = {**self.config, "checkpoint_enabled": True}
            graph = TradingAgentsGraph(
                selected_analysts=analysts,
                config=cfg,
            )
            final_state, rating = graph.propagate(ticker, trade_date)

            # Write individual report
            report_md = _build_individual_report(final_state, ticker, trade_date)
            report_path = week_dir / f"{ticker}.md"
            report_path.write_text(report_md, encoding="utf-8")

            return {
                "ticker": ticker,
                "date": trade_date,
                "rating": rating,
                "final_state": final_state,
                "report_path": str(report_path),
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
                "error": str(exc),
            }

    def _make_narrative_llm(self) -> Any:
        """Instantiate the deep-think LLM for narrative generation."""
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

    def _write_errors(self, errors: list[dict], week_dir: Path) -> None:
        lines = [
            "# Errors",
            "",
            "| Ticker | Error |",
            "|--------|-------|",
        ]
        for r in errors:
            lines.append(f"| {r['ticker']} | {r['error'][:300]} |")
        (week_dir / "errors.md").write_text("\n".join(lines), encoding="utf-8")

    def _notify(
        self,
        results: list[dict],
        iso_week: str,
        trade_date: str,
        summary_path: Path,
    ) -> None:
        from tradingagents.notifiers import create_notifier

        completed = [r for r in results if not r.get("error")]
        errors = [r for r in results if r.get("error")]

        # Rating counts
        counts: dict[str, list[str]] = {}
        for r in completed:
            rating = r.get("rating", "Hold")
            counts.setdefault(rating, []).append(r["ticker"])

        rating_lines = []
        emoji_map = {
            "Buy": "🟢", "Overweight": "🔵", "Hold": "⚪",
            "Underweight": "🟡", "Sell": "🔴",
        }
        for rating, tickers in counts.items():
            emoji = emoji_map.get(rating, "⚪")
            rating_lines.append(f"{emoji} {rating}: {', '.join(tickers)}")

        body_parts = [
            f"✅ {len(completed)}/{len(results)} completed",
            "",
        ] + rating_lines

        if errors:
            body_parts.append(f"\n❌ Failed: {', '.join(r['ticker'] for r in errors)}")

        notifier = create_notifier(self.config)
        notifier.send(
            title=f"📊 Weekly Analysis · {iso_week} ({trade_date})",
            body="\n".join(body_parts),
            url=str(summary_path.resolve()),
        )
