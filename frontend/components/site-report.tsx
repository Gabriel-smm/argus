"use client";

import { useState, type FC } from "react";
import { CircleHelpIcon, ShieldAlertIcon, ShieldCheckIcon } from "lucide-react";

import type { SiteGroup, SiteReport as SiteReportData } from "@/hooks/use-analysis";
import { cn } from "@/lib/utils";

/** How each site-check group looks: one color family per group, used everywhere on the card. */
const GROUP_STYLE: Record<SiteGroup, { label: string; dot: string; bar: string; text: string }> = {
  needs_review: {
    label: "Needs a closer look",
    dot: "bg-rose-500",
    bar: "bg-rose-500",
    text: "text-rose-400",
  },
  unknown: {
    label: "Unknown",
    dot: "bg-amber-400",
    bar: "bg-amber-400",
    text: "text-amber-300",
  },
  expected: {
    label: "Normal here",
    dot: "bg-emerald-500",
    bar: "bg-emerald-500",
    text: "text-emerald-400",
  },
};

const GROUP_ORDER: SiteGroup[] = ["needs_review", "unknown", "expected"];

const VERDICT_STYLE = {
  review: {
    Icon: ShieldAlertIcon,
    ring: "border-rose-500/40 bg-rose-500/10",
    icon: "text-rose-400",
  },
  unknown: {
    Icon: CircleHelpIcon,
    ring: "border-amber-400/40 bg-amber-400/10",
    icon: "text-amber-300",
  },
  normal: {
    Icon: ShieldCheckIcon,
    ring: "border-emerald-500/40 bg-emerald-500/10",
    icon: "text-emerald-400",
  },
} as const;

const SHOWN_FIRST = 3;

/** The site check at a glance: one verdict and what is in the air. Details open per category. */
export const SiteReport: FC<{ report: SiteReportData }> = ({ report }) => {
  const [openKind, setOpenKind] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const verdict = VERDICT_STYLE[report.verdict];
  const inKind = openKind ? report.signals.filter((item) => item.kind === openKind) : [];
  const shown = showAll ? inKind : inKind.slice(0, SHOWN_FIRST);
  const hidden = inKind.length - shown.length;

  const toggle = (kind: string) => {
    setShowAll(false);
    setOpenKind((current) => (current === kind ? null : kind));
  };

  return (
    <section
      aria-label="Site report"
      className="fade-in slide-in-from-bottom-1 animate-in fill-mode-both flex flex-col gap-5 duration-200"
    >
      <div role="status" className={cn("flex items-start gap-4 rounded-2xl border p-4", verdict.ring)}>
        <verdict.Icon aria-hidden className={cn("mt-0.5 size-9 shrink-0", verdict.icon)} strokeWidth={1.75} />
        <div className="min-w-0">
          <p className="text-2xl font-medium tracking-tight">{report.headline}</p>
          <p className="text-muted-foreground mt-1 text-sm">{report.explain}</p>
        </div>
      </div>

      <div>
        <div
          className="bg-muted flex h-3 w-full overflow-hidden rounded-full"
          role="img"
          aria-label={GROUP_ORDER.map((group) => `${report.counts[group]} ${GROUP_STYLE[group].label}`).join(", ")}
        >
          {GROUP_ORDER.map((group) =>
            report.counts[group] > 0 ? (
              <div
                key={group}
                className={cn("h-full", GROUP_STYLE[group].bar)}
                style={{ width: `${(report.counts[group] / report.total) * 100}%` }}
              />
            ) : null,
          )}
        </div>
        <ul className="text-muted-foreground mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {GROUP_ORDER.map((group) => (
            <li key={group} className="flex items-center gap-1.5">
              <span aria-hidden className={cn("size-2 rounded-full", GROUP_STYLE[group].dot)} />
              <span className="text-foreground font-medium tabular-nums">{report.counts[group]}</span>
              {GROUP_STYLE[group].label.toLowerCase()}
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h3 className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">
          What&apos;s in the air
        </h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {report.kinds.map((entry) => {
            const open = openKind === entry.kind;
            return (
              <button
                key={entry.kind}
                type="button"
                aria-pressed={open}
                aria-controls="site-report-details"
                onClick={() => toggle(entry.kind)}
                className={cn(
                  "flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-start text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50 motion-reduce:transition-none",
                  open
                    ? "border-foreground/30 bg-muted"
                    : "bg-muted/40 hover:bg-muted/70 border-transparent",
                )}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden
                    className={cn("size-2 shrink-0 rounded-full", GROUP_STYLE[entry.worst].dot)}
                  />
                  <span className="leading-tight">{entry.kind}</span>
                  <span className="sr-only">, worst: {GROUP_STYLE[entry.worst].label}</span>
                </span>
                <span className="text-muted-foreground tabular-nums">{entry.count}</span>
              </button>
            );
          })}
        </div>

        <div id="site-report-details" aria-live="polite" className="mt-3">
          {openKind === null ? (
            <p className="text-muted-foreground text-xs">
              {report.verdict === "normal"
                ? "Tap a tile to see the signals behind it."
                : "Tap a tile to see the signals behind it. Start with the red ones."}
            </p>
          ) : (
            <div className="fade-in animate-in duration-150">
              <ul className="flex flex-col gap-2">
                {shown.map((item) => (
                  <li key={item.id} className="bg-muted/40 rounded-lg px-3 py-2.5">
                    <p className="flex flex-wrap items-center gap-x-2 text-sm">
                      <span aria-hidden className={cn("size-2 shrink-0 rounded-full", GROUP_STYLE[item.group].dot)} />
                      <span className="font-medium">{item.title}</span>
                      <span className={cn("text-xs", GROUP_STYLE[item.group].text)}>
                        {GROUP_STYLE[item.group].label}
                      </span>
                      {item.protected && (
                        <span className="text-xs text-sky-300">Safety band: listen only</span>
                      )}
                      <span className="text-muted-foreground ms-auto text-xs">signal {item.id}</span>
                    </p>
                    <p className="text-muted-foreground mt-1 text-xs leading-relaxed">{item.reason}</p>
                    <p className="mt-1 text-xs leading-relaxed">
                      <span className="text-muted-foreground">Next: </span>
                      {item.check_next}
                    </p>
                  </li>
                ))}
              </ul>
              {hidden > 0 && (
                <button
                  type="button"
                  onClick={() => setShowAll(true)}
                  className="text-foreground mt-2 text-xs underline-offset-2 hover:underline"
                >
                  Show {hidden} more
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
};
