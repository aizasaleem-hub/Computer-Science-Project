from __future__ import annotations

import json
from typing import Any, Dict, List

from openai import OpenAI

from rag import retrieve, format_context

client = OpenAI()


def _prepare_context(report_text: str, k: int = 6) -> str:
    """Retrieve and format constitutional excerpts for grounding."""
    retrieval_text = report_text[:6000]
    context_docs = retrieve(retrieval_text, k=k)
    return format_context(context_docs)


def analyze_report(report_text: str) -> Dict[str, Any]:
    """
    Review a report, identify weaknesses, and return structured suggestions.

    Returns a dict: {overview, weaknesses, normalized_report}
    """
    context = _prepare_context(report_text)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a constitutional policy reviewer.\n"
                "Using ONLY the provided excerpts from the Constitution of Pakistan (1973), "
                "assess the user's report. Identify gaps, conflicts, or weak reasoning, then "
                "propose concrete, actionable changes.\n"
                "Return strict JSON with keys: overview (string, <= 2 sentences), "
                "weaknesses (array of objects with fields: id, issue, why_it_matters, "
                "suggestion, citation).\n"
                "Rules:\n"
                "- id must be short and stable (e.g., W1, W2...).\n"
                "- Every suggestion must be tied to the cited article/page from context; if not available, set citation to null and say 'Context gap'.\n"
                "- Be concise; avoid redundancy."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Report to review:\n{report_text[:8000]}\n\n"
                f"Reference context from the Constitution:\n{context or '[no matching context found]'}"
            ),
        },
    ]

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    raw = resp.choices[0].message.content
    data = json.loads(raw)

    # Minimal validation/sanitization
    overview = data.get("overview", "").strip()
    weaknesses = data.get("weaknesses") or []
    if not isinstance(weaknesses, list):
        weaknesses = []

    for i, item in enumerate(weaknesses, start=1):
        item.setdefault("id", f"W{i}")
        item["issue"] = (item.get("issue") or "").strip()
        item["why_it_matters"] = (item.get("why_it_matters") or "").strip()
        item["suggestion"] = (item.get("suggestion") or "").strip()
        citation = item.get("citation")
        item["citation"] = citation.strip() if isinstance(citation, str) else None

    return {
        "overview": overview,
        "weaknesses": weaknesses,
        "normalized_report": report_text.strip(),
    }


def refine_report(report_text: str, selected_changes: List[Dict[str, str]]) -> str:
    """
    Rewrite the report applying ONLY the user-approved changes.
    selected_changes: list of dicts with at least 'id' and 'suggestion'; may include 'issue'.
    """
    if not selected_changes:
        return report_text.strip()

    context = _prepare_context(report_text)
    changes_text = "\n".join(
        f"- {c.get('id','')} {c.get('issue','')}: {c.get('suggestion','')}"
        for c in selected_changes
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a constitutional policy editor.\n"
                "Rewrite the report by incorporating ONLY the user-approved changes listed below. "
                "Keep all other content, intent, and structure intact where possible. "
                "Ensure every applied change is aligned with the provided constitutional context. "
                "Do not add new arguments beyond the approved changes. "
                "Return only the refined report text, nothing else."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Original report:\n{report_text[:8000]}\n\n"
                f"Approved changes to apply:\n{changes_text}\n\n"
                f"Reference context:\n{context or '[no matching context found]'}"
            ),
        },
    ]

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.2,
    )

    return resp.choices[0].message.content.strip()
