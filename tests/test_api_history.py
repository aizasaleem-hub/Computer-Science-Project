from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from auth import Base


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_app.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(main, "create_db", lambda: Base.metadata.create_all(bind=engine))
    app = main.app
    app.dependency_overrides[main.get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def stub_model_calls(monkeypatch):
    def fake_analyze(report_text, memory=None):
        return {
            "overview": f"Review completed for {report_text[:20]}",
            "weaknesses": [
                {
                    "id": "W1",
                    "issue": "Needs structure",
                    "why_it_matters": "Improves readability",
                    "suggestion": "Add headings",
                    "citation": "Article 10",
                }
            ],
            "normalized_report": report_text.strip(),
        }

    def fake_refine(report_text, selected_changes, memory=None):
        assert selected_changes
        return f"Refined: {report_text.strip()}"

    monkeypatch.setattr(main, "analyze_report", fake_analyze)
    monkeypatch.setattr(main, "refine_report", fake_refine)


def signup_and_login(client: TestClient, username: str = "alice", email: str = "alice@example.com") -> str:
    signup = client.post(
        "/auth/signup",
        json={"username": username, "email": email, "password": "strong-password"},
    )
    assert signup.status_code == 201, signup.text

    login = client.post(
        "/auth/login",
        json={"username_or_email": email, "password": "strong-password"},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class FakePdfPage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakePdfReader:
    def __init__(self, *_args, **_kwargs):
        self.pages = [FakePdfPage("PDF extracted text for testing.")]


def test_signup_rejects_duplicate_email(client: TestClient):
    payload = {"username": "alice", "email": "alice@example.com", "password": "strong-password"}
    assert client.post("/auth/signup", json=payload).status_code == 201

    duplicate = client.post(
        "/auth/signup",
        json={"username": "alice-2", "email": "alice@example.com", "password": "strong-password"},
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "Username or email already registered"


def test_analyze_accepts_plain_text_and_persists_history(client: TestClient):
    token = signup_and_login(client)
    response = client.post(
        "/analyze",
        data={"report": "This is a constitutional report draft with enough detail to analyze."},
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["conversation_id"] > 0
    assert data["normalized_report"].startswith("This is a constitutional report")

    saved = client.get(f"/conversations/{data['conversation_id']}", headers=auth_headers(token))
    assert saved.status_code == 200
    detail = saved.json()
    assert len(detail["messages"]) == 2
    assert detail["messages"][0]["kind"] == "analysis_request"
    assert detail["messages"][1]["kind"] == "analysis_response"


def test_analyze_accepts_txt_and_docx_uploads(client: TestClient):
    token = signup_and_login(client, username="bob", email="bob@example.com")

    txt_response = client.post(
        "/analyze",
        files={"file": ("report.txt", b"Plain text upload content for testing.", "text/plain")},
        headers=auth_headers(token),
    )
    assert txt_response.status_code == 200, txt_response.text

    docx_response = client.post(
        "/analyze",
        files={
            "file": (
                "report.docx",
                create_docx_bytes("DOCX upload content for testing."),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers=auth_headers(token),
    )
    assert docx_response.status_code == 200, docx_response.text


def test_analyze_accepts_pdf_upload(client: TestClient, monkeypatch):
    token = signup_and_login(client, username="carol", email="carol@example.com")
    monkeypatch.setattr(main, "PdfReader", FakePdfReader)

    response = client.post(
        "/analyze",
        files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["normalized_report"] == "PDF extracted text for testing."


def test_history_survives_second_login_and_refine_stays_in_same_conversation(client: TestClient):
    token = signup_and_login(client, username="dina", email="dina@example.com")
    analysis = client.post(
        "/analyze",
        data={"report": "Initial report body that should be remembered later for this account."},
        headers=auth_headers(token),
    )
    assert analysis.status_code == 200, analysis.text
    conversation_id = analysis.json()["conversation_id"]

    relogin = client.post(
        "/auth/login",
        json={"username_or_email": "dina@example.com", "password": "strong-password"},
    )
    second_token = relogin.json()["access_token"]

    conversations = client.get("/conversations", headers=auth_headers(second_token))
    assert conversations.status_code == 200
    listed_ids = [item["id"] for item in conversations.json()]
    assert conversation_id in listed_ids

    refine = client.post(
        "/refine",
        json={
            "conversation_id": conversation_id,
            "report": analysis.json()["normalized_report"],
            "selected_changes": [
                {
                    "id": "W1",
                    "issue": "Needs structure",
                    "suggestion": "Add headings",
                }
            ],
        },
        headers=auth_headers(second_token),
    )
    assert refine.status_code == 200, refine.text
    assert refine.json()["conversation_id"] == conversation_id

    detail = client.get(f"/conversations/{conversation_id}", headers=auth_headers(second_token))
    assert detail.status_code == 200
    messages = detail.json()["messages"]
    assert [message["kind"] for message in messages] == [
        "analysis_request",
        "analysis_response",
        "refine_request",
        "refine_response",
    ]
