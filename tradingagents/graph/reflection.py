# TradingAgents/graph/reflection.py

from typing import Any


class Reflector:
    """Handles reflection on trading decisions."""

    def __init__(self, quick_thinking_llm: Any):
        """Initialize the reflector with an LLM."""
        self.quick_thinking_llm = quick_thinking_llm
        self.log_reflection_prompt = self._get_log_reflection_prompt()

    def _get_log_reflection_prompt(self) -> str:
        """Concise prompt for reflect_on_final_decision (Phase B log entries).

        Produces 2-4 sentences of plain prose — compact enough to be re-injected
        into future agent prompts without bloating the context window.
        """
        return (
            "You are a trading analyst reviewing your own past decision now that the outcome is known.\n"
            "Write exactly 2-4 sentences of plain prose (no bullets, no headers, no markdown).\n\n"
            "Cover in order:\n"
            "1. Was the directional call correct? (cite the alpha figure)\n"
            "2. Which part of the investment thesis held or failed?\n"
            "3. One concrete lesson to apply to the next similar analysis.\n\n"
            "Be specific and terse. Your output will be stored verbatim in a decision log "
            "and re-read by future analysts, so every word must earn its place."
        )

    def reflect_on_final_decision(
        self,
        final_decision: str,
        raw_return: float,
        alpha_return: float,
    ) -> str:
        """Single reflection call on the final trade decision with outcome context.

        Used by Phase B deferred reflection. The final_trade_decision already
        synthesises all analyst insights, so no separate market context is needed.
        """
        messages = [
            ("system", self.log_reflection_prompt),
            (
                "human",
                (
                    f"Raw return: {raw_return:+.1%}\n"
                    f"Alpha vs SPY: {alpha_return:+.1%}\n\n"
                    f"Final Decision:\n{final_decision}"
                ),
            ),
        ]
        return self.quick_thinking_llm.invoke(messages).content

    def weekly_meta_reflection(
        self,
        outcomes_summary: str,
        previous_lessons: list[str],
        max_lessons: int = 5,
    ) -> list[str]:
        """One weekly LLM call: propose new cross-ticker lessons.

        Takes this week's settled outcomes and the existing lessons, returns
        at most ``max_lessons`` NEW lessons (may be empty). The caller merges
        them into the persistent pool, which handles dedupe and rotation.
        """
        prev = "\n".join(f"- {lesson}" for lesson in previous_lessons) or "(none)"
        system = (
            "You extract trading lessons for future analysts.\n"
            f"Given this week's settled outcomes and the existing lessons, output at most {max_lessons} "
            "NEW lessons as plain lines starting with '- '. Rules:\n"
            "1. Never repeat or rephrase an existing lesson.\n"
            "2. Add a lesson only when a pattern spans more than one decision — never "
            "generalize from a single outcome.\n"
            "3. Each lesson must be one concrete, actionable sentence.\n"
            "If this week's outcomes support no new lesson, output nothing.\n"
            "Output only the bullet lines, nothing else."
        )
        human = (
            f"Existing lessons:\n{prev}\n\n"
            f"This week's settled outcomes:\n{outcomes_summary}"
        )
        content = self.quick_thinking_llm.invoke(
            [("system", system), ("human", human)]
        ).content
        lessons = []
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("- "):
                lessons.append(line[2:].strip())
        return lessons[:max_lessons]
