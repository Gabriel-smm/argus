/**
 * The field-to-HQ packet: one JSON file holding a triaged result, made and checked entirely
 * in the browser. No network call is made here.
 *
 * The fingerprint is a sha256 of the packet's contents (every field but `fingerprint`),
 * written as JSON with keys in sorted order, so re-indenting the file does not break it
 * but changing any value does. It shows a packet was not changed by accident or on the
 * way; it is not a signature, so it cannot prove who made the packet.
 */
import type { AnalysisSummary, SiteGroup, SiteReport } from "@/hooks/use-analysis";

export const PACKET_VERSION = "0.1";
const GROUPS: SiteGroup[] = ["needs_review", "unknown", "expected"];
const VERDICTS = ["review", "unknown", "normal"] as const;

export type PacketSignal = {
  id: string;
  group: SiteGroup;
  title: string;
  kind: string;
  reason: string;
  check_next: string;
  protected: boolean;
};

/**
 * Where the sensor is. Always from the site profile: never a GPS fix and never the browser's
 * geolocation, which can go online.
 */
export type SensorLocation = { name: string; latitude?: number; longitude?: number; source: "site_profile" };

/** The site check's title for any signal seen on GPS L1 (pipeline/lookup.py). */
export const GPS_TITLE = "Something on GPS";

/** True if any signal is on GPS: a nearby GPS receiver's position may be off. */
export const hasGpsInterference = (signals: readonly { title?: string }[]) =>
  signals.some((item) => item.title === GPS_TITLE);

/** The sensor location behind a result, from what the Laya service recorded. */
export function locationFromSummary(summary: AnalysisSummary): SensorLocation | null {
  const site = summary.provenance?.site;
  if (site) return { name: site.name, latitude: site.latitude, longitude: site.longitude, source: "site_profile" };
  const name = summary.site_report?.site;
  return name ? { name, source: "site_profile" } : null;
}

export type PacketBody = {
  packet_version: typeof PACKET_VERSION;
  created_at: string;
  site: { name: string; latitude?: number; longitude?: number; radius_km?: number; frequency_list?: string };
  /** The sensor's location and where it came from, plus whether GPS interference was seen. */
  location?: SensorLocation & { gps_interference_nearby: boolean };
  /** The demo badge for built-in scenes, so demo data is never mistaken for a real recording. */
  data_source: string;
  versions: { band_table: string | null; site_profile: string | null; model: string | null };
  verdict: { code: SiteReport["verdict"]; headline: string };
  counts: Record<SiteGroup, number>;
  signals: PacketSignal[];
};

export type Packet = PacketBody & { fingerprint: { algorithm: "sha256"; value: string } };

/** JSON with object keys sorted at every level: the same contents always give the same text. */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export async function sha256Hex(text: string): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error("This browser cannot compute a fingerprint here.");
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** The packet's contents, from a summary that has a site report. */
export function packetBody(summary: AnalysisSummary, createdAt: Date): PacketBody {
  const report = summary.site_report;
  if (!report) throw new Error("This result has no site report to package.");
  const found = summary.provenance;
  const signals = [...report.signals]
    .sort((a, b) => GROUPS.indexOf(a.group) - GROUPS.indexOf(b.group))
    .map((item) => ({
      id: item.id,
      group: item.group,
      title: item.title,
      kind: item.kind,
      reason: item.reason,
      check_next: item.check_next,
      protected: item.protected,
    }));
  const location = locationFromSummary(summary) ?? { name: report.site, source: "site_profile" as const };
  return {
    packet_version: PACKET_VERSION,
    created_at: createdAt.toISOString(),
    site: found?.site ?? { name: report.site },
    location: { ...location, gps_interference_nearby: hasGpsInterference(signals) },
    data_source: summary.scene?.badge ?? `Files: ${summary.data_name}`,
    versions: {
      band_table: found?.versions.band_table ?? null,
      site_profile: found?.versions.site_profile ?? null,
      model: found?.versions.model ?? null,
    },
    verdict: { code: report.verdict, headline: report.headline },
    counts: report.counts,
    signals,
  };
}

export async function sealPacket(body: PacketBody): Promise<Packet> {
  return { ...body, fingerprint: { algorithm: "sha256", value: await sha256Hex(canonicalJson(body)) } };
}

/** argus-packet-<site>-<YYYY-MM-DD-HHmm>.json, in local time. */
export function packetFileName(siteName: string, createdAt: Date) {
  const slug =
    siteName
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "site";
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp =
    `${createdAt.getFullYear()}-${pad(createdAt.getMonth() + 1)}-${pad(createdAt.getDate())}` +
    `-${pad(createdAt.getHours())}${pad(createdAt.getMinutes())}`;
  return `argus-packet-${slug}-${stamp}.json`;
}

export type OpenResult =
  | { ok: true; packet: Packet }
  | { ok: false; reason: "not_a_packet" | "changed" };

const isString = (value: unknown): value is string => typeof value === "string";
const isCount = (value: unknown) => typeof value === "number" && Number.isInteger(value) && value >= 0;

function isSignal(value: unknown): value is PacketSignal {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    isString(item.id) &&
    GROUPS.includes(item.group as SiteGroup) &&
    isString(item.title) &&
    isString(item.kind) &&
    isString(item.reason) &&
    isString(item.check_next) &&
    typeof item.protected === "boolean"
  );
}

const isOptionalNumber = (value: unknown) => value === undefined || (typeof value === "number" && Number.isFinite(value));

/** Packets made before the location field existed have none; that is fine. */
function isLocationOrMissing(value: unknown) {
  if (value === undefined) return true;
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    isString(item.name) &&
    item.source === "site_profile" &&
    isOptionalNumber(item.latitude) &&
    isOptionalNumber(item.longitude) &&
    typeof item.gps_interference_nearby === "boolean"
  );
}

/** Check a packet's shape and fingerprint. A packet that fails either is not shown. */
export async function openPacket(text: string): Promise<OpenResult> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, reason: "not_a_packet" };
  }
  if (!parsed || typeof parsed !== "object") return { ok: false, reason: "not_a_packet" };
  const { fingerprint, ...body } = parsed as Record<string, unknown>;
  const value = (fingerprint as { value?: unknown } | undefined)?.value;
  const looksLikePacket =
    body.packet_version === PACKET_VERSION &&
    isString(value) &&
    isString(body.created_at) &&
    isString((body.site as { name?: unknown } | undefined)?.name) &&
    Array.isArray(body.signals);
  if (!looksLikePacket) return { ok: false, reason: "not_a_packet" };
  if ((await sha256Hex(canonicalJson(body))) !== value) return { ok: false, reason: "changed" };

  // The fingerprint matches; still check every field the card reads before showing it.
  const counts = body.counts as Record<string, unknown> | undefined;
  const verdict = body.verdict as { code?: unknown; headline?: unknown } | undefined;
  const valid =
    isLocationOrMissing(body.location) &&
    (body.signals as unknown[]).every(isSignal) &&
    !!counts &&
    GROUPS.every((group) => isCount(counts[group])) &&
    VERDICTS.includes(verdict?.code as (typeof VERDICTS)[number]) &&
    isString(verdict?.headline) &&
    isString(body.data_source) &&
    !Number.isNaN(Date.parse(body.created_at as string));
  if (!valid) return { ok: false, reason: "not_a_packet" };
  return { ok: true, packet: parsed as Packet };
}

/** The site report card's data, rebuilt from a packet the same way the Laya service builds it. */
export function reportFromPacket(packet: Packet): SiteReport {
  const kinds = new Map<string, { kind: string; count: number; worst: SiteGroup }>();
  for (const item of packet.signals) {
    const entry = kinds.get(item.kind) ?? { kind: item.kind, count: 0, worst: "expected" as SiteGroup };
    entry.count += 1;
    if (GROUPS.indexOf(item.group) < GROUPS.indexOf(entry.worst)) entry.worst = item.group;
    kinds.set(item.kind, entry);
  }
  const flagged = packet.signals.filter((item) => item.group !== "expected");
  return {
    site: packet.site.name,
    verdict: packet.verdict.code,
    headline: packet.verdict.headline,
    explain: "",
    counts: packet.counts,
    total: packet.signals.length,
    kinds: [...kinds.values()].sort(
      (a, b) => GROUPS.indexOf(a.worst) - GROUPS.indexOf(b.worst) || b.count - a.count,
    ),
    flagged,
    more_flagged: 0,
    signals: packet.signals,
    questions: [],
  };
}
