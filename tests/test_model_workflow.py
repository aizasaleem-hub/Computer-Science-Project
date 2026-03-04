import json

import pytest

import agent


@pytest.fixture(autouse=True)
def patch_context(monkeypatch):
    """Avoid hitting FAISS/OpenAI embeddings during tests."""
    monkeypatch.setattr(agent, "_prepare_context", lambda *_args, **_kwargs: "[context]")


@pytest.fixture
def stub_llm(monkeypatch):
    """Queue up fake LLM responses for sequential agent calls."""

    def _apply(responses):
        queue = iter(responses)

        def fake_create(*_args, **_kwargs):
            try:
                content = next(queue)
            except StopIteration:
                raise AssertionError("LLM called more times than stubbed")

            class Msg:
                def __init__(self, content):
                    self.content = content

            class Choice:
                def __init__(self, msg):
                    self.message = msg

            class Resp:
                def __init__(self, choice):
                    self.choices = [choice]

            return Resp(Choice(Msg(content)))

        monkeypatch.setattr(agent.client.chat.completions, "create", fake_create)

    return _apply


def build_analysis_json(suggestions):
    weaknesses = []
    for i, suggestion in enumerate(suggestions, start=1):
        weaknesses.append(
            {
                "id": f"W{i}",
                "issue": suggestion["issue"],
                "why_it_matters": suggestion.get("why", "Relevance to constitution"),
                "suggestion": suggestion["suggestion"],
                "citation": suggestion.get("citation"),
            }
        )
    return json.dumps({"overview": "Auto overview", "weaknesses": weaknesses})


TEST_CASES = [
    {
        "name": "Structure missing + mixed content",
        "report": "Blob paragraph mixing facts law emotions prayer.",
        "suggestions": [
            {"issue": "Structure", "suggestion": "Add standard headings"},
            {"issue": "Sequence", "suggestion": "Reorder into chronological timeline"},
            {"issue": "Issues", "suggestion": "Add issues for determination"},
            {"issue": "Relief", "suggestion": "Add relief sought numbered"},
        ],
        "selected_ids": ["W1", "W2", "W3", "W4"],
        "refined": "Clean structured report with headings, timeline, issues, numbered relief.",
    },
    {
        "name": "Facts vs allegations blended",
        "report": "They committed fraud and stole money; I think they planned it.",
        "suggestions": [
            {"issue": "Segregate assertions", "suggestion": "Split into Facts / Information / Belief / Inference"},
            {"issue": "Specifics", "suggestion": "Replace conclusory words with acts and evidence"},
            {"issue": "Unknowns", "suggestion": "Add what is unknown / needs confirmation"},
        ],
        "selected_ids": ["W1", "W2", "W3"],
        "refined": "Calibrated language with sections and explicit unknowns.",
    },
    {
        "name": "Pronoun ambiguity",
        "report": "They told him to submit it. Then they rejected it.",
        "suggestions": [
            {"issue": "Pronouns", "suggestion": "Replace pronouns with defined actors"},
            {"issue": "Roles", "suggestion": "Add parties/roles table"},
            {"issue": "Attribution", "suggestion": "Attribute each act to specific respondent"},
        ],
        "selected_ids": ["W1", "W2", "W3"],
        "refined": "Report with named actors, roles table, and clear attributions.",
    },
    {
        "name": "Vague dates",
        "report": "Last month I applied. Recently they called.",
        "suggestions": [
            {"issue": "Timeline", "suggestion": "Convert to timeline with explicit date ranges"},
            {"issue": "Numbering", "suggestion": "Add event numbering E1, E2"},
        ],
        "selected_ids": ["W1", "W2"],
        "refined": "Chronology with numbered events and explicit date placeholders.",
    },
    {
        "name": "Missing jurisdiction",
        "report": "Strong narrative but no jurisdiction basis.",
        "suggestions": [
            {"issue": "Jurisdiction", "suggestion": "Add jurisdiction and maintainability section"},
            {"issue": "State nexus", "suggestion": "Explain state-action nexus if relevant"},
            {"issue": "Alt remedy", "suggestion": "Add alternative remedy note"},
        ],
        "selected_ids": ["W1", "W2", "W3"],
        "refined": "Report now includes jurisdiction, nexus, and alternative remedy note.",
    },
    {
        "name": "Forum mismatch partial selection",
        "report": "Private contract dispute framed constitutionally.",
        "suggestions": [
            {"issue": "Maintainability risk", "suggestion": "Flag maintainability risk"},
            {"issue": "Forum", "suggestion": "Reframe to civil/consumer forum"},
            {"issue": "Constitutional link", "suggestion": "Keep constitutional refs only with nexus"},
        ],
        "selected_ids": ["W1"],  # only flag risk
        "refined": "Report keeps posture but includes clear maintainability risk note.",
    },
    {
        "name": "Relief vague",
        "report": "Take action against them and give me justice.",
        "suggestions": [
            {"issue": "Relief precision", "suggestion": "Convert relief into specific numbered prayers"},
            {"issue": "Interim", "suggestion": "Add interim relief if urgency"},
        ],
        "selected_ids": ["W1", "W2"],
        "refined": "Actionable prayer section with numbered and interim relief.",
    },
    {
        "name": "Evidence unorganized",
        "report": "I have screenshots, letters, calls.",
        "suggestions": [
            {"issue": "Annexures", "suggestion": "Create annexure list A-1, A-2"},
            {"issue": "Evidence map", "suggestion": "Add evidence-to-issue mapping table"},
            {"issue": "Authenticity", "suggestion": "Add authenticity notes for digital evidence"},
        ],
        "selected_ids": ["W1", "W2", "W3"],
        "refined": "Report with annexures referenced and evidence map.",
    },
    {
        "name": "Internal contradiction partial selection",
        "report": "No notice served. Received notice on 12 Jan.",
        "suggestions": [
            {"issue": "Contradiction", "suggestion": "Treat as inadequate notice"},
            {"issue": "Ask user", "suggestion": "Add clarification question"},
        ],
        "selected_ids": ["W1"],
        "refined": "Consistent stance: notice received but inadequate time; timeline updated.",
    },
    {
        "name": "Inflammatory language",
        "report": "These crooks are criminals and liars.",
        "suggestions": [
            {"issue": "Tone", "suggestion": "Replace emotive language with neutral drafting"},
            {"issue": "Caveats", "suggestion": "Add evidentiary caveats"},
            {"issue": "Conduct focus", "suggestion": "Remove personal attacks; focus on conduct"},
        ],
        "selected_ids": ["W1", "W2", "W3"],
        "refined": "Neutral, professional tone with caveats and conduct focus.",
    },
    {
        "name": "Over-citation",
        "report": "Article 1,2,3,4,5 all violated somehow.",
        "suggestions": [
            {"issue": "Relevance", "suggestion": "Keep only relevant Articles with explanation"},
            {"issue": "Legal basis", "suggestion": "Add legal basis paragraph per issue"},
        ],
        "selected_ids": ["W1", "W2"],
        "refined": "Tight constitutional mapping with only relevant Articles explained.",
    },
    {
        "name": "Missing anticipated defense",
        "report": "One-sided allegations.",
        "suggestions": [
            {"issue": "Defense", "suggestion": "Add anticipated response + rebuttal"},
            {"issue": "Fallback", "suggestion": "Add alternative relief"},
        ],
        "selected_ids": ["W1", "W2"],
        "refined": "Report includes anticipated defenses with rebuttals and fallback relief.",
    },
    {
        "name": "Partial selection correctness",
        "report": "Messy structure with vague dates and harsh tone.",
        "suggestions": [
            {"issue": "Structure", "suggestion": "Add standard structure"},
            {"issue": "Timeline", "suggestion": "Add precise timeline"},
            {"issue": "Tone", "suggestion": "Neutralize tone"},
        ],
        "selected_ids": ["W1", "W3"],  # skip timeline
        "refined": "Structured and neutral report; dates remain vague as provided.",
    },
    {
        "name": "Do not add facts / hallucination trap",
        "report": "Missing facts; feel free to fill gaps realistically.",
        "suggestions": [
            {"issue": "Info needed", "suggestion": "Add Information required section"},
            {"issue": "Placeholders", "suggestion": "Add placeholders for unknown data"},
        ],
        "selected_ids": ["W1"],  # no placeholders
        "refined": "Report unchanged except appended Information Required questions; no invented facts.",
    },
    {
        "name": "Multi-respondent split",
        "report": "Two agencies and one officer blamed together.",
        "suggestions": [
            {"issue": "Attribution", "suggestion": "Add respondent-wise allegations"},
            {"issue": "Relief split", "suggestion": "Add respondent-wise relief items"},
        ],
        "selected_ids": ["W1", "W2"],
        "refined": "Acts and prayers split by each respondent.",
    },
]


@pytest.mark.parametrize("case", TEST_CASES, ids=[c["name"] for c in TEST_CASES])
def test_analyze_and_refine(case, stub_llm):
    # Prepare fake analysis JSON and refined text responses
    analysis_json = build_analysis_json(case["suggestions"])
    refined_text = case["refined"]
    stub_llm([analysis_json, refined_text])

    analysis = agent.analyze_report(case["report"])
    assert analysis["normalized_report"] == case["report"].strip()
    assert len(analysis["weaknesses"]) == len(case["suggestions"])

    # Apply user-selected subset
    selected = [w for w in analysis["weaknesses"] if w["id"] in case["selected_ids"]]
    refined = agent.refine_report(case["report"], selected)

    assert refined == refined_text
