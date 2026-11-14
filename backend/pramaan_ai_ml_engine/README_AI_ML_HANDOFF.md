# Pramaan - AI/ML & Evaluation Engine Handoff (B.K. Birla College)

## 1. What Is Inside This Package
- pramaan_ai_engine.py (Core AI/ML Module):
  1. extract_facts_from_pdf(pdf_path, notice_id) - Gemini native PDF extraction + PyMuPDF [x0, y0, x1, y1] bounding-box locator + automatic offline fallback.
  2. classify_candidate_conflict(candidate, issued_on, active_facts) - Deterministic Conflict Engine (NEW, DUPLICATE, SCOPE_OVERLAP, SUPERSEDES, DISPUTED).
  3. route_question(question, ctx) - English + Hinglish intent router (volatile | static | unclear) with instant keyword fallback.
  4. answer_volatile_query(question, matched_facts, ctx) - {fact:ID} placeholder composer, bare-digit anti-hallucination verifier, deterministic multi-fact sum calculator, and verified | outdated | disputed | unavailable card builder.
- evaluate_gold_set.py & gold_set_results.json (Section 9.5 Evaluation):
  - Runs the 40-question Gold-Set benchmark (Groups A-F + 8 Hinglish queries) comparing B0 (Markdown Prompt), B1 (Vanilla RAG), and Pramaan.
- main.py & ledger_db.json (Ready-to-Run FastAPI Integration):
  - Pre-loaded with B.K. Birla College (B.Sc. Data Science) notices N1-N12 covering all Section 12.4 demo checkpoints.

## 2. Quick Start (Zero Configuration Required)
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to test all endpoints interactively.