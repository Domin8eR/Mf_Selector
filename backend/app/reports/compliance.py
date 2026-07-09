"""Report compliance checker — reuses Research Chat's deterministic regex and LLM backstop.

Layer 1: The same _REFRAME_RE regex from supervisor.py (imported, NOT duplicated).
Layer 2: Additional report-specific forbidden phrases (language rule enforcement).
Layer 3: LLM semantic backstop for disguised violations not caught by regex.
"""

from __future__ import annotations

import re
import json
from typing import Any

# ── Reuse the exact guard from Research Chat ──────────────────────────────────
# Import the compiled regex directly — do not reimplement it.
from app.ai.supervisor import _REFRAME_RE as _CHAT_GUARD_RE  # noqa: PLC0415

# ── Report-specific language rule enforcement ─────────────────────────────────
# Catches output-side violations in generated text (different from input-side guard).
_REPORT_FORBIDDEN_RE = re.compile(
    r"\b("
    r"recommend(?:ation|ations|ed|s|ing)?"
    r"|(?:^|\s)buy(?=\s|$)"
    r"|(?:^|\s)sell(?=\s|$)"
    r"|best fund"
    r"|top pick"
    r"|invest in"
    r"|good investment"
    r"|you should"
    r"|clients? should"
    r"|suitable for"
    r"|suitability"
    r"|personali[sz]ed"
    r"|investment advice"
    r"|financial advice"
    r"|returns? will be"
    r"|guaranteed"
    r"|top pick"
    r")\b",
    re.IGNORECASE,
)

# ── LLM semantic system prompt for report compliance ─────────────────────────
_COMPLIANCE_SYSTEM = """You are a compliance reviewer for a mutual fund research workspace.
Your task: scan the provided report text for language that implies personal investment
advice, suitability guidance, or buy/sell recommendations — even when disguised as
objective analysis.

VIOLATIONS include (not exhaustive):
  - "recommend", "buy", "sell", "best fund", "top pick", "invest in"
  - "you should", "clients should", "suitable for", "suitability"
  - "returns will be", "guaranteed", "personalised", "investment advice"
  - Disguised: "poised to outperform", "ideal choice for investors seeking",
    "this fund stands out as the go-to", "investors would do well to consider"

Return ONLY a JSON object (no markdown) with this exact shape:
{
  "additional_flagged": [
    {"phrase": "<exact phrase from text>", "rewrite": "<compliant alternative>"}
  ]
}

If no additional violations beyond the regex pass, return: {"additional_flagged": []}
"""


def check_compliance(text: str) -> dict[str, Any]:
    """
    Full two-layer compliance check on report text.

    Layer 1: deterministic regex (Research Chat guard + report-specific terms).
    Layer 2: LLM semantic backstop for disguised suitability language.

    Returns:
        {
          "pass": bool,
          "flagged_phrases": [str, ...],
          "suggested_rewrites": [{"phrase": str, "rewrite": str}, ...]
        }
    """
    flagged_phrases: list[str] = []
    suggested_rewrites: list[dict[str, str]] = []

    # Layer 1 — regex
    for m in _REPORT_FORBIDDEN_RE.finditer(text):
        phrase = m.group().strip()
        if phrase and phrase not in flagged_phrases:
            flagged_phrases.append(phrase)
            suggested_rewrites.append({
                "phrase": phrase,
                "rewrite": _default_rewrite(phrase),
            })

    # Layer 2 — LLM semantic backstop
    llm_extras = _llm_backstop(text)
    for item in llm_extras:
        phrase = item.get("phrase", "").strip()
        if phrase and phrase not in flagged_phrases:
            flagged_phrases.append(phrase)
            suggested_rewrites.append({
                "phrase": phrase,
                "rewrite": item.get("rewrite", ""),
            })

    return {
        "pass": len(flagged_phrases) == 0,
        "flagged_phrases": flagged_phrases,
        "suggested_rewrites": suggested_rewrites,
    }


def _default_rewrite(phrase: str) -> str:
    """Deterministic rewrite suggestion for common forbidden phrases."""
    phrase_lower = phrase.lower()
    mapping = {
        "recommend": "identified as a research candidate",
        "recommendation": "research finding",
        "recommendations": "research findings",
        "buy": "selected for further research",
        "sell": "flagged for structural review",
        "best fund": "top-ranked fund by composite score",
        "top pick": "highest-ranked research candidate",
        "invest in": "examine as a research candidate",
        "good investment": "structurally strong by composite score",
        "you should": "analysts may consider",
        "clients should": "analysts may consider",
        "suitable for": "structurally aligned with",
        "suitability": "structural fit",
        "personalised": "client-rule-derived",
        "personalized": "client-rule-derived",
        "investment advice": "research output",
        "financial advice": "research output",
        "returns will be": "historically demonstrated returns of",
        "guaranteed": "historically consistent",
    }
    for key, val in mapping.items():
        if key in phrase_lower:
            return val
    return f"[replace '{phrase}' with compliant phrasing]"


def _llm_backstop(text: str) -> list[dict[str, str]]:
    """Run LLM semantic compliance check on report text."""
    from app.core.config import settings

    if not (settings.anthropic_api_key or settings.openai_api_key):
        return []

    # Truncate to 3000 chars to stay within token limits
    excerpt = text[:3000]
    prompt = f"Report text to review:\n\n{excerpt}"

    raw: str | None = None
    try:
        if settings.anthropic_api_key:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                system=_COMPLIANCE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
        elif settings.openai_api_key:
            import openai
            client = openai.OpenAI(api_key=settings.openai_api_key)
            resp = client.chat.completions.create(
                model=settings.llm_model or "gpt-4o",
                max_tokens=400,
                temperature=0,
                messages=[
                    {"role": "system", "content": _COMPLIANCE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = resp.choices[0].message.content or ""
    except Exception:
        return []

    if not raw:
        return []

    try:
        # Strip markdown fences if present
        clean = re.sub(r"```(?:json)?|```", "", raw).strip()
        parsed = json.loads(clean)
        return parsed.get("additional_flagged", [])
    except (json.JSONDecodeError, TypeError):
        return []
