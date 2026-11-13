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
  run: (knowledge: File[], data: File[]) => Promise<boolean>;
  /** Run a built-in scene (no uploads), for the Scan button. */
  scan: (scene?: string) => Promise<boolean>;
  clear: () => Promise<void>;
  refresh: () => Promise<void>;
  /** Read the pipeline once, without scheduling another read. */
  sync: () => Promise<void>;
};

export const ANALYSIS_POLL_MS = 2000;

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

  run: async (knowledge, data) => {
    const upload = async (file: File) => ({ name: file.name, text: await file.text() });
    return submit("classify", async () => ({
      knowledge: await Promise.all(knowledge.map(upload)),
      data: await Promise.all(data.map(upload)),
    }));
  },

  scan: async (scene = "campus") => submit("scan", async () => ({ scene })),

  clear: async () => {
    set({ summary: null, error: null });
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
