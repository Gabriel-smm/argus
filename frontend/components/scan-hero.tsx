"use client";

import { useEffect, useRef, useState, type FC } from "react";
import { RadarIcon } from "lucide-react";

import { cn } from "@/lib/utils";

type Scene = {
  title: string;
  badge: string;
  signals: { id: string; frequency_hz: number }[];
};

// The strip covers the band table: 88 MHz to 6 GHz, on a log scale so FM and 5.8 GHz both fit.
const LOW_HZ = 88e6;
const HIGH_HZ = 6e9;
const SWEEP_MS = 3200;
const TICKS = [
  { hz: 100e6, label: "100 MHz" },
  { hz: 433e6, label: "433" },
  { hz: 1e9, label: "1 GHz" },
  { hz: 1.575e9, label: "GPS" },
  { hz: 2.44e9, label: "2.4 GHz" },
  { hz: 5.8e9, label: "5.8" },
];

function position(hz: number) {
  const x = (Math.log(hz) - Math.log(LOW_HZ)) / (Math.log(HIGH_HZ) - Math.log(LOW_HZ));
  return Math.min(1, Math.max(0, x));
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
  error?: string | null;
}> = ({ scanning, onScan, error }) => {
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
  const found = scanning
    ? signals.filter((signal) => firstPassDone || position(signal.frequency_hz) <= elapsed / SWEEP_MS)
    : [];

  return (
    <section
      aria-label="Scan the area"
      className="fade-in slide-in-from-bottom-1 animate-in fill-mode-both flex flex-col gap-5 duration-200"
    >
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={onScan}
          disabled={scanning}
          aria-label={scanning ? "Scanning" : "Scan the area"}
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
            {scanning ? (firstPassDone ? "Making sense of it…" : "Listening…") : "Scan the area"}
          </p>
          <p role="status" className="text-muted-foreground mt-1 text-sm">
            {scanning
              ? firstPassDone
                ? `Found ${signals.length} signals. Checking what each one is and whether it belongs here.`
                : `Listening from 88 MHz to 6 GHz at ${scene?.title ?? "this site"}.`
              : "Argus listens to the airwaves and tells you what is normal here, what is not, and what to check next."}
          </p>
        </div>
      </div>

      <div>
        <div
          className="bg-muted/50 relative h-16 w-full overflow-hidden rounded-xl border"
          role="img"
          aria-label={
            scanning
              ? `Spectrum from 88 MHz to 6 GHz, ${found.length} signals found so far`
              : "Spectrum from 88 MHz to 6 GHz"
          }
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
              className="fade-in zoom-in-50 animate-in absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-sky-400 shadow-[0_0_10px] shadow-sky-400/70 duration-300"
              style={{ left: `${position(signal.frequency_hz) * 100}%` }}
            />
          ))}
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
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {!scanning && (
          <button
            type="button"
            onClick={onScan}
            className="bg-foreground text-background rounded-full px-5 py-2 text-sm font-medium transition-opacity hover:opacity-90 motion-reduce:transition-none"
          >
            Start scan
          </button>
        )}
        {scene && (
          <span className="text-muted-foreground rounded-full border px-3 py-1 text-xs">{scene.badge}</span>
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
