import { ArrowRight, FileText, RefreshCw } from "lucide-react";
import type { ChangeItem } from "../types";

interface Props {
  changes: ChangeItem[];
  loading?: boolean;
  onSource: (factId: string, notice: string, page: number) => void;
}

export default function ChangeFeed({ changes, loading, onSource }: Props) {
  if (loading) {
    return (
      <div className="flex flex-col">
        <div className="flex items-center gap-2 mb-3">
          <RefreshCw className="w-4 h-4 text-sky-500 dark:text-sky-400 animate-spin" />
          <span className="text-sm font-bold uppercase tracking-wide text-slate-700 dark:text-night-text">
            What changed for you
          </span>
        </div>
        <div className="space-y-3">
          {[1, 2].map((i) => (
            <div
              key={i}
              className="bg-white/90 dark:bg-night-card/90 backdrop-blur-sm rounded-2xl border border-slate-100 dark:border-night-border shadow-card p-5"
            >
              <div className="skeleton h-4 w-2/3 rounded mb-3" />
              <div className="skeleton h-6 w-32 rounded-lg" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <RefreshCw className="w-4 h-4 text-sky-500 dark:text-sky-400" />
          <h2 className="text-sm font-bold uppercase tracking-wide text-slate-700 dark:text-night-text">
            What changed for you
          </h2>
        </div>
        {changes.length > 0 && (
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-sky-50 text-sky-600 dark:bg-sky-400/10 dark:text-sky-400 border border-sky-100 dark:border-sky-500/20">
            {changes.length} {changes.length === 1 ? "update" : "updates"}
          </span>
        )}
      </div>

      {changes.length === 0 ? (
        <div className="flex flex-col items-center justify-center bg-white/90 dark:bg-night-card/90 backdrop-blur-sm rounded-2xl border border-slate-100 dark:border-night-border shadow-card p-8 text-center">
          <FileText className="w-10 h-10 text-slate-200 dark:text-slate-600 mx-auto mb-3" />
          <p className="text-sm font-medium text-slate-500 dark:text-night-muted">
            No recent changes for your course and semester.
          </p>
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
            New updates published by the college administration will appear here.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {changes.map((c) => (
            <div
              key={c.id}
              className="student-card bg-white/90 dark:bg-night-card/90 backdrop-blur-sm rounded-2xl border border-slate-100 dark:border-night-border shadow-card p-4 sm:p-5 transition-all hover:border-sky-200 dark:hover:border-sky-500/30"
            >
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="text-sm sm:text-[15px] font-semibold text-slate-900 dark:text-night-text">
                      {c.label}
                    </span>
                    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-50 dark:bg-night-border/50 border border-slate-200/60 dark:border-night-border">
                      <span className="change-old text-xs sm:text-[13px] text-slate-500 dark:text-night-muted line-through">
                        {c.oldValue}
                      </span>
                      <ArrowRight className="w-3.5 h-3.5 text-slate-400 dark:text-night-muted" />
                      <span className="change-new text-xs sm:text-[13px] font-bold text-sky-600 dark:text-sky-400">
                        {c.newValue}
                      </span>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onSource(c.factId, c.noticeTitle, c.page)}
                  className="self-start sm:self-auto inline-flex items-center gap-1.5 text-xs sm:text-[13px] font-medium text-sky-600 dark:text-sky-300 hover:text-sky-700 dark:hover:text-sky-200 bg-sky-50 dark:bg-sky-400/10 hover:bg-sky-100 dark:hover:bg-sky-400/20 px-3 py-1.5 rounded-lg transition-all active:scale-95 flex-shrink-0"
                >
                  <FileText className="w-3.5 h-3.5" />
                  <span>{c.noticeTitle}, page {c.page}</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
