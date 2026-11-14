# Pramaan — Technical Architecture & System Specification

Pramaan is a **Deterministic Truth Ledger and Conflict-Resolution Engine** for educational institutions that digests unstructured administrative circulars (PDFs), extracts atomic facts, resolves inter-notice contradictions, and serves verified answers to students with page-level citations.

---

## 1. High-Level System Architecture

```mermaid
flowchart TD
    subgraph Client_Layer["Client Layer (Frontend - React 18 + TypeScript + Vite)"]
        UI_Student["Student Portal\n- Context Selector (Course/Sem)\n- Deadline Strip\n- Verified Change Feed\n- Grounded Ask Chatbot\n- Source Inspection Drawer"]
        UI_Admin["Admin Portal\n- PDF Upload & OCR Extraction\n- Fact Review & Edit Queue\n- Conflict Resolution Studio\n- Unanswered Question Resolver\n- One-Click Instant Publisher"]
        Auth_GIS["Google Identity Services (OAuth 2.0)\n+ Instant Demo Session Bypassing"]
    end

    subgraph Gateway_Routing["API & Gateway Layer (FastAPI / ASGI Uvicorn)"]
        CORS["CORS Middleware\n(Vercel & Local origins)"]
        Router["Unified /api Router"]
        Auth_MW["JWT & RBAC Middleware\n(Admin vs Student vs Demo)"]
    end

    subgraph Service_Core["Business & Verification Core (Python 3.11)"]
        PDF_Engine["Ingestion Engine\n(PyMuPDF / fitz, page slicing, hash deduplication)"]
        Fact_Extractor["Atomic Fact Extraction\n(NLP/LLM semantic parser, scope & validity annotator)"]
        Conflict_Engine["Conflict & Supersession Detector\n(Pairwise temporal checks, state classifier)"]
        QA_Engine["Temporal Grounded QA Engine\n(Anti-hallucination constraint, citation compiler)"]
        Audit_Engine["Immutable Audit Engine\n(Append-only ledger of state transitions)"]
    end

    subgraph Data_Layer["Persistence Layer (SQLAlchemy 2.0)"]
        DB[(Relational DB\nPostgreSQL / SQLite)]
        Storage[(Local / S3 Document Store\nRaw Notice PDFs)]
        LocalLedger[(Client-Side Demo Ledger\nLocalStorage v10)]
    end

    Client_Layer --> Gateway_Routing
    Gateway_Routing --> Service_Core
    Service_Core --> Data_Layer
    UI_Student -.->|In Demo Mode| LocalLedger
    UI_Admin -.->|In Demo Mode| LocalLedger
```

---

## 2. Ingestion & Truth Resolution Pipeline

```mermaid
sequenceDiagram
    autonumber
    actor Admin as College Administrator
    participant Frontend as Admin Portal UI
    participant Bridge as FastAPI /api Bridge
    participant PDF as PyMuPDF Extractor
    participant Conflict as Conflict Detector
    participant DB as Truth Ledger (Database)
    actor Student as Student (Chatbot/Feed)

    Admin->>Frontend: Uploads Notice PDF (e.g. Revised Late Fee)
    Frontend->>Bridge: POST /api/upload (Multipart/Form-Data)
    Bridge->>PDF: Parse text, page boundaries, metadata
    PDF-->>Bridge: Extracted raw text + page mapping
    Bridge->>Conflict: Compare extracted facts vs active DB facts
    Conflict-->>Bridge: Flag supersessions & conflicts (e.g., Notice #19 vs #18)
    Bridge-->>Frontend: Review Queue (FactRows with conflicts & oldValue)
    
    Admin->>Frontend: Resolves conflict & Approves facts
    Frontend->>Bridge: POST /api/publish (Approved Fact IDs)
    Bridge->>DB: Mutate old facts to 'superseded', mark new as 'approved'
    Bridge->>DB: Write append-only AuditLog record
    Bridge-->>Frontend: 200 OK + confetti celebration

    Student->>Frontend: Asks "What is the late fee?"
    Frontend->>Bridge: GET /api/ask?q=...&course=bsc-ds&sem=4
    Bridge->>DB: Fetch active fact with highest temporal priority
    DB-->>Bridge: Active fact (Rs. 75, replaces Notice 10 Nov)
    Bridge-->>Student: Verified AnswerCard with Page 2 Citation & Proof
```

---

## 3. Four Canonical Truth States

The core engine models every question into one of 4 deterministic states:

```mermaid
stateDiagram-v2
    [*] --> Query_Received: Student asks question

    Query_Received --> Scope_Check: Evaluates Course & Semester Scope
    Scope_Check --> Unavailable: Fact not found OR outside student semester
    
    Scope_Check --> Temporal_Check: Matching fact found in ledger
    Temporal_Check --> Outdated: Current Date > Fact.valid_until OR superseding notice published
    
    Temporal_Check --> Conflict_Check: Valid within temporal window
    Conflict_Check --> Disputed: Contradictory circulars active without admin resolution
    Conflict_Check --> Verified: Unambiguous active circular in effect

    Verified --> [*]: Green Card + Direct PDF Citation
    Outdated --> [*]: Amber Card + Superseding Reference
    Disputed --> [*]: Red Card + Conflicting Notices Listed
    Unavailable --> [*]: Grey Card + Auto-logged to Unanswered Queue
```

---

## 4. Database Schema (Entity-Relationship)

```mermaid
erDiagram
    DOCUMENT ||--o{ NOTICE : contains
    NOTICE ||--o{ FACT : defines
    FACT ||--o{ FACT_VERSION : tracks
    NOTICE ||--o{ CONFLICT : participates_in
    USER ||--o{ AUDIT_LOG : generates

    DOCUMENT {
        uuid id PK
        string filename
        string sha256_hash
        string storage_path
        string status
        datetime created_at
    }

    NOTICE {
        uuid id PK
        uuid document_id FK
        string notice_number
        string title
        string issuer
        date issued_on
        string category
        string status "current | superseded | expired"
        string summary
    }

    FACT {
        uuid id PK
        uuid notice_id FK
        string fact_key
        string value
        string old_value
        string scope_course
        int scope_semester
        date valid_until
        string status "pending | approved | rejected"
        string source_text
        int page_number
    }

    CONFLICT {
        uuid id PK
        uuid notice_a_id FK
        uuid notice_b_id FK
        string fact_key
        string conflict_description
        string status "unresolved | resolved"
        uuid winning_notice_id FK
    }

    UNANSWERED_QUESTION {
        uuid id PK
        string question
        int occurrence_count
        string status "open | resolved"
        datetime last_asked_at
    }

    AUDIT_LOG {
        uuid id PK
        uuid actor_id FK
        string action "upload | approve | reject | resolve | publish"
        string target_entity
        uuid target_id
        json metadata
        datetime created_at
    }
```

---

## 5. Technology Stack Summary

| Layer | Technologies | Role in System |
|---|---|---|
| **Frontend Framework** | React 18, TypeScript, Vite | Fast SPA bundling, strict type safety |
| **Styling & UI** | Tailwind CSS, Lucide React, Canvas Confetti | Responsive mobile-first interface, micro-interactions |
| **Client Persistence** | LocalStorage (`pramaan-demo-state-v10`) | Zero-backend demo operation for hackathons |
| **Backend Framework** | Python 3.11, FastAPI, Uvicorn (ASGI) | Async RESTful API, OpenAPI documentation |
| **Data Extraction** | PyMuPDF (`fitz`), Regex Lexers | Native PDF parsing, bounding box & page slicing |
| **ORM & Database** | SQLAlchemy 2.0, PostgreSQL / SQLite, Alembic | Type-annotated relational models & migrations |
| **Authentication** | Google Identity Services (GIS), JWT | Single Sign-On + Instant Role Switcher |
| **Deployment** | Vercel (Frontend), Render (FastAPI Docker/Web Service) | Global edge CDN + scalable cloud execution |
