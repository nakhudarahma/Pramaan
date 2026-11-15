import { getSession } from "./session";
import type {
  AnswerCardData,
  CourseId,
  Semester,
  Deadline,
  ChangeItem,
  NoticeRecord,
  FactRow,
  UnansweredItem,
} from "./types";
import {
  seedDeadlines,
  seedChanges,
  seedNotices,
  seedFacts,
  seedFactRows,
  seedUnanswered,
  seedNoticesForReview,
} from "./mockData";

const API_BASE = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");
const USE_MOCK = false;
const MOCK_DELAY = 150;

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

function isDemoSession(): boolean {
  const session = getSession();
  return Boolean(session?.demo || session?.mock);
}

// ---------- localStorage persistence ----------

const STORAGE_KEY = "pramaan-demo-state-v11";

interface PersistedState {
  facts: typeof seedFacts;
  factRows: FactRow[];
  changes: ChangeItem[];
  unanswered: UnansweredItem[];
  notices: NoticeRecord[];
}

function loadState(): PersistedState {
  let stored: Partial<PersistedState> = {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) stored = JSON.parse(raw) || {};
  } catch {
    /* ignore */
  }
  const fresh: PersistedState = {
    facts:
      stored.facts && Object.keys(stored.facts).length > 0
        ? stored.facts
        : structuredClone(seedFacts),
    factRows:
      stored.factRows && stored.factRows.length > 0
        ? stored.factRows
        : structuredClone(seedFactRows),
    changes:
      stored.changes && stored.changes.length > 0
        ? stored.changes
        : structuredClone(seedChanges),
    unanswered:
      stored.unanswered && stored.unanswered.length > 0
        ? stored.unanswered
        : structuredClone(seedUnanswered),
    notices:
      stored.notices && stored.notices.length > 0
        ? stored.notices
        : structuredClone(seedNotices),
  };
  saveState(fresh);
  return fresh;
}

function saveState(state: PersistedState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* ignore */
  }
}

export function resetDemo() {
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem("pramaan-demo-state-v5");
  localStorage.removeItem("pramaan-demo-state-v6");
  localStorage.removeItem("pramaan-demo-state-v7");
  localStorage.removeItem("pramaan-demo-state-v8");
  localStorage.removeItem("pramaan-demo-state-v9");
  localStorage.removeItem("pramaan-demo-state-v10");
  localStorage.removeItem("pramaan-demo-state-v11");
  localStorage.removeItem("pramaan-context");
}

interface GoogleUser {
  name: string;
  email: string;
  picture?: string;
  role: "student" | "admin";
}

type GoogleSignInResult =
  | { ok: true; user: GoogleUser }
  | { ok: false; reason: string };

export async function googleSignIn(
  role: "student" | "admin",
  extra?: { token?: string; credential?: string; name?: string; email?: string; picture?: string }
): Promise<GoogleSignInResult> {
  try {
    const res = await fetch(`${API_BASE}/api/auth/google`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, ...(extra || {}) }),
    });
    if (!res.ok) {
      return { ok: false, reason: "Server returned status " + res.status };
    }
    return await res.json();
  } catch (err: any) {
    return { ok: false, reason: err?.message || "Google sign-in connection failed" };
  }
}

// ---------- keyword matching ----------

function matchFact(
  question: string
): { key: string; data: (typeof seedFacts)[string] } | null {
  const state = loadState();
  const q = question.toLowerCase();
  const scored: { key: string; data: (typeof seedFacts)[string]; score: number }[] = [];

  for (const [key, data] of Object.entries(state.facts)) {
    let score = 0;
    for (const kw of data.keywords) {
      if (q.includes(kw)) score += kw.split(" ").length;
    }
    if (score > 0) scored.push({ key, data, score });
  }

  if (scored.length === 0) return null;
  scored.sort((a, b) => b.score - a.score);
  return { key: scored[0].key, data: scored[0].data };
}

const FACT_TO_NOTICE: Record<string, string> = {
  "f-latefee": "n10",
  "f-examform": "n25",
  "f-labexam-a": "n18",
  "f-labexam-b": "n19",
  "f-hostel": "n07",
  "f-library": "n08",
  "f-latefee-new": "n12",
};

const CATEGORY_BY_FACT: Record<string, string> = {
  lateFee: "Fees",
  examForm: "Exams",
  labExam: "Exams",
  hostelFee: "Hostel",
  libraryFee: "Library",
};

function parseDateValue(value: string): Date | null {
  const match = value.match(/^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$/);
  if (!match) return null;
  const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].indexOf(match[2]);
  if (month === -1) return null;
  return new Date(Number(match[3]), month, Number(match[1]));
}

// ---------- API functions ----------

async function askImpl(
  question: string,
  course: CourseId,
  sem: Semester
): Promise<AnswerCardData> {
  const session = getSession();
  const isDemo = session?.demo === true;

  if (!USE_MOCK && !isDemo) {
    try {
      const res = await fetch(
        `${API_BASE}/api/ask?q=${encodeURIComponent(question)}&course=${course}&sem=${sem}`
      );
      if (res.ok) {
        const data = await res.json();
        let state: AnswerCardData["state"] = "verified";
        if (data.state === "outdated" || data.state === "disputed" || data.state === "unavailable") {
          state = data.state;
        } else if (data.state === "wrong_scope") {
          state = "outdated";
        } else if (data.state === "clarification" || data.state === "error") {
          state = "unavailable";
        }

        const sources = (data.sources && Array.isArray(data.sources) && data.sources.length > 0)
          ? data.sources
          : (data.citations && Array.isArray(data.citations))
          ? data.citations.map(
              (c: {
                fact_id?: string;
                notice_title?: string;
                document_name?: string;
                page_number?: number;
              }) => ({
                factId: c.fact_id || "f0",
                notice: c.notice_title || c.document_name || "Official Notice",
                page: c.page_number || 1,
              })
            )
          : [];

        return {
          state,
          text: data.text || data.answer || "Official notice record verified.",
          appliesTo: data.appliesTo || `${courseLabel(course)}, Sem ${sem}`,
          validUntil: data.validUntil || "—",
          replaces: data.replaces || undefined,
          sources,
          contact: data.contact || data.office_contact || undefined,
          note: data.note || undefined,
          issuedBy: data.issuedBy || undefined,
          noticeNumber: data.noticeNumber || undefined,
          noticeDate: data.noticeDate || undefined,
          category: data.category || undefined,
        };
      }
    } catch (err) {
      console.warn("API /api/ask unavailable, falling back to local ledger:", err);
    }
  }
  await delay(MOCK_DELAY);
  const match = matchFact(question);
  const state = loadState();

  // No match -> unavailable, and log to unanswered
  if (!match) {
    const existing = state.unanswered.find(
      (u) => u.question.toLowerCase() === question.toLowerCase().trim()
    );
    if (existing) {
      existing.count += 1;
    } else {
      state.unanswered.unshift({
        id: `u${Date.now()}`,
        question: question.trim(),
        count: 1,
      });
    }
    saveState(state);
    return {
      state: "unavailable",
      text: "Not in official records yet.",
      appliesTo: `${courseLabel(course)}, Sem ${sem}`,
      validUntil: "—",
      sources: [],
      contact: "Exam Cell",
      note: "Your question was logged for the admin.",
    };
  }

  const f = match.data;

  const primaryNotice =
    state.notices.find((n) => n.id === FACT_TO_NOTICE[f.sources[0]?.factId]) ||
    state.notices[0];
  const noticeMeta = primaryNotice
    ? {
        issuedBy: primaryNotice.issuer,
        noticeNumber: primaryNotice.id.toUpperCase(),
        noticeDate: primaryNotice.date,
        category: CATEGORY_BY_FACT[match.key] || "General",
      }
    : {};

  // Hostel fee scope check — only sem 1-2
  if (match.key === "hostelFee" && (sem > 2)) {
    return {
      state: "unavailable",
      text: "This applies to a different semester. Change your selection?",
      appliesTo: "All courses, Sem 1–2",
      validUntil: "15 Nov 2026",
      sources: f.sources,
      contact: "Hostel Office",
      note: "Your question was logged for the admin.",
      ...noticeMeta,
    };
  }

  // Disputed state — lab exam
  if (f.value === "DISPUTED") {
    return {
      state: "disputed",
      text: "Two notices disagree on this fact.",
      appliesTo: f.appliesTo,
      validUntil: f.validUntil,
      sources: f.sources,
      contact: "Examination Cell",
      ...noticeMeta,
    };
  }

  // Check if outdated — facts whose validity has passed
  const validUntilDate = parseDateValue(f.validUntil);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (validUntilDate && validUntilDate < today) {
    return {
      state: "outdated",
      text: f.value,
      appliesTo: f.appliesTo,
      validUntil: f.validUntil,
      replaces: f.replaces,
      sources: f.sources,
      contact: f.contact,
      ...noticeMeta,
    };
  }

  // Check if outdated — if there's a pending approved change that supersedes
  const supersedingChange = state.changes.find(
    (c) => c.factId === f.factId && c.approved
  );
  if (supersedingChange) {
    // The fact should already be updated — return verified with new value
  }

  return {
    state: "verified",
    text: f.value,
    appliesTo: f.appliesTo,
    validUntil: f.validUntil,
    replaces: f.replaces,
    sources: f.sources,
    contact: f.contact,
    ...noticeMeta,
  };
}

export async function ask(
  question: string,
  course: CourseId,
  sem: Semester
): Promise<AnswerCardData> {
  try {
    return await askImpl(question, course, sem);
  } catch (err) {
    console.warn("ask() failed, returning safe fallback:", err);
    return {
      state: "unavailable",
      text: "I couldn't reach the notice service right now. Please try again in a moment.",
      appliesTo: `${courseLabel(course)}, Sem ${sem}`,
      validUntil: "—",
      sources: [],
      contact: "Academic Office",
      note: "Your question was logged for the admin.",
    };
  }
}

export async function getDeadlines(
  course: CourseId,
  sem: Semester
): Promise<Deadline[]> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/deadlines?course=${course}&sem=${sem}`);
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data) ? data : (data.items ?? []);
        if (list.length > 0) {
          return list.map((item: any) => ({
            id: item.id || item.fact_id,
            title: item.title || item.fact_key,
            date: item.formatted_date || (typeof item.date === "string" ? item.date : `${item.date}`),
            daysLeft: item.daysLeft !== undefined ? item.daysLeft : (item.days_remaining ?? 0),
            course: item.course || course,
            semester: item.semester || sem,
          }));
        }
      }
    } catch (e) {
      /* fallback below */
    }
  }
  await delay(100);
  const filtered = seedDeadlines.filter((d) => d.course === course && d.semester === sem);
  return filtered.length > 0 ? filtered : seedDeadlines.slice(0, 3);
}

export async function getChanges(
  course: CourseId,
  sem: Semester
): Promise<ChangeItem[]> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/changes?course=${course}&sem=${sem}`);
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data) ? data : (data.items ?? []);
        if (list.length > 0) {
          return list.map((item: any) => ({
            id: item.id,
            label: item.label || item.title || item.fact_key,
            oldValue: item.oldValue || item.old_value || "",
            newValue: item.newValue || item.new_value || "",
            noticeDate: item.noticeDate || "12 Nov 2026",
            factId: item.factId || item.id,
            noticeTitle: item.noticeTitle || item.notice_title || "Notice",
            page: item.page || item.page_number || 1,
            course: item.course || course,
            semester: item.semester || sem,
            approved: item.approved !== undefined ? item.approved : true,
          }));
        }
      }
    } catch (e) {
      /* fallback below */
    }
  }
  await delay(100);
  const st = loadState();
  const filtered = st.changes.filter(
    (c) => c.course === course && c.semester === sem && c.approved
  );
  if (filtered.length > 0) return filtered;
  const anyApproved = st.changes.filter((c) => c.approved);
  return anyApproved.length > 0 ? anyApproved : structuredClone(seedChanges);
}

export async function getSource(factId: string): Promise<NoticeRecord> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/source/${factId}`);
      if (res.ok) {
        return await res.json();
      }
    } catch (e) {
      console.warn("API /api/source failed, falling back:", e);
    }
  }
  await delay(100);
  const state = loadState();
  const noticeId = FACT_TO_NOTICE[factId] || "n10";
  const notice = state.notices.find((n) => n.id === noticeId) || state.notices[0];
  return notice;
}

export async function uploadNotice(
  _file: File
): Promise<{ noticeId: string; review: typeof seedNoticesForReview; factRows: FactRow[] }> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const formData = new FormData();
      formData.append("file", _file);
      const res = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: formData });
      if (res.ok) {
        const data = await res.json();
        if (data && data.factRows) return data;
      }
    } catch (e) {
      console.warn("API /api/upload failed, falling back to mock upload:", e);
    }
  }
  await delay(1000);
  const state = loadState();
  const pending = state.factRows.filter((r) => r.status === "pending");
  return {
    noticeId: "n12",
    review: seedNoticesForReview,
    factRows: pending.length > 0 ? pending : structuredClone(seedFactRows),
  };
}

export async function getReview(
  noticeId: string
): Promise<{ review: typeof seedNoticesForReview; factRows: FactRow[] }> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/review/${noticeId}`);
      if (res.ok) {
        const data = await res.json();
        if (data && Array.isArray(data.factRows) && data.factRows.length > 0) {
          return data;
        }
      }
    } catch (e) {
      console.warn("API /api/review failed, falling back:", e);
    }
  }
  await delay(100);
  const state = loadState();
  const pending = state.factRows.filter((r) => r.status === "pending");
  return {
    review: seedNoticesForReview,
    factRows: pending.length > 0 ? pending : structuredClone(seedFactRows),
  };
}

export async function approveFact(id: string): Promise<FactRow[]> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/facts/${id}/approve`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) return data;
      }
    } catch (e) {
      console.warn("API /api/facts/approve failed, falling back:", e);
    }
  }
  await delay(150);
  const state = loadState();
  const row = state.factRows.find((r) => r.id === id);
  if (row) {
    row.status = "approved";

    // Update the live fact and add a change feed item
    if (row.factKey.toLowerCase().includes("late fee")) {
      state.facts.lateFee = {
        ...state.facts.lateFee,
        value: row.value,
        replaces: "Notice 10 Nov (Rs. 50)",
        sources: [{ factId: "f-latefee-new", notice: "Notice 12 Nov", page: 2 }],
      };
      state.changes.unshift({
        id: `c${Date.now()}`,
        label: "Late fee",
        oldValue: row.oldValue || "Rs. 50",
        newValue: row.value,
        noticeDate: "12 Nov",
        factId: "f-latefee-new",
        noticeTitle: "Notice 12 Nov",
        page: 2,
        course: row.scope.course,
        semester: row.scope.semester,
        approved: true,
      });
    }

    if (row.factKey.toLowerCase().includes("exam form")) {
      state.facts.examForm = {
        ...state.facts.examForm,
        value: row.value,
        replaces: "Notice 05 Nov (25 Nov 2026)",
        validUntil: "30 Nov 2026",
      };
    }

    if (row.factKey.toLowerCase().includes("lab")) {
      row.conflict = undefined;
      state.facts.labExam = {
        ...state.facts.labExam,
        value: row.value,
        replaces: "Notice 08 Nov (9:00 AM – 12:00 PM)",
      };
    }
  }
  saveState(state);
  return state.factRows.filter((r) => r.status === "pending");
}

export async function rejectFact(id: string): Promise<FactRow[]> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/facts/${id}/reject`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) return data;
      }
    } catch (e) {
      console.warn("API /api/facts/reject failed, falling back:", e);
    }
  }
  await delay(150);
  const state = loadState();
  const row = state.factRows.find((r) => r.id === id);
  if (row) row.status = "rejected";
  saveState(state);
  return state.factRows.filter((r) => r.status === "pending");
}

export async function editFact(id: string, value: string): Promise<FactRow[]> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/facts/${id}/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value }),
      });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) return data;
      }
    } catch (e) {
      console.warn("API /api/facts/edit failed, falling back:", e);
    }
  }
  await delay(150);
  const state = loadState();
  const row = state.factRows.find((r) => r.id === id);
  if (row) row.value = value;
  saveState(state);
  return state.factRows.filter((r) => r.status === "pending");
}

export async function getUnanswered(): Promise<UnansweredItem[]> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/unanswered`);
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data) ? data : (data.items ?? []);
        if (list.length > 0) return list;
      }
    } catch (e) {
      console.warn("API /api/unanswered failed, falling back:", e);
    }
  }
  await delay(150);
  const unanswered = loadState().unanswered;
  return unanswered && unanswered.length > 0 ? unanswered : structuredClone(seedUnanswered);
}

export async function getNotices(): Promise<NoticeRecord[]> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/notices`);
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data) ? data : (data.items ?? []);
        if (list.length > 0) return list;
      }
    } catch {
      /* fallback below */
    }
  }
  await delay(150);
  const notices = loadState().notices;
  return notices && notices.length > 0 ? notices : structuredClone(seedNotices);
}

export async function publishFacts(
  approvedIds: string[]
): Promise<{ count: number; affected: string }> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: approvedIds }),
      });
      if (res.ok) {
        return await res.json();
      }
    } catch (e) {
      console.warn("API /api/publish failed, falling back:", e);
    }
  }
  await delay(250);
  return { count: approvedIds.length, affected: "B.Sc Data Science Sem 4" };
}

// ---------- helpers ----------

export function courseLabel(id: CourseId): string {
  const map: Record<CourseId, string> = {
    "bsc-ds": "B.Sc Data Science",
    "bsc-cs": "B.Sc Computer Science",
    "bsc-it": "B.Sc Information Technology",
    bcom: "B.Com",
    bms: "BMS",
    baf: "BAF",
    ba: "BA",
  };
  return map[id];
}

export async function resolveConflictNotice(
  factRowId: string,
  winningNoticeNumber: string
): Promise<FactRow[]> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/facts/${factRowId}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ winningNoticeNumber }),
      });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) return data;
      }
    } catch (e) {
      console.warn("API /api/facts/resolve failed, falling back:", e);
    }
  }
  await delay(150);
  const state = loadState();
  const row = state.factRows.find((r) => r.id === factRowId);
  if (row) {
    row.conflict = undefined;
    if (winningNoticeNumber.includes("19")) {
      row.value = "2:00 PM – 5:00 PM";
      row.status = "approved";
      state.facts.labExam = {
        ...state.facts.labExam,
        value: "2:00 PM – 5:00 PM",
        validUntil: "30 Nov 2026",
        replaces: "Notice 08 Nov (9:00 AM – 12:00 PM)",
        sources: [{ factId: "f-labexam-b", notice: "Notice 11 Nov", page: 1 }],
      };
    } else {
      row.value = "9:00 AM – 12:00 PM";
      row.status = "rejected";
      state.facts.labExam = {
        ...state.facts.labExam,
        value: "9:00 AM – 12:00 PM",
        validUntil: "30 Nov 2026",
        sources: [{ factId: "f-labexam-a", notice: "Notice 08 Nov", page: 3 }],
      };
    }
  }
  saveState(state);
  return state.factRows.filter((r) => r.status === "pending");
}

export async function saveCustomFact({
  question,
  answerValue,
  course,
  semester,
  validUntil,
}: {
  question: string;
  answerValue: string;
  course: CourseId;
  semester: Semester;
  validUntil?: string;
}): Promise<UnansweredItem[]> {
  if (!USE_MOCK && !isDemoSession()) {
    try {
      const res = await fetch(`${API_BASE}/api/facts/custom`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, answerValue, course, semester, validUntil }),
      });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) return data;
      }
    } catch (e) {
      console.warn("API /api/facts/custom failed, falling back:", e);
    }
  }
  await delay(150);
  const state = loadState();
  const factId = `f-custom-${Date.now()}`;
  const key = `custom_${Date.now()}`;

  // Generate keywords from question so student chat matches it
  const cleanQ = question.toLowerCase().replace(/[^a-z0-9\s-]/g, " ").trim();
  const words = cleanQ.split(/\s+/).filter((w) => w.length > 1);
  const keywords = Array.from(new Set([cleanQ, question.toLowerCase().trim(), ...words]));

  if (cleanQ.includes("re") && cleanQ.includes("exam")) {
    keywords.push("re-exam", "reexam", "re exam", "re-exam date", "re-exam kab hai");
  }
  if (cleanQ.includes("hostel") || cleanQ.includes("gate")) {
    keywords.push("hostel gate", "gate timing", "hostel timing", "curfew", "in time");
  }

  state.facts[key] = {
    factId,
    key: cleanQ,
    value: answerValue,
    appliesTo: `${courseLabel(course)}, Sem ${semester}`,
    validUntil: validUntil || "31 Dec 2026",
    sources: [{ factId, notice: "Notice 12 Nov", page: 1 }],
    keywords,
    scope: { course, semester },
  };

  state.unanswered = state.unanswered.filter(
    (u) => u.question.toLowerCase().trim() !== question.toLowerCase().trim()
  );

  saveState(state);
  return state.unanswered;
}
