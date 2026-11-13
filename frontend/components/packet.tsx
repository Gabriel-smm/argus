"use client";

import { useRef, useState, type FC } from "react";
import { FileUpIcon, PackageIcon, XIcon } from "lucide-react";
import { create } from "zustand";

import { SiteReport } from "@/components/site-report";
import type { AnalysisSummary, SiteReport as SiteReportData } from "@/hooks/use-analysis";
import { translateBadge, useT } from "@/lib/i18n";
import {
  openPacket,
  packetBody,
  packetFileName,
  reportFromPacket,
  sealPacket,
  type Packet,
} from "@/lib/packet";

const SHORT_PRINT = 8;

/** "Package for HQ": builds the packet, fingerprints it and saves it, all in the browser. */
export const PacketExport: FC<{ summary: AnalysisSummary }> = ({ summary }) => {
  const { t, language } = useT();
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState<{ signals: number; kb: string; print: string } | null>(null);
  const [failed, setFailed] = useState(false);

  const save = async () => {
    setBusy(true);
    setFailed(false);
    try {
      const createdAt = new Date();
      const packet = await sealPacket(packetBody(summary, createdAt));
      const text = JSON.stringify(packet, null, 2);
      const blob = new Blob([text], { type: "application/json" });
      // A local download: the file never leaves this computer unless someone moves it.
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = packetFileName(packet.site.name, createdAt);
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      setReady({
        signals: packet.signals.length,
        kb: (blob.size / 1024).toLocaleString(language, { maximumFractionDigits: 1 }),
        print: packet.fingerprint.value.slice(0, SHORT_PRINT),
      });
    } catch {
      setReady(null);
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <button
        type="button"
        onClick={() => void save()}
        disabled={busy}
        className="hover:bg-muted/70 focus-visible:ring-ring/50 flex items-center gap-2 rounded-full border px-4 py-1.5 font-medium transition-colors outline-none focus-visible:ring-2 disabled:opacity-60 motion-reduce:transition-none"
      >
        <PackageIcon aria-hidden className="size-4" />
        {busy ? t("packet.exporting") : t("packet.export")}
      </button>
      <p role="status" className="text-muted-foreground text-xs">
        {ready && (
          <>
            {t("packet.ready", { n: ready.signals, size: ready.kb })}
            {" · "}
            <span className="font-mono">{t("packet.fingerprint", { fp: ready.print })}</span>
          </>
        )}
      </p>
      {failed && (
        <p role="alert" className="text-xs text-rose-400">
          {t("packet.failed")}
        </p>
      )}
    </div>
  );
};

type PacketViewState = {
  opened: { packet: Packet; report: SiteReportData } | null;
  problem: "changed" | "not_a_packet" | null;
  open: (file: File) => Promise<void>;
  close: () => void;
};

/** A packet opened at HQ. View-only: it never touches the Laya service's current result. */
export const usePacketView = create<PacketViewState>((set) => ({
  opened: null,
  problem: null,
  open: async (file) => {
    let text: string;
    try {
      text = await file.text();
    } catch {
      set({ opened: null, problem: "not_a_packet" });
      return;
    }
    const result = await openPacket(text).catch(() => ({ ok: false as const, reason: "not_a_packet" as const }));
    if (result.ok) set({ opened: { packet: result.packet, report: reportFromPacket(result.packet) }, problem: null });
    else set({ opened: null, problem: result.reason });
  },
  close: () => set({ opened: null, problem: null }),
}));

/** "Open a packet" on the front page: pick an argus-packet file from this computer. */
export const OpenPacketLink: FC = () => {
  const { t } = useT();
  const open = usePacketView((s) => s.open);
  const problem = usePacketView((s) => s.problem);
  const input = useRef<HTMLInputElement>(null);

  return (
    <>
      <button
        type="button"
        onClick={() => input.current?.click()}
        className="text-foreground flex items-center gap-1.5 text-sm underline-offset-2 hover:underline"
      >
        <FileUpIcon aria-hidden className="size-4" />
        {t("packet.open")}
      </button>
      <input
        ref={input}
        type="file"
        accept=".json,application/json"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void open(file);
        }}
      />
      {problem && (
        <p role="alert" className="basis-full text-sm text-rose-400">
          {problem === "changed" ? t("packet.changed") : t("packet.invalid")}
        </p>
      )}
    </>
  );
};

/** The same site report card, from an opened packet, under a banner saying where it came from. */
export const PacketView: FC<{ packet: Packet; report: SiteReportData; onClose: () => void }> = ({
  packet,
  report,
  onClose,
}) => {
  const { t, language } = useT();
  const created = new Date(packet.created_at).toLocaleString(language, { dateStyle: "medium", timeStyle: "short" });

  return (
    <div className="flex flex-col gap-4">
      <div
        role="status"
        className="flex items-start gap-3 rounded-xl border border-sky-400/40 bg-sky-400/10 px-4 py-3 text-sm"
      >
        <PackageIcon aria-hidden className="mt-0.5 size-4 shrink-0 text-sky-300" />
        <div className="min-w-0 flex-1">
          <p>
            {t("packet.openedFrom", {
              fp: packet.fingerprint.value.slice(0, SHORT_PRINT),
              time: created,
              site: packet.site.name,
            })}
          </p>
          <p className="text-muted-foreground mt-1 text-xs">{translateBadge(packet.data_source, language)}</p>
          <p className="text-muted-foreground mt-1 text-xs">{t("packet.viewOnly")}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("packet.close")}
          title={t("packet.close")}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 rounded-md p-1 outline-none focus-visible:ring-2"
        >
          <XIcon aria-hidden className="size-4" />
        </button>
      </div>
      <SiteReport report={report} />
    </div>
  );
};
