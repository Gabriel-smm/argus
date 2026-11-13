"use client";

import { create } from "zustand";

import type { LayaRole } from "@/lib/laya-files";

export type SiteGroup = "needs_review" | "unknown" | "expected";

/** The site check as a picture-ready report (pipeline/context.py build_site_report). */
export type SiteReport = {
  site: string;
  verdict: "review" | "unknown" | "normal";
  headline: string;
  explain: string;
  counts: Record<SiteGroup, number>;
  total: number;
  kinds: { kind: string; count: number; worst: SiteGroup }[];
  flagged: {
    id: string;
    group: SiteGroup;
    title: string;
    kind: string;
    reason: string;
    check_next: string;
    protected: boolean;
  }[];
  more_flagged: number;
  /** Every signal, worst first, for the category buttons. */
  signals: SiteReport["flagged"];
  questions: string[];
};

export type AnalysisSummary = {
  knowledge_name: string;
  data_name: string;
  observations: number;
  total_rows: number;
  /** Index of the first classified row. Zero means the run started at the first row. */
  row_offset: number;
  questions: {
    name: string;
    instructions: string;
    counts: Record<string, number>;
  }[];
  low_confidence: number;
  seconds: number;
  /** Present when the site check ran. */
  site_check?: Record<SiteGroup, number>;
  site_report?: SiteReport | null;
  /** Set when the result came from the Scan button's built-in scene. */
  scene?: { title: string; badge: string };
};

export type AnalysisError = { message: string; field: LayaRole | null };

type AnalysisState = {
  /** Laya is classifying; the chat model is unloaded until it finishes. */
  running: boolean;
  /** The classification the chat currently answers from, if any. */
  summary: AnalysisSummary | null;
  error: AnalysisError | null;
  /** The Scan button's sweep is on screen: from the click until the result, and at least SCAN_MIN_MS. */
  scanning: boolean;
  /**
   * Show the result instead of the Scan page. Starts false on every page load, even when the
   * Laya service still holds an earlier result, and lasts only for this page session.
   */
  showResult: boolean;
  run: (knowledge: File[], data: File[]) => Promise<boolean>;
  /** Run a built-in scene (no uploads), for the Scan button. */
  scan: (scene?: string) => Promise<boolean>;
  /** The "See last result" link: show a result left from an earlier run. */
  showLastResult: () => void;
  clear: () => Promise<void>;
  refresh: () => Promise<void>;
  /** Read the pipeline once, without scheduling another read. */
  sync: () => Promise<void>;
};

export const ANALYSIS_POLL_MS = 2000;
/** One left-to-right pass of the scan animation (components/scan-hero.tsx). */
export const SCAN_SWEEP_MS = 3200;
/** The sweep stays on screen at least this long, so a fast result never makes it flash by. */
export const SCAN_MIN_MS = SCAN_SWEEP_MS + 400;

async function pullAnalysis(set: (partial: Partial<AnalysisState>) => void): Promise<boolean> {
  const res = await fetch("/api/pipeline/context").catch(() => null);
  if (!res?.ok) return false;
  const payload = await res.json().catch(() => null);
  if (!payload) return false;
  set({
    running: payload.running === true,
    summary: payload.active ? payload.summary : null,
  });
  return payload.running === true;
}

/** Shared by the Library, which starts a run, and the thread, which reflects it. */
export const useAnalysis = create<AnalysisState>((set, get) => {
  /** POST to the Laya service and make the answer the current result. */
  const submit = async (path: "classify" | "scan", makeBody: () => Promise<object>) => {
    if (get().running) return false;
    set({ running: true, error: null });
    try {
      const res = await fetch(`/api/pipeline/${path}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(await makeBody()),
      });
      const payload = await res.json().catch(() => null);
      if (!res.ok || !payload?.summary) {
        set({
          running: false,
          error: {
            message: payload?.error ?? `The Laya service answered ${res.status}.`,
            field: payload?.field ?? null,
          },
        });
        return false;
      }
      set({ running: false, summary: payload.summary });
      return true;
    } catch {
      set({
        running: false,
        error: { message: "Could not reach the dashboard server.", field: null },
      });
      return false;
    }
  };

  return {
  running: false,
  summary: null,
  error: null,
  scanning: false,
  showResult: false,

  run: async (knowledge, data) => {
    const upload = async (file: File) => ({ name: file.name, text: await file.text() });
    const ok = await submit("classify", async () => ({
      knowledge: await Promise.all(knowledge.map(upload)),
      data: await Promise.all(data.map(upload)),
    }));
    // A Library run was asked for in this session, so its result is shown.
    if (ok) set({ showResult: true });
    return ok;
  },

  scan: async (scene = "campus") => {
    if (get().running || get().scanning) return false;
    const started = Date.now();
    set({ scanning: true, showResult: false });
    const ok = await submit("scan", async () => ({ scene }));
    const left = SCAN_MIN_MS - (Date.now() - started);
    if (left > 0) await new Promise((resolve) => setTimeout(resolve, left));
    set({ scanning: false, showResult: ok });
    return ok;
  },

  showLastResult: () => {
    if (get().summary) set({ showResult: true });
  },

  clear: async () => {
    set({ summary: null, error: null, showResult: false });
    await fetch("/api/pipeline/context", { method: "DELETE" }).catch(() => undefined);
  },

  // Picks up a classification that outlived a page reload, or is still going.
  refresh: async () => {
    if (await pullAnalysis(set)) setTimeout(() => void get().refresh(), ANALYSIS_POLL_MS);
  },

  sync: async () => {
    await pullAnalysis(set);
  },
  };
});
