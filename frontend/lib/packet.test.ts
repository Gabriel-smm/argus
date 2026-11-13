// Run with `npm test` (Node's test runner through tsx). No browser, network or Laya needed.
import assert from "node:assert/strict";
import { test } from "node:test";

import type { AnalysisSummary } from "../hooks/use-analysis";
import {
  canonicalJson,
  openPacket,
  packetBody,
  packetFileName,
  reportFromPacket,
  sealPacket,
} from "./packet";

const signal = (id: string, group: "needs_review" | "unknown" | "expected", kind: string) => ({
  id,
  group,
  title: group === "expected" ? "Normal here" : "Possible drone",
  kind,
  reason: `Reason ${id}`,
  check_next: `Check ${id}`,
  protected: false,
});

const summary = {
  knowledge_name: "data-full.json",
  data_name: "observations-site-demo.jsonl",
  observations: 3,
  scene: { title: "Notre Dame campus", badge: "Demo mode: sample campus signals, not a live radio" },
  provenance: {
    site: { name: "Notre Dame campus (demo site)", latitude: 41.703, longitude: -86.239 },
    versions: { band_table: "bands.csv sha256:aaa", site_profile: "site.json sha256:bbb", model: "laya-rf-modes" },
  },
  site_report: {
    site: "Notre Dame campus (demo site)",
    verdict: "review",
    headline: "1 signal needs a closer look",
    explain: "",
    counts: { needs_review: 1, unknown: 1, expected: 1 },
    total: 3,
    kinds: [],
    flagged: [],
    more_flagged: 0,
    // Not worst-first on purpose: the packet must reorder them.
    signals: [signal("0", "expected", "Wi-Fi & Bluetooth"), signal("1", "unknown", "Drones"), signal("2", "needs_review", "Drones")],
    questions: [],
  },
} as unknown as AnalysisSummary;

const when = new Date(2026, 10, 12, 9, 5);

test("a packet holds the site, the demo badge, versions and every signal, closer look first", () => {
  const body = packetBody(summary, when);
  assert.equal(body.packet_version, "0.1");
  assert.equal(body.created_at, when.toISOString());
  assert.deepEqual(body.site, { name: "Notre Dame campus (demo site)", latitude: 41.703, longitude: -86.239 });
  assert.match(body.data_source, /^Demo mode/);
  assert.deepEqual(body.versions, { band_table: "bands.csv sha256:aaa", site_profile: "site.json sha256:bbb", model: "laya-rf-modes" });
  assert.deepEqual(body.verdict, { code: "review", headline: "1 signal needs a closer look" });
  assert.deepEqual(body.signals.map((item) => item.group), ["needs_review", "unknown", "expected"]);
  assert.deepEqual(Object.keys(body.signals[0]).sort(), ["check_next", "group", "id", "kind", "protected", "reason", "title"]);
});

test("a packet records the sensor location, its source, and GPS interference", () => {
  assert.deepEqual(packetBody(summary, when).location, {
    name: "Notre Dame campus (demo site)",
    latitude: 41.703,
    longitude: -86.239,
    source: "site_profile",
    gps_interference_nearby: false,
  });
  const withGps = structuredClone(summary);
  withGps.site_report!.signals[1].title = "Something on GPS";
  assert.equal(packetBody(withGps, when).location?.gps_interference_nearby, true);
});

test("without recorded coordinates the location still names the site", () => {
  const bare = { ...summary, provenance: null } as AnalysisSummary;
  assert.deepEqual(packetBody(bare, when).location, {
    name: "Notre Dame campus (demo site)",
    source: "site_profile",
    gps_interference_nearby: false,
  });
});

test("a packet made before the location field still opens; a bad location does not", async () => {
  const { location: _dropped, ...older } = packetBody(summary, when);
  assert.ok((await openPacket(JSON.stringify(await sealPacket(older)))).ok);
  const body = packetBody(summary, when);
  const bad = await sealPacket({ ...body, location: { ...body.location!, source: "gps" as "site_profile" } });
  assert.deepEqual(await openPacket(JSON.stringify(bad)), { ok: false, reason: "not_a_packet" });
});

test("a jamming result keeps its assessment through a packet", async () => {
  const jammed = structuredClone(summary);
  const report = jammed.site_report!;
  const assessment = { flagged: true, reason: "Noise floor rose 18 dB.", noise_rise_db: 18, expected_missing: ["sensor bursts"] };
  report.jamming = assessment;
  report.counts = { needs_review: 0, unknown: 1, expected: 0 };
  report.signals = [
    { id: "jamming", group: "needs_review", title: "Possible jamming", kind: "Jamming", reason: "r", check_next: "c", protected: false },
    signal("d1", "unknown", "Mystery signals"),
  ];
  const packet = await sealPacket(packetBody(jammed, when));
  assert.deepEqual(packet.jamming, assessment);
  const opened = await openPacket(JSON.stringify(packet));
  assert.ok(opened.ok);
  if (!opened.ok) return;
  const rebuilt = reportFromPacket(opened.packet);
  assert.deepEqual(rebuilt.jamming, assessment);
  assert.equal(rebuilt.total, 1);
  assert.deepEqual(rebuilt.kinds[0], { kind: "Jamming", count: 1, worst: "needs_review" });
  // Packets without a jamming field have none.
  assert.equal(packetBody(summary, when).jamming, undefined);
});

test("the file name carries the site and local time", () => {
  assert.equal(packetFileName("Notre Dame campus (demo site)", when), "argus-packet-notre-dame-campus-demo-site-2026-11-12-0905.json");
  assert.equal(packetFileName("!!!", when), "argus-packet-site-2026-11-12-0905.json");
});

test("canonical JSON ignores key order", () => {
  assert.equal(canonicalJson({ b: 1, a: [{ d: 2, c: 3 }] }), canonicalJson({ a: [{ c: 3, d: 2 }], b: 1 }));
});

test("a sealed packet opens, even after being re-indented", async () => {
  const packet = await sealPacket(packetBody(summary, when));
  assert.match(packet.fingerprint.value, /^[0-9a-f]{64}$/);
  const opened = await openPacket(JSON.stringify(packet, null, 4));
  assert.ok(opened.ok);
  if (opened.ok) assert.equal(opened.packet.signals.length, 3);
});

test("a packet changed after it was made is refused", async () => {
  const packet = await sealPacket(packetBody(summary, when));
  const edited = { ...packet, counts: { ...packet.counts, needs_review: 0 } };
  assert.deepEqual(await openPacket(JSON.stringify(edited)), { ok: false, reason: "changed" });
  const relabeled = structuredClone(packet);
  relabeled.signals[0].group = "expected";
  assert.deepEqual(await openPacket(JSON.stringify(relabeled)), { ok: false, reason: "changed" });
});

test("files that are not packets are refused", async () => {
  assert.deepEqual(await openPacket("not json"), { ok: false, reason: "not_a_packet" });
  assert.deepEqual(await openPacket(JSON.stringify({ hello: "world" })), { ok: false, reason: "not_a_packet" });
  const packet = await sealPacket(packetBody(summary, when));
  const noPrint = { ...packet, fingerprint: undefined };
  assert.deepEqual(await openPacket(JSON.stringify(noPrint)), { ok: false, reason: "not_a_packet" });
});

test("a well-sealed packet with a broken field is still refused", async () => {
  const body = packetBody(summary, when);
  // Sealed after breaking it, so the fingerprint matches but the card could not show it.
  const broken = await sealPacket({ ...body, signals: [{ ...body.signals[0], group: "hostile" as "unknown" }] });
  assert.deepEqual(await openPacket(JSON.stringify(broken)), { ok: false, reason: "not_a_packet" });
});

test("the report card rebuilt from a packet groups kinds worst first", async () => {
  const packet = await sealPacket(packetBody(summary, when));
  const report = reportFromPacket(packet);
  assert.equal(report.total, 3);
  assert.deepEqual(report.kinds, [
    { kind: "Drones", count: 2, worst: "needs_review" },
    { kind: "Wi-Fi & Bluetooth", count: 1, worst: "expected" },
  ]);
  assert.equal(report.flagged.length, 2);
});
