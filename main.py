from __future__ import annotations

from io import BytesIO
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pypdf import PdfReader
from docx import Document

from agent import analyze_report

app = FastAPI(title="Report Reviewer", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalysisResponse(BaseModel):
    analysis: str


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
        if not analysis:
            raise HTTPException(status_code=500, detail="No analysis generated.")
        return AnalysisResponse(analysis=analysis)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {type(e).__name__}: {e}")
