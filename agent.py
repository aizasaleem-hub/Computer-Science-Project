from __future__ import annotations

from openai import OpenAI

from rag import retrieve, format_context

client = OpenAI()


def analyze_report(report_text: str) -> str:
    """Review a report against the Constitution and suggest improvements."""
    # Use a trimmed version for retrieval to avoid exceeding embedding limits
    retrieval_text = report_text[:6000]

    context_docs = retrieve(retrieval_text, k=6)
    context = format_context(context_docs)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a constitutional policy reviewer.\n"
                "Using ONLY the provided excerpts from the Constitution of Pakistan (1973), "
                "assess the user's report. Identify gaps, conflicts, or weak reasoning, then "
                "propose concrete improvements that make the report unambiguous and persuasive.\n"
                "Be concise, specific, and tie every critique to constitutional grounding.\n"
                "Structure the response as:\n"
                "1) Brief overview of the report (2 sentences max).\n"
                "2) Weaknesses (bulleted): each item names the issue, why it matters, and the relevant article/page.\n"
                "3) Improvement suggestions (bulleted): actionable changes tied to the weaknesses with clear reasons.\n"
                "If the provided context lacks coverage for a claim, state that limitation explicitly."
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
    )

    return resp.choices[0].message.content.strip()
