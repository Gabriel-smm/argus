"use client";

import { useState, type FC, type ReactNode } from "react";
import { CircleHelpIcon, ShieldAlertIcon, ShieldCheckIcon } from "lucide-react";

import type { SiteGroup, SiteReport as SiteReportData } from "@/hooks/use-analysis";
import { LocationLine } from "@/components/location-line";
import { translateKind, translateTitle, useT, type MessageKey } from "@/lib/i18n";
import { hasGpsInterference, type SensorLocation } from "@/lib/packet";
import { cn } from "@/lib/utils";

/** How each site-check group looks: one color family per group, used everywhere on the card. */
const GROUP_STYLE: Record<SiteGroup, { dot: string; bar: string; text: string }> = {
  needs_review: { dot: "bg-rose-500", bar: "bg-rose-500", text: "text-rose-400" },
  unknown: { dot: "bg-amber-400", bar: "bg-amber-400", text: "text-amber-300" },
  expected: { dot: "bg-emerald-500", bar: "bg-emerald-500", text: "text-emerald-400" },
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

/**
 * The verdict in the chosen language. Rebuilt from the counts with the same wording as
 * build_site_report in pipeline/context.py, so it can be translated.
 */
function verdictText(report: SiteReportData, t: (key: MessageKey, vars?: Record<string, string | number>) => string) {
  const site = report.site;
  if (report.verdict === "review") {
    const n = report.counts.needs_review;
    const form = n === 1 ? "one" : "other";
    return { headline: t(`verdict.review.${form}`, { n }), explain: t(`explain.review.${form}`, { n, site }) };
  }
  if (report.verdict === "unknown") {
    const n = report.counts.unknown;
    return { headline: t("verdict.unknown"), explain: t(n === 1 ? "explain.unknown.one" : "explain.unknown.other", { n }) };
  }
  return { headline: t("verdict.normal"), explain: t("explain.normal", { site }) };
}

/** The site check at a glance: one verdict and what is in the air. Details open per category. */
export const SiteReport: FC<{
  report: SiteReportData;
  /** The sensor's location from the site profile, shown above the verdict. */
  location?: SensorLocation | null;
  actions?: ReactNode;
}> = ({ report, location, actions }) => {
  const { t, language } = useT();
  const [openKind, setOpenKind] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const verdict = VERDICT_STYLE[report.verdict];
  const { headline, explain } = verdictText(report, t);
  const inKind = openKind ? report.signals.filter((item) => item.kind === openKind) : [];
  const shown = showAll ? inKind : inKind.slice(0, SHOWN_FIRST);
  const hidden = inKind.length - shown.length;
  const label = (group: SiteGroup) => t(`group.${group}`);

  const toggle = (kind: string) => {
    setShowAll(false);
    setOpenKind((current) => (current === kind ? null : kind));
  };

  return (
    <section
      aria-label={t("report.label")}
      className="fade-in slide-in-from-bottom-1 animate-in fill-mode-both flex flex-col gap-5 duration-200 motion-reduce:animate-none"
    >
      {location && <LocationLine location={location} gpsInterference={hasGpsInterference(report.signals)} />}

      <div role="status" className={cn("flex items-start gap-4 rounded-2xl border p-4", verdict.ring)}>
        <verdict.Icon aria-hidden className={cn("mt-0.5 size-9 shrink-0", verdict.icon)} strokeWidth={1.75} />
        <div className="min-w-0">
          <p className="text-2xl font-medium tracking-tight">{headline}</p>
          <p className="text-muted-foreground mt-1 text-sm">{explain}</p>
        </div>
      </div>

      <div>
        <div
          className="bg-muted flex h-3 w-full overflow-hidden rounded-full"
          role="img"
          aria-label={GROUP_ORDER.map((group) => `${report.counts[group]} ${label(group)}`).join(", ")}
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
              {label(group).toLocaleLowerCase(language)}
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h3 className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">
          {t("report.inAir")}
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
                  <span className="leading-tight">{translateKind(entry.kind, language)}</span>
                  <span className="sr-only">{t("report.worst", { group: label(entry.worst) })}</span>
                </span>
                <span className="text-muted-foreground tabular-nums">{entry.count}</span>
              </button>
            );
          })}
        </div>

        <div id="site-report-details" aria-live="polite" className="mt-3">
          {openKind === null ? (
            <p className="text-muted-foreground text-xs">
              {report.verdict === "normal" ? t("report.hint") : t("report.hintRed")}
            </p>
          ) : (
            <div className="fade-in animate-in duration-150 motion-reduce:animate-none">
              {language !== "en" && (
                <p className="text-muted-foreground mb-2 text-xs italic">{t("report.detailsInEnglish")}</p>
              )}
              <ul className="flex flex-col gap-2">
                {shown.map((item) => (
                  <li key={item.id} className="bg-muted/40 rounded-lg px-3 py-2.5">
                    <p className="flex flex-wrap items-center gap-x-2 text-sm">
                      <span aria-hidden className={cn("size-2 shrink-0 rounded-full", GROUP_STYLE[item.group].dot)} />
                      <span className="font-medium">{translateTitle(item.title, language)}</span>
                      <span className={cn("text-xs", GROUP_STYLE[item.group].text)}>{label(item.group)}</span>
                      {item.protected && <span className="text-xs text-sky-300">{t("report.safety")}</span>}
                      <span className="text-muted-foreground ms-auto text-xs">{t("report.signal", { id: item.id })}</span>
                    </p>
                    <p lang="en" className="text-muted-foreground mt-1 text-xs leading-relaxed">
                      {item.reason}
                    </p>
                    <p className="mt-1 text-xs leading-relaxed">
                      <span className="text-muted-foreground">{t("report.next")}</span>
                      <span lang="en">{item.check_next}</span>
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
                  {t("report.showMore", { n: hidden })}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {actions}
    </section>
  );
};
