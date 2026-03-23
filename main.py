from __future__ import annotations

import json
from io import BytesIO
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pypdf import PdfReader
from docx import Document

from agent import analyze_report, refine_report
from auth import (
    ConversationMessageOut,
    ConversationOut,
    UserCreate,
    UserLogin,
    UserOut,
    Token,
    append_conversation_message,
    create_access_token,
    create_conversation,
    authenticate_user,
    create_user,
    get_db,
    get_current_active_user,
    get_conversation_for_user,
    get_recent_user_memory,
    list_conversation_messages,
    list_conversations,
    create_db,
)
from sqlalchemy.orm import Session

app = FastAPI(title="Report Reviewer", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


class Weakness(BaseModel):
    id: str
    issue: str
    why_it_matters: str
    suggestion: str
    citation: Optional[str] = None


class AnalysisResponse(BaseModel):
    conversation_id: int
    overview: str
    weaknesses: List[Weakness]
    normalized_report: str


class SelectedChange(BaseModel):
    id: str
    suggestion: str
    issue: Optional[str] = None


class RefineRequest(BaseModel):
    conversation_id: Optional[int] = None
    report: str
    selected_changes: List[SelectedChange]


class RefineResponse(BaseModel):
    conversation_id: int
    refined_report: str


class ConversationCreate(BaseModel):
    title: Optional[str] = None


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    messages: List[ConversationMessageOut]


@app.on_event("startup")
def _init_db():
    create_db()


@app.get("/")
def health():
    return {"status": "ok", "message": "Report Reviewer is running. Visit /docs"}


def _extract_text_from_upload(upload: UploadFile) -> str:
    data = upload.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    name = (upload.filename or "").lower()
    content_type = (upload.content_type or "").lower()

    def is_type(*kinds: str) -> bool:
        return any(kind in content_type for kind in kinds) or name.endswith(tuple(kinds))

    if is_type("pdf", ".pdf"):
        reader = PdfReader(BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(p.strip() for p in pages if p and p.strip())
        if not text:
            raise HTTPException(status_code=400, detail="Could not extract text from PDF.")
        return text

    if is_type("docx", ".docx", ".doc"):
        doc = Document(BytesIO(data))
        paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paras)
        if not text:
            raise HTTPException(status_code=400, detail="Could not extract text from DOC/DOCX.")
        return text

    if is_type("text", "plain", ".txt"):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1", errors="ignore")

    raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF, DOCX, or TXT.")


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(
    report: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    conversation_id: Optional[int] = Form(None),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    try:
        if not report and not file:
            raise HTTPException(status_code=400, detail="Provide report text or upload a file.")

        text_parts = []
        if report:
            cleaned = report.strip()
            if len(cleaned) < 20:
                raise HTTPException(status_code=400, detail="Report text must be at least 20 characters.")
            text_parts.append(cleaned)

        if file:
            text_parts.append(_extract_text_from_upload(file))

        combined = "\n\n".join(text_parts)
        conversation = (
            get_conversation_for_user(db, current_user, conversation_id)
            if conversation_id is not None
            else create_conversation(db, current_user, seed_text=combined)
        )
        source_parts = []
        if report and report.strip():
            source_parts.append(f"Text Input:\n{report.strip()}")
        if file:
            source_parts.append(f"Uploaded File: {file.filename or 'unnamed file'}")
        append_conversation_message(
            db,
            conversation,
            role="user",
            kind="analysis_request",
            content="\n\n".join(source_parts + [f"Combined Report:\n{combined}"]),
        )

        analysis = analyze_report(combined, memory=get_recent_user_memory(db, current_user))
        if not analysis or not analysis.get("weaknesses"):
            raise HTTPException(status_code=500, detail="No analysis generated.")
        append_conversation_message(
            db,
            conversation,
            role="assistant",
            kind="analysis_response",
            content=json.dumps(analysis, ensure_ascii=True),
        )
        return AnalysisResponse(conversation_id=conversation.id, **analysis)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {type(e).__name__}: {e}")


@app.post("/refine", response_model=RefineResponse)
async def refine(
    req: RefineRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if not req.report or not req.report.strip():
        raise HTTPException(status_code=400, detail="Report text is required.")

    conversation = (
        get_conversation_for_user(db, current_user, req.conversation_id)
        if req.conversation_id is not None
        else create_conversation(db, current_user, seed_text=req.report)
    )
    refined = refine_report(
        req.report,
        [c.model_dump() for c in req.selected_changes],
        memory=get_recent_user_memory(db, current_user),
    )
    if not refined:
        raise HTTPException(status_code=500, detail="Could not generate refined report.")
    append_conversation_message(
        db,
        conversation,
        role="user",
        kind="refine_request",
        content=json.dumps(
            {
                "report": req.report,
                "selected_changes": [c.model_dump() for c in req.selected_changes],
            },
            ensure_ascii=True,
        ),
    )
    append_conversation_message(
        db,
        conversation,
        role="assistant",
        kind="refine_response",
        content=refined,
    )
    return RefineResponse(conversation_id=conversation.id, refined_report=refined)


# -------------------------
# Auth routes
# -------------------------


@app.post("/auth/signup", response_model=UserOut, status_code=201)
def signup(user_in: UserCreate, db: Session = Depends(get_db)):
    user = create_user(db, user_in)
    return user


@app.post("/auth/login", response_model=Token)
def login(user_in: UserLogin, db: Session = Depends(get_db)):
    user = authenticate_user(db, user_in.username_or_email, user_in.password)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    token = create_access_token({"sub": user.username})
    return Token(access_token=token)


@app.get("/auth/me", response_model=UserOut)
def me(current_user=Depends(get_current_active_user)):
    return current_user


@app.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation_endpoint(
    payload: ConversationCreate,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    return create_conversation(db, current_user, title=payload.title)


@app.get("/conversations", response_model=List[ConversationOut])
def list_conversations_endpoint(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    return list_conversations(db, current_user)


@app.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation_endpoint(
    conversation_id: int,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    conversation = get_conversation_for_user(db, current_user, conversation_id)
    return ConversationDetail(
        conversation=conversation,
        messages=list_conversation_messages(db, conversation),
    )
