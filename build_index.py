from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict

import faiss
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from pypdf import PdfReader

# -------------------------
# Environment
# -------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

client = OpenAI()

# -------------------------
# Paths
# -------------------------
PDF_PATH = BASE_DIR / "Constitution of Pakistan 1973.pdf"
INDEX_PATH = BASE_DIR / "constitution.index"
DOCS_PATH = BASE_DIR / "constitution_docs.json"


# -------------------------
# PDF -> text chunks
# -------------------------
def load_pdf_chunks(path: Path, chunk_size: int = 1200, overlap: int = 200) -> List[Dict]:
    reader = PdfReader(str(path))

    if reader.is_encrypted:
        try:
            reader.decrypt("")  # attempt empty password (common for open docs)
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(
                "PDF is encrypted and could not be opened. "
                "Decrypt it or supply a password before indexing."
            ) from exc

    chunks: List[Dict] = []

    for page_no, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue

        # normalize whitespace
        text = " ".join(text.split())

        start = 0
        while start < len(text):
            end = min(len(text), start + chunk_size)
            chunk_text = text[start:end]
            chunks.append(
                {
                    "text": chunk_text,
                    "source": "Constitution of Pakistan 1973",
                    "title": f"Page {page_no}",
                    "page": page_no,
                }
            )
            if end == len(text):
                break
            start = end - overlap

    return chunks


# -------------------------
# Embeddings
# -------------------------
def embed_texts(texts: List[str]) -> np.ndarray:
    embeddings: List[List[float]] = []
    for i in range(0, len(texts), 32):
        batch = texts[i : i + 32]
        resp = client.embeddings.create(model="text-embedding-3-small", input=batch)
        embeddings.extend([d.embedding for d in resp.data])
    return np.array(embeddings, dtype="float32")


# -------------------------
# Build index
# -------------------------
def main():
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"PDF not found at {PDF_PATH}")

    if not PDF_PATH.stat().st_size:
        raise FileNotFoundError(f"PDF is empty: {PDF_PATH}")

    chunks = load_pdf_chunks(PDF_PATH)
    texts = [c["text"] for c in chunks]

    if not texts:
        raise RuntimeError("No text extracted from PDF; check file or parser.")

    emb = embed_texts(texts)

    # cosine similarity via normalized dot product
    faiss.normalize_L2(emb)
    index = faiss.IndexFlatIP(emb.shape[1])
    index.add(emb)

    faiss.write_index(index, str(INDEX_PATH))
    DOCS_PATH.write_text(json.dumps(chunks, indent=2), encoding="utf-8")

    print(f"Indexed {len(chunks)} chunks from Constitution into {INDEX_PATH}")


if __name__ == "__main__":
    main()
