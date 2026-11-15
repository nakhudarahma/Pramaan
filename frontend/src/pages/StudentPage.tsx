import { useState, useEffect, useCallback } from "react";
import { ask, getDeadlines, getChanges } from "../api";
import { seedDeadlines, seedChanges } from "../mockData";
import type { AnswerCardData, Deadline, ChangeItem } from "../types";
import { useContext } from "../useContext";
import { getSession } from "../session";
import ContextBar from "../components/ContextBar";
import DeadlineStrip from "../components/DeadlineStrip";
import ChangeFeed from "../components/ChangeFeed";
import IntentTiles from "../components/IntentTiles";
import ChatLauncher from "../components/ChatLauncher";
import SourceDrawer from "../components/SourceDrawer";

export default function StudentPage() {
  const { course, semester, update, courses } = useContext();
  const [deadlines, setDeadlines] = useState<Deadline[]>(() =>
    seedDeadlines.filter((d) => d.course === "bsc-ds" && d.semester === 4)
  );
  const [changes, setChanges] = useState<ChangeItem[]>(() =>
    seedChanges.filter((c) => c.course === "bsc-ds" && c.semester === 4 && c.approved)
  );
  const [loading, setLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerData, setDrawerData] = useState({ factId: "", notice: "", page: 1 });
  const [pendingQuestion, setPendingQuestion] = useState<{ q: string; n: number } | null>(null);

  const firstName = getSession()?.name.trim().split(/\s+/)[0] || "Student";
  const hour = new Date().getHours();
  const greeting =
    hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  const fetchData = useCallback(
    (showLoading = false) => {
      if (showLoading) setLoading(true);
      Promise.all([
        getDeadlines(course, semester),
        getChanges(course, semester),
      ])
        .then(([nextDeadlines, nextChanges]) => {
          setDeadlines(Array.isArray(nextDeadlines) ? nextDeadlines : []);
          setChanges(Array.isArray(nextChanges) ? nextChanges : []);
        })
        .catch((err) => {
          console.warn("fetchData failed, retaining default records:", err);
        })
        .finally(() => {
          if (showLoading) setLoading(false);
        });
    },
    [course, semester]
  );

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleAsk = async (question: string): Promise<AnswerCardData> => {
    const answer = await ask(question, course, semester);
    // After asking, re-fetch changes in case a new fact was published
    fetchData(false);
    return answer;
  };

  const openSource = (factId: string, notice: string, page: number) => {
    setDrawerData({ factId, notice, page });
    setDrawerOpen(true);
  };

  const handleIntentAsk = (question: string) => {
    setPendingQuestion({ q: question, n: Date.now() });
  };

  return (
    <div className="min-h-[calc(100dvh_-_3.5rem_-_1px)] pb-28 md:pb-12">
      <ContextBar
        course={course}
        semester={semester}
        courses={courses}
        onChange={update}
      />

      <div className="relative">
        <div
          className="student-glow pointer-events-none absolute inset-x-0 top-0 h-56"
          aria-hidden="true"
        />
        <div className="relative mx-auto max-w-[1600px] px-4 md:px-8 xl:px-12 py-6">
          <div
            className="student-reveal mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3"
            style={{ animationDelay: "0ms" }}
          >
            <div>
              <p className="text-xl sm:text-2xl font-bold text-navy-700 dark:text-night-text">
                {greeting}, {firstName}
              </p>
              <p className="text-xs sm:text-sm text-slate-500 dark:text-night-muted mt-0.5">
                Official verified records and circular updates for your semester
              </p>
            </div>
            <span className="self-start sm:self-auto inline-flex items-center gap-1.5 rounded-full bg-white dark:bg-night-card border border-slate-200 dark:border-night-border px-3 py-1 text-xs font-medium text-slate-500 dark:text-night-muted shadow-sm">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              Live Ledger: 12 Nov 2026
            </span>
          </div>

          <div className="space-y-6">
            <div
              className="student-reveal"
              style={{ animationDelay: "80ms" }}
            >
              <DeadlineStrip deadlines={deadlines} loading={loading} />
            </div>
            <div
              className="student-reveal"
              style={{ animationDelay: "160ms" }}
            >
              <ChangeFeed changes={changes} loading={loading} onSource={openSource} />
            </div>
            <div
              className="student-reveal"
              style={{ animationDelay: "240ms" }}
            >
              <IntentTiles onAsk={handleIntentAsk} />
            </div>
          </div>
        </div>
      </div>


      {/* Floating chat launcher */}
      <ChatLauncher
        onAsk={handleAsk}
        onSource={openSource}
        initialQuestion={pendingQuestion?.q ?? null}
        initialNonce={pendingQuestion?.n}
      />

      <SourceDrawer
        open={drawerOpen}
        factId={drawerData.factId}
        noticeLabel={drawerData.notice}
        page={drawerData.page}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
