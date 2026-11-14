# Pramaan

**A verified, version-aware college notice assistant.**
Built by **Team QuadraSyn** for B. K. Birla College (Empowered Autonomous Status), Kalyan.

Students often can't tell which college notice is current, which one applies to their course and semester, or where the information came from. Pramaan treats official notices as source documents. Admins upload PDF circulars, the system extracts facts with their source page, and a human approves every change before students see it. Students get answers they can check.

## Key Features

- **Admin-approved changes:** nothing reaches students until an admin approves it.
- **Scoped answers:** answers apply only to the student's own course and semester.
- **Verified answer cards:** each answer shows its status, validity and the notice it replaces.
- **Page-level source citation:** every answer points to the original notice page.
- **Change feed:** students see only the changes that affect them, with the old and new value.
- **Conflict and supersession handling:** newer notices replace older ones, and clashing notices are flagged for review.
- **Honest unknowns:** if something is not in the official records, the app says so and names the office to contact.
- **Unanswered questions queue:** shows admins what students ask that has no answer yet.

## Answer Statuses

| Status | Meaning |
|---|---|
| Verified | Current, approved and applies to the student |
| Outdated | The validity period has passed; confirm with the office |
| Disputed | Two notices disagree; the answer is blocked and both sources are shown |
| Unavailable | Not in the official records yet |

## How It Works

1. **Upload PDF notice:** the admin uploads a circular.
2. **Extract facts and page metadata:** facts such as fees, dates and rules are pulled out with their source page.
3. **Detect conflicts and compare old vs new:** each fact is checked against what is already live.
4. **Admin review, approve and publish:** the admin sees a before and after diff and approves it.
5. **Student asks a question:** the app answers for their course and semester.
6. **Verified answer with page citation:** the student sees the answer, its status and the source page.

## Architecture

- **Users:** Student, College Admin
- **Frontend:** Student Portal and Admin Portal
- **Backend and Verification Core:** PDF ingestion, atomic fact extraction, conflict and supersession detector, grounded QA engine, immutable audit engine
- **Data Layer:** database for the truth ledger, document store for raw notice PDFs

## Portals

**Student Portal**
- Course and semester selector
- Deadline strip
- Verified change feed
- Grounded ask chatbot
- PDF and page source inspection

**Admin Portal**
- PDF upload
- Fact review queue
- Conflict resolution
- Unanswered questions
- Publish

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS |
| Backend | FastAPI, Python 3.11, Uvicorn |
| PDF / OCR | PyMuPDF (fitz) |
| Database | PostgreSQL / SQLite, SQLAlchemy 2.0 |
| Authentication | Google OAuth 2.0, JWT + RBAC |
| Deployment | Vercel (frontend), Render (backend) |

## Repository Structure

```
frontend/   React app (student portal, admin portal, login)
backend/    FastAPI service, verification core, database models
```

## Getting Started

**Frontend**
```bash
cd frontend
npm install
npm run dev
```
The app runs at `http://localhost:5173`.

**Backend**
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

## Security and Privacy

- Role-based access control (student and admin)
- Admin actions require a verified Google sign-in
- No student personal data is collected beyond the chosen course and semester
- Every change is recorded in an append-only audit history

---

---

<p align="center">Made with 💗 by <b>Team QuadraSyn</b></p>
