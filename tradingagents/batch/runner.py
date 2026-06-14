"""BatchRunner: run TradingAgentsGraph for one or many tickers.

Output directory structure (all relative to config["reports_root"]):
  manual/<DATE>_<TICKER>/complete_report.md   — single-stock
  batch/<DATE>/{summary.md, TICKER.md, …}    — multi-ticker batch
  scheduled/<task_name>/<DATE>/{…}           — scheduled task
"""

from __future__ import annotations

import datetime
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# ── Notification helpers ──────────────────────────────────────────────────────

def extract_reason(pm_decision: str, max_chars: int = 500) -> str:
    """Extract a concise reason from the Portfolio Manager decision text.

    Strips label-only lines (rating, 最终交易决策, 执行策略, etc.) and markdown,
    then returns substantive content up to max_chars characters, cut at the
    nearest sentence boundary (。！？) so the text doesn't end mid-sentence.
    """
    if not pm_decision:
        return ""

    import re

    # Lines that are short label-only entries — skip them
    _LABEL_RE = re.compile(
        r"^(?:rating|评级|最终交易决策|最终决策|交易决策|执行策略|标的|"
        r"action|price\s*target|time\s*horizon|recommendation|executive\s*summary|"
        r"investment\s*thesis)\s*[:：]",
        re.IGNORECASE,
    )
    # Pure separator lines (---, ===, ───, etc.)
    _SEP_RE = re.compile(r"^[-=─*#\s]{2,}$")

    lines = []
    for line in pm_decision.splitlines():
        # Remove markdown bold/header/code markers
        clean = re.sub(r"\*{1,2}|#{1,6}|`", "", line).strip()
        if not clean:
            continue
        if _SEP_RE.match(clean):
            continue
        if _LABEL_RE.match(clean) and len(clean) < 60:
            continue
        lines.append(clean)

    text = " ".join(lines)
    if len(text) <= max_chars:
        return text

    cut = text[:max_chars]
    # Prefer cutting at a Chinese/English sentence boundary
    for punct in "。！？.!?":
        idx = cut.rfind(punct)
        if idx > max_chars // 2:
            return cut[: idx + 1]
    # Fall back to word boundary
    return cut.rsplit(" ", 1)[0].rstrip("，。,") + "…"


# ── Rate-limit detection ──────────────────────────────────────────────────────

_RATE_LIMIT_KEYWORDS = (
    "429", "rate limit", "too many requests", "ratelimit",
    "rate_limit", "quota", "capacity", "overloaded",
)


def _is_rate_limit(error: str) -> bool:
    low = error.lower()
    return any(kw in low for kw in _RATE_LIMIT_KEYWORDS)


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
        on_rate_limit: Optional[Callable[[list[str], int, int, int], None]] = None,
        on_complete: Optional[Callable[[list[dict], Path], None]] = None,
    ) -> tuple[list[dict[str, Any]], Path]:
        """Analyse multiple tickers with parallel execution and auto-retry.

        Args:
            tickers:        Ticker list; defaults to watchlist when None.
            trade_date:     YYYY-MM-DD; defaults to most recent trading day.
            mode:           "batch" | "scheduled".
            task_name:      Required when mode=="scheduled".
            narrative:      Include LLM cross-ticker narrative in summary.
            on_ticker_done: Called immediately after each ticker finishes
                            (success or failure).
            on_rate_limit:  Called when rate-limiting is detected with
                            (failed_tickers, old_workers, new_workers, wait_s).
            on_complete:    Called with (results, summary_path) at the very end.

        Returns:
            (results, summary_path)
        """
        from .watchlist import format_position_context

        trade_date = _resolve_date(trade_date)
        wl = load_watchlist(self.config["watchlist_path"])
        if tickers is None:
            tickers = wl.get("tickers", [])
        positions = wl.get("positions", {})

        if not tickers:
            logger.warning("No tickers to analyse.")
            out_dir = _output_dir(self.config, mode, trade_date, task_name=task_name)
            out_dir.mkdir(parents=True, exist_ok=True)
            summary_path = out_dir / "summary.md"
            summary_path.write_text("# Batch Analysis\n\nNo tickers configured.", encoding="utf-8")
            return [], summary_path

        out_dir = _output_dir(self.config, mode, trade_date, task_name=task_name)
        out_dir.mkdir(parents=True, exist_ok=True)

        max_workers = max(1, int(self.config.get("batch_max_workers", 3)))
        max_retries = max(0, int(self.config.get("batch_max_retries", 2)))
        retry_wait  = max(1, int(self.config.get("batch_retry_wait", 30)))

        logger.info(
            "Batch start: %d tickers, workers=%d, retries=%d → %s",
            len(tickers), max_workers, max_retries, out_dir,
        )

        # ticker → latest result (updated on each attempt)
        results_map: dict[str, dict[str, Any]] = {}

        def _run_ticker(ticker: str) -> dict[str, Any]:
            position = positions.get(ticker.upper())
            ctx = format_position_context(ticker, position)
            return self._run_one(ticker, trade_date, out_dir, extra_context=ctx)

        def _fire_ticker_done(result: dict) -> None:
            status = result.get("rating", "—") if not result.get("error") else f"ERR: {result['error'][:60]}"
            logger.info("[%s] %s", result["ticker"], status)
            if on_ticker_done:
                try:
                    on_ticker_done(result)
                except Exception as exc:
                    logger.warning("on_ticker_done raised: %s", exc)

        def _run_all(batch: list[str], workers: int) -> None:
            """Run a batch of tickers at given concurrency; update results_map."""
            if workers == 1:
                for ticker in batch:
                    r = _run_ticker(ticker)
                    results_map[ticker] = r
                    _fire_ticker_done(r)
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {pool.submit(_run_ticker, t): t for t in batch}
                    for future in as_completed(futures):
                        r = future.result()
                        results_map[r["ticker"]] = r
                        _fire_ticker_done(r)

        # ── Initial run ───────────────────────────────────────────────────────
        _run_all(tickers, max_workers)

        # ── Retry loop ────────────────────────────────────────────────────────
        for attempt in range(1, max_retries + 1):
            failed = [r for r in results_map.values() if r.get("error")]
            if not failed:
                break

            rate_limited = [r for r in failed if _is_rate_limit(r.get("error", ""))]
            retry_tickers = [r["ticker"] for r in failed]

            if rate_limited:
                # Reduce concurrency and wait before retrying
                old_workers = max_workers
                max_workers = max(1, max_workers - 1)
                wait_s = retry_wait * (2 ** (attempt - 1))   # 30s → 60s

                logger.warning(
                    "Rate limit on attempt %d — workers %d→%d, waiting %ds, retrying: %s",
                    attempt, old_workers, max_workers, wait_s,
                    ", ".join(r["ticker"] for r in rate_limited),
                )
                if on_rate_limit:
                    try:
                        on_rate_limit(
                            [r["ticker"] for r in rate_limited],
                            old_workers, max_workers, wait_s,
                        )
                    except Exception as exc:
                        logger.warning("on_rate_limit raised: %s", exc)
                time.sleep(wait_s)
            else:
                # Non-rate-limit failure: short pause then retry
                logger.info(
                    "Retry attempt %d/%d (non-rate-limit) for: %s",
                    attempt, max_retries, ", ".join(retry_tickers),
                )
                time.sleep(5)

            _run_all(retry_tickers, max_workers)

        # ── Finalise ──────────────────────────────────────────────────────────
        results = list(results_map.values())
        errors = [r for r in results if r.get("error")]
        if errors:
            self._write_errors(errors, out_dir)

        llm = self._make_narrative_llm() if narrative else None
        iso = datetime.date.fromisoformat(trade_date).isocalendar()
        iso_label = f"{iso[0]}-W{iso[1]:02d}"
        summary_md = generate_summary(
            results=results, trade_date=trade_date,
            iso_week=iso_label, narrative=narrative, llm=llm,
        )
        summary_path = out_dir / "summary.md"
        summary_path.write_text(summary_md, encoding="utf-8")
        logger.info("Summary written → %s", summary_path)

        if on_complete:
            try:
                on_complete(results, summary_path)
            except Exception as exc:
                logger.warning("on_complete raised: %s", exc)

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
