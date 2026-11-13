"use client";

import { useEffect, useRef, useState, type FC } from "react";
import { RadarIcon } from "lucide-react";

import { OpenPacketLink } from "@/components/packet";
import { SCAN_SWEEP_MS, type SiteGroup } from "@/hooks/use-analysis";
import { translateBadge, useT, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type SceneSignal = {
  id: string;
  frequency_hz: number;
  /** The site check, from GET /scene. Missing if the band table could not be read. */
  kind?: string;
  title?: string;
  triage?: SiteGroup;
};

type Scene = {
  title: string;
  badge: string;
  signals: SceneSignal[];
};

// The strip covers the band table: 88 MHz to 6 GHz, on a log scale so FM and 5.8 GHz both fit.
const LOW_HZ = 88e6;
const HIGH_HZ = 6e9;
const SWEEP_MS = SCAN_SWEEP_MS;
const HEARD_SHOWN = 6;
const TICKS = [
  { hz: 100e6, label: "100 MHz" },
  { hz: 433e6, label: "433" },
  { hz: 1e9, label: "1 GHz" },
  { hz: 1.575e9, label: "GPS" },
  { hz: 2.44e9, label: "2.4 GHz" },
  { hz: 5.8e9, label: "5.8" },
];

/** Dot color per site-check group: red needs a closer look, amber unknown, green normal. */
const DOT: Record<SiteGroup | "none", string> = {
  needs_review: "bg-rose-500 shadow-rose-500/70",
  unknown: "bg-amber-400 shadow-amber-400/70",
  expected: "bg-emerald-500 shadow-emerald-500/70",
  none: "bg-sky-400 shadow-sky-400/70",
};

/** A likely match, worded as a guess: the site check reads frequency and width, not content. */
const LIKELY_BY_KIND: Record<string, MessageKey> = {
  "Wi-Fi & Bluetooth": "likely.wifi",
  Drones: "likely.drone",
  GPS: "likely.gps",
  Aircraft: "likely.aircraft",
  Radar: "likely.radar",
  "Phone networks": "likely.phone",
  "Sensors & gadgets": "likely.sensor",
  "Radio stations": "likely.station",
  "Ham radio": "likely.ham",
  "Mystery signals": "likely.mystery",
};

function likelyKey(signal: SceneSignal): MessageKey {
  if (signal.title === "Something on GPS") return "likely.gps";
  if (signal.title === "On the restricted list") return "likely.restricted";
  if (!signal.kind) return "likely.signal";
  return LIKELY_BY_KIND[signal.kind] ?? "likely.mystery";
}

function position(hz: number) {
  const x = (Math.log(hz) - Math.log(LOW_HZ)) / (Math.log(HIGH_HZ) - Math.log(LOW_HZ));
  return Math.min(1, Math.max(0, x));
}

function formatHz(hz: number) {
  return hz >= 1e9 ? `${Number((hz / 1e9).toPrecision(4))} GHz` : `${Number((hz / 1e6).toPrecision(4))} MHz`;
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const update = () => setReduced(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

/** Elapsed milliseconds since scanning started, updated every frame while scanning. */
function useElapsed(active: boolean) {
  const [elapsed, setElapsed] = useState(0);
  const start = useRef<number | null>(null);
  useEffect(() => {
    if (!active) {
      start.current = null;
      setElapsed(0);
      return;
    }
    let frame = 0;
    const tick = (now: number) => {
      start.current ??= now;
      setElapsed(now - start.current);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active]);
  return elapsed;
}

/**
 * The front page: one Scan button, then a sweep across the spectrum while signals are found
 * and classified. It plays a built-in scene and says so in a badge; it is not a live radio.
 */
export const ScanHero: FC<{
  scanning: boolean;
  onScan: () => void;
  /** Set when an earlier result exists; shows a "See last result" link instead of jumping to it. */
  onShowLast?: () => void;
  error?: string | null;
}> = ({ scanning, onScan, onShowLast, error }) => {
  const { t, language } = useT();
  const [scene, setScene] = useState<Scene | null>(null);
  const reduced = useReducedMotion();
  const elapsed = useElapsed(scanning && !reduced);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/pipeline/scene")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data?.signals) setScene(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const signals = scene?.signals ?? [];
  const firstPassDone = reduced || elapsed >= SWEEP_MS;
  const sweep = (elapsed % SWEEP_MS) / SWEEP_MS;
  // In the order the sweep reaches them, left to right; the last one is the newest.
  const found = scanning
    ? signals
        .filter((signal) => firstPassDone || position(signal.frequency_hz) <= elapsed / SWEEP_MS)
        .sort((a, b) => position(a.frequency_hz) - position(b.frequency_hz))
    : [];
  const newest = found.at(-1);
  const heard = [...found].reverse();
  const heardHidden = Math.max(0, heard.length - HEARD_SHOWN);
  const newestX = newest ? position(newest.frequency_hz) : 0;

  return (
    <section
      aria-label={t("scan.title")}
      className="fade-in slide-in-from-bottom-1 animate-in fill-mode-both flex flex-col gap-5 duration-200 motion-reduce:animate-none"
    >
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={onScan}
          disabled={scanning}
          aria-label={scanning ? t("scan.scanning") : t("scan.title")}
          className={cn(
            "relative flex size-20 shrink-0 items-center justify-center rounded-full border-2 transition-colors outline-none focus-visible:ring-4 focus-visible:ring-ring/50 motion-reduce:transition-none",
            scanning
              ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-400"
              : "border-foreground/20 bg-muted/60 hover:border-emerald-500/60 hover:bg-emerald-500/10 hover:text-emerald-400",
          )}
        >
          {scanning && !reduced && (
            <span aria-hidden className="absolute inset-0 animate-ping rounded-full border-2 border-emerald-500/40" />
          )}
          <RadarIcon aria-hidden className={cn("size-9", scanning && !reduced && "animate-spin [animation-duration:3s]")} />
        </button>
        <div className="min-w-0">
          <p className="text-2xl font-medium tracking-tight">
            {scanning ? (firstPassDone ? t("scan.thinking") : t("scan.listening")) : t("scan.title")}
          </p>
          <p role="status" className="text-muted-foreground mt-1 text-sm">
            {scanning
              ? firstPassDone
                ? t("scan.found", { n: signals.length })
                : t("scan.listeningAt", { site: scene?.title ?? t("scan.thisSite") })
              : t("scan.intro")}
          </p>
        </div>
      </div>

      <div>
        <div
          className="bg-muted/50 relative h-16 w-full overflow-hidden rounded-xl border"
          role="img"
          aria-label={scanning ? t("scan.spectrumFound", { n: found.length }) : t("scan.spectrum")}
        >
          {TICKS.map((tick) => (
            <span
              key={tick.label}
              aria-hidden
              className="border-foreground/10 absolute top-0 bottom-0 border-l"
              style={{ left: `${position(tick.hz) * 100}%` }}
            />
          ))}
          {found.map((signal) => (
            <span
              key={signal.id}
              aria-hidden
              className={cn(
                "fade-in zoom-in-50 animate-in absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full shadow-[0_0_10px] duration-300 motion-reduce:animate-none",
                DOT[signal.triage ?? "none"],
                signal === newest && "ring-background ring-2",
              )}
              style={{ left: `${position(signal.frequency_hz) * 100}%` }}
            />
          ))}
          {newest && (
            // Only the newest dot is named on the strip, so labels never overlap.
            <span
              key={newest.id}
              aria-hidden
              className={cn(
                "fade-in animate-in bg-background/90 absolute top-1.5 max-w-[60%] truncate rounded-md border px-1.5 py-0.5 text-[11px] leading-tight whitespace-nowrap shadow-sm duration-200 motion-reduce:animate-none",
                newestX < 0.15 ? "translate-x-0" : newestX > 0.85 ? "-translate-x-full" : "-translate-x-1/2",
              )}
              style={{ left: `${newestX * 100}%` }}
            >
              {t(likelyKey(newest))}
            </span>
          )}
          {scanning && !reduced && (
            <span
              aria-hidden
              className="absolute top-0 bottom-0 w-px bg-emerald-400 shadow-[0_0_12px_2px] shadow-emerald-400/60"
              style={{ left: `${sweep * 100}%` }}
            />
          )}
        </div>
        <div aria-hidden className="text-muted-foreground relative mt-1 h-4 text-[11px]">
          {TICKS.map((tick) => (
            <span
              key={tick.label}
              className="absolute -translate-x-1/2 whitespace-nowrap"
              style={{ left: `${position(tick.hz) * 100}%` }}
            >
              {tick.label}
            </span>
          ))}
        </div>

        {/* Always mounted, so screen readers hear each signal as it is added. */}
        <div aria-live="polite" className="mt-3">
          {heard.length > 0 && (
            <>
              <h3 className="text-muted-foreground mb-1.5 text-xs font-medium tracking-wide uppercase">
                {t("scan.heard")}
              </h3>
              <ul className="flex flex-col gap-1">
                {heard.slice(0, HEARD_SHOWN).map((signal) => (
                  <li
                    key={signal.id}
                    className="fade-in slide-in-from-top-1 animate-in flex items-center gap-2 text-sm duration-200 motion-reduce:animate-none"
                  >
                    <span aria-hidden className={cn("size-2 shrink-0 rounded-full", DOT[signal.triage ?? "none"])} />
                    <span className="min-w-0 truncate">{t(likelyKey(signal))}</span>
                    {signal.triage && <span className="sr-only">, {t(`group.${signal.triage}`)}</span>}
                    <span className="text-muted-foreground ms-auto shrink-0 text-xs tabular-nums">
                      {formatHz(signal.frequency_hz)}
                    </span>
                  </li>
                ))}
              </ul>
              {heardHidden > 0 && (
                <p className="text-muted-foreground mt-1 text-xs">{t("scan.more", { n: heardHidden })}</p>
              )}
            </>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {!scanning && (
          <button
            type="button"
            onClick={onScan}
            className="bg-foreground text-background rounded-full px-5 py-2 text-sm font-medium transition-opacity hover:opacity-90 motion-reduce:transition-none"
          >
            {t("scan.start")}
          </button>
        )}
        {!scanning && <OpenPacketLink />}
        {!scanning && onShowLast && (
          <button
            type="button"
            onClick={onShowLast}
            className="text-foreground text-sm underline-offset-2 hover:underline"
          >
            {t("scan.seeLast")}
          </button>
        )}
        {scene && (
          <span className="text-muted-foreground rounded-full border px-3 py-1 text-xs">
            {translateBadge(scene.badge, language)}
          </span>
        )}
      </div>

      {error && !scanning && (
        <p role="alert" className="text-sm text-rose-400">
          {error}
        </p>
      )}
    </section>
  );
};
