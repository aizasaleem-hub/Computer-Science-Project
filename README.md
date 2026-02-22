# Report Reviewer (Constitution-Aligned)

FastAPI service that reviews a report, flags weaknesses, and suggests improvements grounded in the Constitution of Pakistan (1973).

## 1) Setup
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 2) Build the RAG index (one-time)
Make sure `Constitution of Pakistan 1973.pdf` is present in the project root.
```bash
python build_index.py
```
This creates:
- `constitution.index`
- `constitution_docs.json`

## 3) Run API
```bash
uvicorn main:app --reload
```
Open API docs at http://127.0.0.1:8000/docs

## 4) Quick UI
Open `index.html` in a browser. Paste text and/or upload a PDF/DOCX/TXT file, then click **Analyze**.
