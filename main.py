from __future__ import annotations

from io import BytesIO
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pypdf import PdfReader
from docx import Document

from agent import analyze_report, refine_report
from auth import (
    UserCreate,
    UserLogin,
    UserOut,
    Token,
    create_access_token,
    authenticate_user,
    create_user,
    get_db,
    get_current_active_user,
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
    overview: str
    weaknesses: List[Weakness]
    normalized_report: str


class SelectedChange(BaseModel):
    id: str
    suggestion: str
    issue: Optional[str] = None


class RefineRequest(BaseModel):
    report: str
    selected_changes: List[SelectedChange]


class RefineResponse(BaseModel):
    refined_report: str


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
    current_user=Depends(get_current_active_user),
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

        analysis = analyze_report(combined)
        if not analysis or not analysis.get("weaknesses"):
            raise HTTPException(status_code=500, detail="No analysis generated.")
        return AnalysisResponse(**analysis)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {type(e).__name__}: {e}")


@app.post("/refine", response_model=RefineResponse)
async def refine(req: RefineRequest):
    if not req.report or not req.report.strip():
        raise HTTPException(status_code=400, detail="Report text is required.")

    refined = refine_report(req.report, [c.model_dump() for c in req.selected_changes])
    if not refined:
        raise HTTPException(status_code=500, detail="Could not generate refined report.")
    return RefineResponse(refined_report=refined)


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
