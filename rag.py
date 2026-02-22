from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Tuple

import faiss
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

# -------------------------
# LOAD .env FIRST
# -------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

# Safety check (optional but recommended)
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY not loaded in rag.py"

# -------------------------
# OpenAI client
# -------------------------
client = OpenAI()

# -------------------------
# Paths
# -------------------------
INDEX_PATH = BASE_DIR / "constitution.index"
DOCS_PATH = BASE_DIR / "constitution_docs.json"



def _load_index_and_docs() -> Tuple[faiss.Index, List[Dict]]:
    if not INDEX_PATH.exists() or not DOCS_PATH.exists():
        raise FileNotFoundError(
            "RAG index not found. Run: python build_index.py (from project folder)."
        )
    index = faiss.read_index(str(INDEX_PATH))
    docs = json.loads(DOCS_PATH.read_text(encoding="utf-8"))
    return index, docs


_INDEX, _DOCS = None, None


def _ensure_loaded():
    global _INDEX, _DOCS
    if _INDEX is None or _DOCS is None:
        _INDEX, _DOCS = _load_index_and_docs()


def embed_query(q: str, model: str = "text-embedding-3-small") -> np.ndarray:
    emb = client.embeddings.create(model=model, input=[q]).data[0].embedding
    v = np.array([emb], dtype="float32")
    faiss.normalize_L2(v)
    return v


def retrieve(q: str, k: int = 4) -> List[Dict]:
    """Return top-k docs: {id, source, title, text}"""
    _ensure_loaded()
    qv = embed_query(q)
    scores, ids = _INDEX.search(qv, k)
    out: List[Dict] = []
    for idx in ids[0]:
        if idx == -1:
            continue
        out.append(_DOCS[idx])
    return out


def format_context(docs: List[Dict]) -> str:
    if not docs:
        return ""
    chunks = []
    for d in docs:
        src = d.get("source", "")
        title = d.get("title", "")
        page = d.get("page")
        header_parts = [src, title]
        if page:
            header_parts.append(f"Page {page}")
        header = " - ".join(p for p in header_parts if p)
        chunks.append(f"{header}\n{d.get('text','')}".strip())
    return "\n\n---\n\n".join(chunks)
