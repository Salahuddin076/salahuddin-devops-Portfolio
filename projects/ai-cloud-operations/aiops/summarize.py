"""Incident summaries: a deterministic template always; an LLM layer optionally.

The template summary is produced from the ``Correlation`` object alone
(service, window, z-score, matched deploys/alerts) and needs no log text
and no LLM. It is always computed and is the result returned whenever the
LLM path is disabled (the default) or declines (the no-op provider, or any
real provider that raised/returned ``None``).

The LLM path, when enabled, is given a token budget and only ever sees
*redacted* text: raw log excerpts are passed through
``aiops.redact.redact`` before they are concatenated into the prompt, and
the prompt itself is truncated to approximate the configured token budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LLMProvider, NoOpLLMProvider
from .models import Correlation, Summary
from .redact import redact

# Rough, conservative estimate used only to size the prompt we build locally;
# real providers report their own token counts. ~4 chars/token is the usual
# rule of thumb for English text.
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class SummaryConfig:
    use_llm: bool = False
    token_budget: int = 400  # max OUTPUT tokens requested from the provider
    prompt_char_budget: int = 2000  # cap on redacted context sent in the prompt
    provider: LLMProvider = field(default_factory=NoOpLLMProvider)


def template_summary(correlation: Correlation) -> str:
    a = correlation.anomaly
    parts = [
        f"{a.service}: {a.metric} {a.observed_value:.1%} in "
        f"{a.window_start.isoformat()}Z-{a.window_end.isoformat()}Z "
        f"(baseline {a.baseline_mean:.1%} +/- {a.baseline_stddev:.1%}, z={a.z_score:.2f}, "
        f"n={a.sample_size})."
    ]
    if correlation.has_deploy:
        versions = ", ".join(f"{d.version} by {d.actor or 'unknown'}" for d in correlation.deploys)
        parts.append(f"Correlated with deploy(s): {versions}.")
    if correlation.has_alert:
        names = ", ".join(f"{al.name} ({al.severity})" for al in correlation.alerts)
        parts.append(f"Correlated with alert(s): {names}.")
    if not correlation.has_deploy and not correlation.has_alert:
        parts.append("No deploy or alert correlated in the configured time window.")
    return " ".join(parts)


def _build_prompt(correlation: Correlation, redacted_log_excerpt: str, char_budget: int) -> str:
    header = template_summary(correlation)
    instruction = (
        "Write a 2-3 sentence incident summary for an on-call engineer, given the "
        "statistics below and the (already redacted) log excerpt. Do not invent facts "
        "not present in the input."
    )
    excerpt = redacted_log_excerpt[: max(0, char_budget - len(header) - len(instruction))]
    return f"{instruction}\n\nStats: {header}\n\nLog excerpt (redacted):\n{excerpt}"


def summarize(
    correlation: Correlation,
    raw_log_excerpt: str = "",
    config: SummaryConfig = SummaryConfig(),
) -> Summary:
    template = template_summary(correlation)
    if not config.use_llm:
        return Summary(text=template, source="template", redacted_input=False)

    redacted_excerpt = redact(raw_log_excerpt)
    prompt = _build_prompt(correlation, redacted_excerpt, config.prompt_char_budget)
    llm_text = config.provider.summarize(prompt, config.token_budget)
    if not llm_text:
        # No-op provider, a provider that declined, or an empty response:
        # fall back to the template. The redaction step still ran, so the
        # guardrail is exercised even when nothing actually left the process.
        return Summary(text=template, source="template", redacted_input=True)
    return Summary(text=llm_text, source=f"llm:{config.provider.name}", redacted_input=True)
