"""Optional LLM provider abstraction for business insight generation."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError

from app.schemas.business_insights import BusinessInsightResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a retail operations manager writing a daily store performance note.\n\n"
    "Use only the analytics provided.\n\n"
    "Never invent metrics.\n\n"
    "Never fabricate numbers.\n\n"
    "Write executive-friendly insights that sound like a real store manager report.\n\n"
    "STYLE RULES (IMPORTANT):\n"
    "- Do NOT repeat KPI card numbers already visible elsewhere.\n"
    "- Avoid raw decimals (e.g., 0.5143, 77.7, 100.0). Prefer plain-language interpretation.\n"
    "- It is OK to reference issues qualitatively (e.g., 'checkout lines are building', 'conversion remains strong').\n"
    "- Mention product areas by name when they are clearly top or weak.\n"
    "- If multiple weak zones are provided, focus on the lowest-performing 3 first.\n"
    "- Do not repeat the same recommendation using different wording.\n"
    "- Each recommendation must be a distinct business action (e.g., checkout staffing, queue management, weak-zone merchandising, product visibility, customer engagement).\n"
    "- When making merchandising/engagement recommendations, explicitly reference up to the 3 weakest zones by name.\n"
    "- Recommendations must be specific, actionable, and doable today.\n"
    "- Avoid generic phrases like 'investigate' or 'monitor' unless no concrete action is possible.\n"
    "- Keep each bullet short (one sentence).\n"
    "- Avoid technical terms like API, JSON, schema, model, anomaly codes.\n\n"
    "CONTENT RULES:\n"
    "- Mention checkout actions only when checkout metrics indicate a problem.\n"
    "- Mention weak product-area actions only when analytics indicate weak engagement.\n"
    "- Prioritise actions by impact (most important first).\n\n"
    "CHECKOUT ASSESSMENT (REQUIRED):\n"
    "- Always include a short checkout assessment.\n"
    "- Base it only on checkout context: peak_queue_depth, queue_abandonment_rate, reached_checkout_count, completed_purchase_count.\n"
    "- Recommend extra billing counters only when there are clear congestion signals.\n"
    "- Do not invent checkout problems.\n"
    "- Avoid repeating exact KPI numbers already shown on the dashboard.\n\n"
    "OUTPUT REQUIREMENTS (MANDATORY):\n"
    "- Return a JSON object ONLY.\n"
    "- Do NOT include markdown.\n"
    "- Do NOT include explanations.\n"
    "- Do NOT include code fences.\n"
    "- Do NOT add any other fields.\n"
    "- Do NOT include store_id.\n"
    "- Do NOT include recommendations.\n\n"
    "Return ONLY this exact JSON schema:\n"
    "{\n"
    '  \"store_summary\": \"string\",\n'
    '  \"manager_actions\": [\"string\"],\n'
    '  \"business_risks\": [\"string\"],\n'
    '  \"positive_signals\": [\"string\"],\n'
    '  \"checkout_summary\": \"string\",\n'
    '  \"checkout_actions\": [\"string\"]\n'
    "}"
)

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def is_ai_insights_enabled() -> bool:
    """True when ENABLE_AI_INSIGHTS is set to a truthy value."""
    return os.getenv("ENABLE_AI_INSIGHTS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_llm_provider_name() -> str:
    # NOTE: empty string means "unspecified" (used for default selection when enabled).
    return os.getenv("LLM_PROVIDER", "").strip().lower()


def get_llm_model() -> str:
    return os.getenv("LLM_MODEL", "").strip()


def get_openrouter_model() -> str:
    return os.getenv("OPENROUTER_MODEL", "").strip()


def get_groq_model() -> str:
    return os.getenv("GROQ_MODEL", "").strip()


def get_llm_timeout_seconds() -> float:
    raw = os.getenv("LLM_TIMEOUT_SECONDS", "15").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 15.0


def get_llm_base_url(provider: str) -> str:
    explicit = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    if provider == "ollama":
        return "http://localhost:11434"
    if provider == "openai_compatible":
        return "http://localhost:8000/v1"
    if provider == "openrouter":
        return "https://openrouter.ai/api/v1"
    if provider == "groq":
        return "https://api.groq.com/openai/v1"
    return ""


def get_provider_api_key(provider: str) -> str:
    if provider == "openrouter":
        return os.getenv("OPENROUTER_API_KEY", "").strip()
    if provider == "groq":
        return os.getenv("GROQ_API_KEY", "").strip()
    return os.getenv("LLM_API_KEY", "").strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = _JSON_OBJECT_PATTERN.search(stripped)
    if match is None:
        raise ValueError("No JSON object found in LLM response")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON must be an object")
    return parsed


def _should_log_prompts() -> bool:
    """
    Development-only prompt logging (never logs API keys).

    Enable with LLM_DEBUG_PROMPTS=true or ENV in {dev,development,demo}.
    """
    if os.getenv("LLM_DEBUG_PROMPTS", "false").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    env = os.getenv("ENV", "").strip().lower()
    return env in {"dev", "development", "demo"}


def _normalize_action_text(text: str) -> str:
    """Normalize action strings for near-duplicate detection (no external deps)."""
    s = (text or "").strip().lower()
    if not s:
        return ""
    # unify common synonyms/phrases (semantic dedupe)
    replacements = {
        # checkout lane/counter concepts
        "billing lane": "checkout lane",
        "billing counter": "checkout lane",
        "billing counters": "checkout lane",
        "billing desk": "checkout lane",
        "checkout counter": "checkout lane",
        "checkout counters": "checkout lane",
        "cashier lane": "checkout lane",
        "cashier lanes": "checkout lane",
        "cashier counter": "checkout lane",
        # staffing concepts
        "add staff": "add staff",
        "deploy staff": "add staff",
        "assign staff": "add staff",
        "add a staff member": "add staff",
        "deploy a staff member": "add staff",
        "assign a floater": "add staff",
        "floater": "staff",
        # time window concepts
        "during busy periods": "during peak periods",
        "during busy hours": "during peak periods",
        "during rush periods": "during peak periods",
        "busy periods": "peak periods",
        "busy hours": "peak periods",
        "rush periods": "peak periods",
        # wording minimization
        "additional": "extra",
        "another": "extra",
        "open a": "open",
        "open an": "open",
        # outcome concepts
        "reduce congestion": "reduce wait",
        "reduce long queues": "reduce wait",
        "reduce queues": "reduce wait",
        "reduce queue delays": "reduce wait",
        "reduce wait times": "reduce wait",
        "reduce waiting time": "reduce wait",
        "cut wait times": "reduce wait",
        "shorten waits": "reduce wait",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    # strip punctuation
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _dedupe_actions(items: list[str]) -> list[str]:
    """Case-insensitive + near-identical dedupe while preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        norm = _normalize_action_text(item)
        if not norm:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        out.append(item.strip())
    return out


def _action_theme(text: str) -> str:
    """
    Coarse action theme classification for diversity.

    Themes:
      - additional staffing
      - queue management
      - express checkout
      - customer guidance/signage
      - process optimization
      - other
    """
    s = _normalize_action_text(text)
    if not s:
        return "other"

    if any(k in s for k in ("express checkout", "express lane", "fast lane", "small baskets")):
        return "express checkout"
    if any(k in s for k in ("signage", "signs", "guide", "direct", "wayfinding")):
        return "customer guidance/signage"
    if any(k in s for k in ("prestage", "pre stage", "scan", "billing speed", "speed up", "process", "workflow", "bags", "price checks")):
        return "process optimization"
    if any(k in s for k in ("queue", "line", "crowd", "flow", "manage queues", "queue management")):
        return "queue management"
    if any(k in s for k in ("add staff", "staff", "cashier", "staffing", "redeploy")):
        return "additional staffing"
    if "checkout lane" in s or "open" in s and "lane" in s:
        return "queue management"
    return "other"


def _dedupe_and_diversify_actions(
    *,
    items: list[str],
    min_items: int,
    max_items: int,
    deterministic_supplier: callable[[], list[str]],
    debug_label: str,
) -> tuple[list[str], bool]:
    """
    2-pass cleanup:
    - pass 1: semantic normalization dedupe
    - pass 2: keep diverse themes when possible
    - pad with deterministic actions from missing themes if needed
    """
    did_repair = False
    before = [str(x).strip() for x in items if str(x).strip()]

    # pass 1: semantic dedupe
    deduped = _dedupe_actions(before)
    if len(deduped) != len(before):
        did_repair = True

    # pass 2: theme diversity
    themed_out: list[str] = []
    seen_themes: set[str] = set()
    for item in deduped:
        theme = _action_theme(item)
        if theme not in seen_themes:
            themed_out.append(item)
            seen_themes.add(theme)
        else:
            # allow extras if we still have room and they are not near-identical
            themed_out.append(item)
        if len(themed_out) >= max_items:
            break

    # If we have too many of the same theme early, compact to distinct themes first.
    compact: list[str] = []
    compact_seen: set[str] = set()
    for item in themed_out:
        theme = _action_theme(item)
        if theme in compact_seen:
            continue
        compact.append(item)
        compact_seen.add(theme)
        if len(compact) >= max_items:
            break
    if compact:
        themed_out = compact
        if len(themed_out) != len(deduped):
            did_repair = True

    # pad if needed (try to introduce missing themes)
    if len(themed_out) < min_items:
        did_repair = True
        for suggestion in deterministic_supplier():
            if len(themed_out) >= min_items:
                break
            theme = _action_theme(suggestion)
            if theme in {_action_theme(x) for x in themed_out}:
                continue
            themed_out.append(suggestion)

    # Second pass: allow duplicate themes but not duplicate text (Groq often returns [])
    if len(themed_out) < min_items:
        did_repair = True
        seen_norm = {_normalize_action_text(x) for x in themed_out}
        for suggestion in deterministic_supplier():
            if len(themed_out) >= min_items:
                break
            norm = _normalize_action_text(suggestion)
            if norm in seen_norm:
                continue
            themed_out.append(suggestion)
            seen_norm.add(norm)

    # Guaranteed schema minimum (e.g. manager_actions need 3)
    if len(themed_out) < min_items:
        did_repair = True
        for filler in (
            "Review staffing during peak hours to keep service levels high.",
            "Ensure high-traffic brand areas are clearly signed and well stocked.",
            "Monitor checkout lines and adjust lanes when queues build up.",
        ):
            if len(themed_out) >= min_items:
                break
            themed_out.append(filler)

    # final cap and final dedupe
    themed_out = _dedupe_actions(themed_out)[:max_items]

    # debug logs
    logger.info("%s before dedupe: %s", debug_label, before)
    logger.info(
        "%s normalized keys: %s",
        debug_label,
        [_normalize_action_text(x) for x in before],
    )
    logger.info("%s after dedupe: %s", debug_label, themed_out)

    return themed_out, did_repair


def _repair_common_model_shapes(
    *,
    parsed: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """
    Lightweight repair for common non-conforming payloads.

    Keeps endpoint behavior unchanged: callers still validate with Pydantic and
    fall back on failure. This only increases the chance of a valid payload.
    """
    if "recommendations" in parsed and "manager_actions" not in parsed:
        recs = parsed.get("recommendations", [])
        if not isinstance(recs, list):
            recs = []
        actions = [str(item).strip() for item in recs if str(item).strip()]

        store_summary = str(parsed.get("store_summary") or "").strip()
        if not store_summary:
            visitors = context.get("visitors")
            converted = (context.get("funnel") or {}).get("converted")
            conversion_rate = context.get("conversion_rate")
            revenue = context.get("revenue")
            parts: list[str] = []
            if isinstance(visitors, int) and isinstance(converted, int) and isinstance(conversion_rate, (int, float)):
                parts.append(
                    f"{visitors} customers visited and {converted} completed a purchase ({float(conversion_rate) * 100:.1f}% conversion)."
                )
            if isinstance(revenue, (int, float)) and float(revenue) > 0:
                parts.append(f"Total sales reached ₹{float(revenue):,.0f} for the day.")
            store_summary = " ".join(parts[:2]).strip() or "Store activity was recorded for the selected day."

        # Ensure we meet schema min lengths after repair (schema requires 1–3 for risks/positives).
        business_risks = parsed.get("business_risks") if isinstance(parsed.get("business_risks"), list) else []
        positive_signals = parsed.get("positive_signals") if isinstance(parsed.get("positive_signals"), list) else []
        if not business_risks:
            business_risks = ["No major operational risks flagged from the provided analytics context."]
        if not positive_signals:
            positive_signals = ["Core store analytics are available for this trading day."]
        # Ensure actions are 3–5 items.
        while len(actions) < 3:
            actions.append("Review checkout staffing during peak hours.")
        actions = actions[:5]

        return {
            "store_summary": store_summary,
            "manager_actions": actions,
            "business_risks": business_risks[:3],
            "positive_signals": positive_signals[:3],
            "checkout_summary": "Checkout performance was recorded for the selected day.",
            "checkout_actions": [
                "Keep checkout staffing aligned with customer traffic.",
                "Step in quickly when lines start building.",
            ],
        }

    return parsed


def _deterministic_action_suggestions(context: dict[str, Any]) -> list[str]:
    checkout = context.get("checkout") or {}
    queue_depth = checkout.get("queue_depth")
    queue_abandonment_rate = checkout.get("queue_abandonment_rate")
    weak_zone = None
    weak_zones = context.get("weak_zones") or []
    if isinstance(weak_zones, list) and weak_zones:
        candidate = weak_zones[0]
        if isinstance(candidate, dict):
            weak_zone = candidate.get("zone")

    suggestions: list[str] = []
    if isinstance(queue_depth, int) and queue_depth >= 3:
        suggestions.append("Open an additional checkout lane during peak periods to reduce wait times.")
    if isinstance(queue_abandonment_rate, (int, float)) and float(queue_abandonment_rate) >= 0.15:
        suggestions.append("Add a floater near billing to keep the line moving and prevent walk-aways.")
    if weak_zone:
        suggestions.append(f"Refresh the display and signage in {str(weak_zone).replace('_', ' ').title()} to lift engagement.")
    suggestions.extend(
        [
            "Review checkout staffing during busy periods.",
            "Keep the main path to billing clear and easy to follow.",
            "Place a quick impulse display near checkout to capture last-minute add-ons.",
        ]
    )

    # Deduplicate while preserving order.
    unique: list[str] = []
    seen: set[str] = set()
    for item in suggestions:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


def _deterministic_checkout_actions(context: dict[str, Any]) -> list[str]:
    checkout = context.get("checkout") or {}
    peak = checkout.get("peak_queue_depth") or checkout.get("queue_depth") or 0
    abandon = checkout.get("queue_abandonment_rate") or 0.0

    actions: list[str] = []
    if isinstance(peak, int) and peak >= 4:
        actions.append("Open an additional billing lane during peak periods to reduce wait times.")
    if isinstance(abandon, (int, float)) and float(abandon) >= 0.15:
        actions.append("Assign a floater at checkout to keep the line moving and prevent walk-aways.")
    actions.extend(
        [
            "Keep checkout staffing aligned with customer traffic patterns.",
            "Pre-stage bags and common items to speed up billing during rush windows.",
            "Introduce an express checkout option for small baskets during rush windows.",
            "Add clear signs from busy aisles to checkout to reduce last-minute confusion.",
        ]
    )

    unique: list[str] = []
    seen: set[str] = set()
    for item in actions:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


def _deterministic_checkout_summary(context: dict[str, Any]) -> str:
    checkout = context.get("checkout") or {}
    peak = checkout.get("peak_queue_depth") or 0
    abandon = checkout.get("queue_abandonment_rate") or 0.0
    reached = checkout.get("reached_checkout_count") or 0
    completed = checkout.get("completed_purchase_count") or 0
    lost = 0
    try:
        lost = max(0, int(reached) - int(completed))
    except Exception:
        lost = 0

    # Avoid decimals and avoid repeating KPI-style numbers unless needed.
    if isinstance(peak, int) and peak >= 6:
        base = "Checkout demand was elevated during busy periods and lines built up."
    elif isinstance(peak, int) and peak >= 4:
        base = "Checkout demand increased during busy periods and queues formed."
    else:
        base = "Checkout flow stayed manageable for most of the day."

    if isinstance(abandon, (int, float)) and float(abandon) >= 0.15:
        tail = "Some customers left the line before paying, so reducing wait time should be a priority."
        return f"{base} {tail}"

    if lost > 0:
        return f"{base} A small number of customers reached checkout but did not complete a purchase."

    return f"{base} Most customers who reached checkout completed their purchase."


def _force_minimum_insight_lists(
    parsed: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Last-resort padding so BusinessInsightResponse validation succeeds."""
    out = dict(parsed)
    actions = out.get("manager_actions")
    if not isinstance(actions, list):
        actions = []
    actions = [str(x).strip() for x in actions if str(x).strip()]
    for suggestion in _deterministic_action_suggestions(context):
        if len(actions) >= 3:
            break
        if suggestion not in actions:
            actions.append(suggestion)
    while len(actions) < 3:
        actions.append("Review store operations and adjust staffing for peak periods.")
    out["manager_actions"] = actions[:5]

    checkout_actions = out.get("checkout_actions")
    if not isinstance(checkout_actions, list):
        checkout_actions = []
    checkout_actions = [str(x).strip() for x in checkout_actions if str(x).strip()]
    for suggestion in _deterministic_checkout_actions(context):
        if len(checkout_actions) >= 2:
            break
        if suggestion not in checkout_actions:
            checkout_actions.append(suggestion)
    while len(checkout_actions) < 2:
        checkout_actions.append("Keep checkout staffing aligned with customer traffic patterns.")
    out["checkout_actions"] = checkout_actions[:4]

    if not str(out.get("store_summary") or "").strip():
        out["store_summary"] = "Store activity was recorded for the selected trading day."
    if not str(out.get("checkout_summary") or "").strip():
        out["checkout_summary"] = _deterministic_checkout_summary(context)

    risks = out.get("business_risks")
    if not isinstance(risks, list) or not risks:
        out["business_risks"] = [
            "Checkout wait times may increase during peak periods if lines build up."
        ]
    positives = out.get("positive_signals")
    if not isinstance(positives, list) or not positives:
        out["positive_signals"] = [
            "Customer traffic and engagement signals are present for the selected day."
        ]
    return out


def _normalize_insight_payload_for_schema(
    *,
    parsed: dict[str, Any],
    context: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """
    Pad list lengths to avoid fallback on minor formatting mistakes.

    Returns (normalized_payload, did_repair).
    """
    did_repair = False

    actions = parsed.get("manager_actions")
    if not isinstance(actions, list):
        actions = []
        did_repair = True
    actions = [str(item).strip() for item in actions if str(item).strip()]

    risks = parsed.get("business_risks")
    if not isinstance(risks, list):
        risks = []
        did_repair = True
    risks = [str(item).strip() for item in risks if str(item).strip()]

    positives = parsed.get("positive_signals")
    if not isinstance(positives, list):
        positives = []
        did_repair = True
    positives = [str(item).strip() for item in positives if str(item).strip()]

    checkout_summary = parsed.get("checkout_summary")
    if not isinstance(checkout_summary, str) or not checkout_summary.strip():
        checkout_summary = _deterministic_checkout_summary(context)
        did_repair = True
    checkout_summary = checkout_summary.strip()

    checkout_actions = parsed.get("checkout_actions")
    if not isinstance(checkout_actions, list):
        checkout_actions = []
        did_repair = True
    checkout_actions = [
        str(item).strip() for item in checkout_actions if str(item).strip()
    ]

    # Semantic dedupe + theme diversity
    actions, repaired_actions = _dedupe_and_diversify_actions(
        items=actions,
        min_items=3,
        max_items=5,
        deterministic_supplier=lambda: _deterministic_action_suggestions(context),
        debug_label="Manager actions",
    )
    if repaired_actions:
        did_repair = True

    checkout_actions, repaired_checkout = _dedupe_and_diversify_actions(
        items=checkout_actions,
        min_items=2,
        max_items=4,
        deterministic_supplier=lambda: _deterministic_checkout_actions(context),
        debug_label="Checkout actions",
    )
    if repaired_checkout:
        did_repair = True

    if not risks:
        did_repair = True
        risks = ["Checkout wait times may increase during peak periods if lines build up."]

    if not positives:
        did_repair = True
        positives = ["Customer traffic and engagement signals are present for the selected day."]

    # Enforce max caps before validation (schema caps: actions 5, risks 3, positives 3).
    actions = actions[:5]
    risks = risks[:3]
    positives = positives[:3]

    # checkout_actions already padded/diversified above

    normalized = dict(parsed)
    normalized["manager_actions"] = actions
    normalized["business_risks"] = risks
    normalized["positive_signals"] = positives
    normalized["checkout_summary"] = checkout_summary
    normalized["checkout_actions"] = checkout_actions
    return normalized, did_repair


class LLMProvider(ABC):
    """Generate validated business insights from a compact analytics context."""

    @abstractmethod
    def generate_insights(self, context: dict[str, Any]) -> BusinessInsightResponse | None:
        """Return validated insights or None when generation fails."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for safe logging."""


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def generate_insights(self, context: dict[str, Any]) -> BusinessInsightResponse | None:
        if not self._model:
            logger.warning("Ollama provider skipped: LLM_MODEL is not set")
            return None

        user_message = (
            "Analyze the following store analytics context and return JSON only:\n"
            f"{json.dumps(context, separators=(',', ':'))}"
        )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "format": "json",
        }

        try:
            started = time.perf_counter()
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(f"{self._base_url}/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
            content = body.get("message", {}).get("content", "")
            if not content:
                raise ValueError("Ollama returned empty content")
            parsed = _extract_json_object(content)
            validated = BusinessInsightResponse.model_validate(parsed)
            duration_ms = (time.perf_counter() - started) * 1000.0
            logger.info(
                "LLM provider success provider=%s duration_ms=%.2f",
                self.name,
                duration_ms,
            )
            return validated
        except Exception:
            logger.exception("Ollama insight generation failed")
            return None

    @property
    def name(self) -> str:
        return "ollama"


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def generate_insights(self, context: dict[str, Any]) -> BusinessInsightResponse | None:
        if not self._model:
            logger.warning("OpenAI-compatible provider skipped: LLM_MODEL is not set")
            return None

        user_message = (
            "Analyze the following store analytics context and return JSON only:\n"
            f"{json.dumps(context, separators=(',', ':'))}"
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "response_format": {"type": "json_object"},
        }

        try:
            started = time.perf_counter()
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
            choices = body.get("choices") or []
            if not choices:
                raise ValueError("OpenAI-compatible response missing choices")
            content = choices[0].get("message", {}).get("content", "")
            if not content:
                raise ValueError("OpenAI-compatible response returned empty content")
            parsed = _extract_json_object(content)
            validated = BusinessInsightResponse.model_validate(parsed)
            duration_ms = (time.perf_counter() - started) * 1000.0
            logger.info(
                "LLM provider success provider=%s duration_ms=%.2f",
                self.name,
                duration_ms,
            )
            return validated
        except Exception:
            logger.exception("OpenAI-compatible insight generation failed")
            return None

    @property
    def name(self) -> str:
        return "openai_compatible"


class OpenRouterProvider(LLMProvider):
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def generate_insights(self, context: dict[str, Any]) -> BusinessInsightResponse | None:
        if not self._model:
            logger.warning("OpenRouter provider skipped: OPENROUTER_MODEL is not set")
            return None
        if not self._api_key:
            logger.warning("OpenRouter provider skipped: OPENROUTER_API_KEY is not set")
            return None

        user_message = (
            "Analyze the following store analytics context and return JSON only:\n"
            f"{json.dumps(context, separators=(',', ':'))}"
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            started = time.perf_counter()
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                body = response.json()
            choices = body.get("choices") or []
            if not choices:
                raise ValueError("OpenRouter response missing choices")
            content = choices[0].get("message", {}).get("content", "")
            if not content:
                raise ValueError("OpenRouter response returned empty content")
            parsed = _extract_json_object(content)
            validated = BusinessInsightResponse.model_validate(parsed)
            duration_ms = (time.perf_counter() - started) * 1000.0
            logger.info(
                "LLM provider success provider=%s duration_ms=%.2f",
                self.name,
                duration_ms,
            )
            return validated
        except Exception:
            logger.exception("OpenRouter insight generation failed")
            return None

    @property
    def name(self) -> str:
        return "openrouter"


class GroqProvider(LLMProvider):
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def generate_insights(self, context: dict[str, Any]) -> BusinessInsightResponse | None:
        if not self._model:
            logger.warning("Groq provider skipped: GROQ_MODEL is not set")
            return None
        if not self._api_key:
            logger.warning("Groq provider skipped: GROQ_API_KEY is not set")
            return None

        user_message = (
            "Analyze the following store analytics context:\n"
            f"{json.dumps(context, separators=(',', ':'))}"
        )
        schema_instruction = (
            "Return a JSON object matching exactly this schema (and nothing else):\n"
            "{\n"
            '  "store_summary": "...",\n'
            '  "manager_actions": ["..."],\n'
            '  "business_risks": ["..."],\n'
            '  "positive_signals": ["..."],\n'
            '  "checkout_summary": "...",\n'
            '  "checkout_actions": ["..."]\n'
            "}\n"
            "Rules:\n"
            "- Do not add any other fields.\n"
            "- Do not include store_id.\n"
            "- Do not include recommendations.\n"
            "- Do not include markdown, explanations, or code fences.\n"
            "- Return JSON object only.\n"
            "\nQuality bar:\n"
            "- Avoid raw decimal metrics; use qualitative language.\n"
            "- Do not restate KPI card numbers.\n"
            "- Make actions concrete (e.g., 'open an additional checkout lane during peak periods').\n"
            "- If multiple weak zones are provided, prioritise the lowest-performing 3.\n"
            "- Include a dedicated checkout assessment based on the checkout context.\n"
            "- Keep it concise.\n"
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
                {"role": "user", "content": schema_instruction},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        response_text = ""
        content = ""
        try:
            if _should_log_prompts():
                logger.info(
                    "Groq prompt messages: %s",
                    json.dumps(payload.get("messages", []), ensure_ascii=False),
                )

            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                response_text = response.text or ""

            # Temporary debug: log raw provider response before any parsing/validation.
            logger.info("Groq raw response: %s", response_text)

            try:
                body = json.loads(response_text) if response_text else {}
            except json.JSONDecodeError:
                logger.exception(
                    "Groq JSON parsing failed (response body is not valid JSON). raw=%s",
                    response_text,
                )
                return None

            choices = body.get("choices") or []
            if not choices:
                raise ValueError("Groq response missing choices")
            content = choices[0].get("message", {}).get("content", "") or ""
            if not content:
                raise ValueError("Groq response returned empty content")

            # Required: log extracted model content before validation.
            logger.info("Groq extracted model content: %s", content)

            try:
                parsed = _extract_json_object(content)
            except Exception:
                logger.exception(
                    "Groq model output JSON extraction failed. raw_model_output=%s",
                    content,
                )
                return None

            # Lightweight repair for common mismatch: {"recommendations": [...]}.
            parsed = _repair_common_model_shapes(parsed=parsed, context=context)

            parsed, did_repair = _normalize_insight_payload_for_schema(
                parsed=parsed,
                context=context,
            )
            if did_repair:
                logger.info("Business insights auto-repaired before validation")

            try:
                validated = BusinessInsightResponse.model_validate(parsed)
            except ValidationError as exc:
                parsed, _ = _normalize_insight_payload_for_schema(
                    parsed=_force_minimum_insight_lists(parsed, context),
                    context=context,
                )
                try:
                    validated = BusinessInsightResponse.model_validate(parsed)
                except ValidationError:
                    logger.error(
                        "Groq Pydantic validation failed errors=%s raw_model_output=%s",
                        exc.errors(),
                        content,
                    )
                    return None

            duration_ms = (time.perf_counter() - started) * 1000.0
            logger.info(
                "LLM provider success provider=%s duration_ms=%.2f",
                self.name,
                duration_ms,
            )
            return validated
        except Exception:
            logger.exception(
                "Groq insight generation failed raw_response=%s raw_model_output=%s",
                response_text,
                content,
            )
            return None

    @property
    def name(self) -> str:
        return "groq"


class DeterministicFallbackProvider(LLMProvider):
    """No-op provider — always returns None so callers use rule-based fallback."""

    def generate_insights(self, context: dict[str, Any]) -> BusinessInsightResponse | None:
        return None

    @property
    def name(self) -> str:
        return "fallback"


def build_llm_provider() -> LLMProvider:
    """Construct the configured LLM provider (never raises)."""
    if not is_ai_insights_enabled():
        return DeterministicFallbackProvider()

    provider = get_llm_provider_name()
    if not provider:
        # Development/demo default: use Groq when AI is enabled but provider is not specified.
        provider = "groq"
    if provider in {"", "fallback", "deterministic"}:
        return DeterministicFallbackProvider()

    model = get_llm_model()
    timeout_seconds = get_llm_timeout_seconds()
    base_url = get_llm_base_url(provider)

    if provider == "ollama":
        return OllamaProvider(model=model, base_url=base_url, timeout_seconds=timeout_seconds)
    if provider in {"openai_compatible", "openai", "openai-compatible"}:
        return OpenAICompatibleProvider(
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
    if provider == "openrouter":
        api_key = get_provider_api_key("openrouter")
        if not api_key:
            logger.warning("OpenRouter provider disabled: OPENROUTER_API_KEY missing; falling back")
            return DeterministicFallbackProvider()
        return OpenRouterProvider(
            model=get_openrouter_model() or model,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    if provider == "groq":
        api_key = get_provider_api_key("groq")
        if not api_key:
            logger.warning("Groq provider disabled: GROQ_API_KEY missing; falling back")
            return DeterministicFallbackProvider()
        return GroqProvider(
            model=get_groq_model() or model,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )

    logger.warning("Unknown LLM_PROVIDER=%s — using deterministic fallback", provider)
    return DeterministicFallbackProvider()


def log_ai_insights_startup() -> None:
    """
    Log AI insights configuration at startup.

    Never raises; safe in production even without credentials/internet.
    """
    try:
        enabled = is_ai_insights_enabled()
        if not enabled:
            logger.info("AI Insights: Disabled")
            logger.info("Provider: fallback")
            return

        configured = get_llm_provider_name() or "groq"
        model = ""
        if configured == "groq":
            model = get_groq_model() or get_llm_model()
        elif configured == "openrouter":
            model = get_openrouter_model() or get_llm_model()
        else:
            model = get_llm_model()

        provider = build_llm_provider()
        provider_name = getattr(provider, "name", provider.__class__.__name__)

        logger.info("AI Insights: Enabled")
        logger.info("Provider: %s", provider_name)
        if model:
            logger.info("Model: %s", model)
        else:
            logger.info("Model: (not set)")
    except Exception:
        logger.exception("Failed to log AI insights startup configuration")
