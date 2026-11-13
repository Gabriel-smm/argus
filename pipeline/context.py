"""Turn Laya's answers into the text the chat model answers from."""

from pipeline.lookup import EXPECTED, GROUPS, MYSTERY, REVIEW, UNKNOWN

LOW_CONFIDENCE = 0.5
MAX_LOW_CONFIDENCE = 20
MAX_FLAGGED = 20
GROUP_WORDS = {
    REVIEW: "needs a closer look",
    UNKNOWN: "unknown",
    EXPECTED: "expected here",
}


MAX_REPORT_FLAGGED = 8
MAX_REPORT_QUESTIONS = 4


def _plural(count, one, many):
    return f"{count} {one if count == 1 else many}"


JAMMING_KIND = "Jamming"
JAMMING_TITLE = "Possible jamming"
JAMMING_NEXT = (
    "Check whether radios and sensors on this band stopped working, note the time, and report a "
    "possible interference event. Do not transmit to test it."
)


def is_jamming_flagged(jamming):
    return bool(jamming and jamming.get("flagged"))


def _jamming_signal(jamming):
    """A jamming assessment as one entry under the Jamming tile.

    Jamming is judged on the band as a whole (noise floor and missing traffic), not on any
    one signal, so it is not counted among the signals.
    """
    reason = jamming.get("reason") or "The noise floor on this band rose and the usual traffic disappeared."
    band = jamming.get("band") or {}
    if band.get("min_hz") and band.get("max_hz"):
        reason += f" Band: {band['min_hz'] / 1e6:g}-{band['max_hz'] / 1e6:g} MHz."
    if isinstance(jamming.get("noise_rise_db"), (int, float)):
        reason += f" Noise rise: {jamming['noise_rise_db']:g} dB."
    missing = "; ".join(jamming.get("expected_missing") or [])
    if missing:
        reason += f" Usually heard here but missing: {missing}."
    return {
        "id": "jamming",
        "group": REVIEW,
        "title": JAMMING_TITLE,
        "kind": JAMMING_KIND,
        "reason": reason,
        "check_next": JAMMING_NEXT,
        "protected": False,
    }


def build_site_report(rows, jamming=None):
    """The site check as a picture-ready report: one verdict, what is in the air, and what to look at.

    Built here, not by the chat model, so the dashboard can show it the moment a run
    finishes and it always matches the numbers. A flagged jamming assessment (from a
    scene) makes the verdict "needs a closer look", headed "Possible jamming".
    """
    checked = [row for row in rows if row.get("lookup")]
    if not checked:
        return None
    site = checked[0]["lookup"]["site"]
    counts = {group: sum(row["lookup"]["triage"] == group for row in checked) for group in GROUPS}
    review, unknown = counts[REVIEW], counts[UNKNOWN]
    jammed = is_jamming_flagged(jamming)
    if jammed:
        verdict = "review"
        headline = JAMMING_TITLE
        explain = jamming.get("reason") or "The usual traffic on one band disappeared under noise."
    elif review:
        verdict = "review"
        headline = f"{_plural(review, 'signal needs', 'signals need')} a closer look"
        explain = (
            f"Most of what we heard is normal for {site}, but "
            f"{_plural(review, 'signal does', 'signals do')} not belong here. Tap the red tiles below to see them."
        )
    elif unknown:
        verdict = "unknown"
        headline = "Mostly normal"
        explain = f"Nothing alarming. We could not place {_plural(unknown, 'signal', 'signals')}."
    else:
        verdict = "normal"
        headline = "Normal activity"
        explain = f"Everything we heard is what we would expect at {site}."

    kinds = {}
    for row in checked:
        lookup = row["lookup"]
        entry = kinds.setdefault(lookup["kind"], {"kind": lookup["kind"], "count": 0, "worst": EXPECTED})
        entry["count"] += 1
        if GROUPS.index(lookup["triage"]) < GROUPS.index(entry["worst"]):
            entry["worst"] = lookup["triage"]
    kind_list = sorted(kinds.values(), key=lambda entry: (GROUPS.index(entry["worst"]), -entry["count"]))

    flagged_rows = sorted(
        (row for row in checked if row["lookup"]["triage"] != EXPECTED),
        key=lambda row: GROUPS.index(row["lookup"]["triage"]),
    )
    flagged = [
        {
            "id": str(row["id"]),
            "group": row["lookup"]["triage"],
            "title": row["lookup"]["title"],
            "kind": row["lookup"]["kind"],
            "reason": row["lookup"]["reason"],
            "check_next": row["lookup"]["check_next"],
            "protected": row["lookup"]["protected"],
        }
        for row in flagged_rows[:MAX_REPORT_FLAGGED]
    ]

    # Every signal, worst first, so the dashboard can open any category on demand.
    ordered = sorted(checked, key=lambda row: GROUPS.index(row["lookup"]["triage"]))
    signals = [
        {
            "id": str(row["id"]),
            "group": row["lookup"]["triage"],
            "title": row["lookup"]["title"],
            "kind": row["lookup"]["kind"],
            "reason": row["lookup"]["reason"],
            "check_next": row["lookup"]["check_next"],
            "protected": row["lookup"]["protected"],
        }
        for row in ordered
    ]

    titles = {row["lookup"]["title"] for row in flagged_rows}
    kinds_flagged = {row["lookup"]["kind"] for row in flagged_rows}
    questions = []
    if "Something on GPS" in titles:
        questions.append("Is the signal on GPS dangerous, and what should I check?")
    if titles & {"Drone with no ID", "Possible drone"}:
        questions.append("What should I do about the drone signals?")
    if MYSTERY in kinds_flagged or "Not usual for this place" in titles:
        questions.append("What could the unknown signals be?")
    questions.append(f"What is normal at {site}, and why?")
    if verdict != "normal":
        questions.append("Explain this report as if I am new to radio.")

    if jammed:
        # Jamming first everywhere: its own tile, entry and question.
        entry = _jamming_signal(jamming)
        kind_list.insert(0, {"kind": JAMMING_KIND, "count": 1, "worst": REVIEW})
        flagged.insert(0, entry)
        signals.insert(0, entry)
        questions.insert(0, "What does possible jamming mean, and what should I check?")

    report = {
        "site": site,
        "verdict": verdict,
        "headline": headline,
        "explain": explain,
        "counts": counts,
        "total": len(checked),
        "kinds": kind_list,
        "flagged": flagged[:MAX_REPORT_FLAGGED],
        "more_flagged": max(0, len(flagged_rows) + jammed - MAX_REPORT_FLAGGED),
        "signals": signals,
        "questions": questions[:MAX_REPORT_QUESTIONS],
    }
    if jammed:
        report["jamming"] = {
            key: jamming[key]
            for key in ("flagged", "reason", "noise_rise_db", "expected_missing", "band", "source")
            if key in jamming
        }
    return report


def _site_check(rows, jamming=None):
    """The site check section: counts per group, then the flagged signals with reasons."""
    checked = [row for row in rows if row.get("lookup")]
    if not checked:
        return []
    site = checked[0]["lookup"]["site"]
    lines = [
        "",
        f"Site check for {site}: each signal compared with the band table and the site's "
        "frequency list. This is separate from the labels above and does not change them.",
        f"Overall verdict, shown to the person as a card above the chat: "
        f"{build_site_report(rows, jamming)['headline']}.",
    ]
    if is_jamming_flagged(jamming):
        entry = _jamming_signal(jamming)
        lines.append(
            "Jamming assessment (the band as a whole, not one signal; it needs a closer look): "
            f"possible jamming. {entry['reason']} Next: {entry['check_next']}"
        )
    lines.append("Group (count): observation ids")
    for group in GROUPS:
        ids = [str(row["id"]) for row in checked if row["lookup"]["triage"] == group]
        lines.append(f"- {GROUP_WORDS[group]} ({len(ids)}): {', '.join(ids) or 'none'}")
    flagged = [row for row in checked if row["lookup"]["triage"] != EXPECTED]
    flagged.sort(key=lambda row: GROUPS.index(row["lookup"]["triage"]))
    if not flagged:
        lines.append("Every signal is expected at this site.")
        return lines
    shown = f"the first {MAX_FLAGGED} are listed" if len(flagged) > MAX_FLAGGED else "all are listed"
    lines.append(
        f"{len(flagged)} signals need a closer look or are unknown; {shown}, closer look first, "
        "as id (group): measurements; why; what to check next"
    )
    for row in flagged[:MAX_FLAGGED]:
        lookup = row["lookup"]
        protected = " Protected safety band: listen only." if lookup["protected"] else ""
        lines.append(
            f"- {row['id']} ({GROUP_WORDS[lookup['triage']]}): {row['state']} "
            f"Why: {lookup['reason']}{protected} Next: {lookup['check_next']}"
        )
    return lines


def _members(name, question, rows):
    """Observation ids per answer, keeping answers nobody got."""
    members = {option: [] for option in question["criteria"]}
    for row in rows:
        members.setdefault(row["answers"][name][0], []).append(str(row["id"]))
    return members


def _low_confidence(name, rows):
    """Rows Laya was unsure about for one question, least certain first."""
    low = [row for row in rows if row["answers"][name][1] < LOW_CONFIDENCE]
    return sorted(low, key=lambda row: row["answers"][name][1])


def build_context(names, questions, rows, total, offset=0, jamming=None):
    """Describe the classification so a small model can answer without counting."""
    end = offset + len(rows)
    lines = [
        f"Laya classified {len(rows)} observations from {names['data']}, "
        f"using the questions in {names['knowledge']}."
    ]
    if offset == 0 and total > len(rows):
        lines.append(f"Only the first {len(rows)} of {total} rows in the file were classified.")
        lines.append(f"{total - len(rows)} rows have not been classified.")
    elif offset > 0:
        lines.append(f"This result covers rows {offset + 1}\u2013{end} of {total}.")
        lines.append(f"Rows 1\u2013{offset} are not part of this result.")
        if end < total:
            lines.append(f"{total - end} rows after this result have not been classified.")
    for name, question in questions.items():
        lines += ["", f"Question {name!r}: {question['instructions']}", "What each answer means:"]
        lines += [f"- {option}: {description}" for option, description in question["criteria"].items()]
        lines.append("Answer (count): observation ids")
        lines += [
            f"- {option} ({len(ids)}): {', '.join(ids) or 'none'}"
            for option, ids in _members(name, question, rows).items()
        ]
        confidences = [row["answers"][name][1] for row in rows]
        lines.append(
            f"Confidence: mean {sum(confidences) / len(confidences):.2f}, "
            f"lowest {min(confidences):.2f}."
        )
        low = _low_confidence(name, rows)
        if not low:
            lines.append(f"No observation is below {LOW_CONFIDENCE:.2f} confidence.")
            continue
        shown = (
            f"Only the {MAX_LOW_CONFIDENCE} least certain are listed"
            if len(low) > MAX_LOW_CONFIDENCE
            else "Least certain first"
        )
        lines.append(
            f"{len(low)} observations are below {LOW_CONFIDENCE:.2f} confidence. "
            f"{shown}, as id: answer at confidence; measurements"
        )
        for row in low[:MAX_LOW_CONFIDENCE]:
            choice, confidence = row["answers"][name]
            lines.append(f"- {row['id']}: {choice} at {confidence:.2f}; {row['state']}")
    lines += _site_check(rows, jamming)
    return "\n".join(lines)


def build_summary(names, questions, rows, total, seconds, offset=0, jamming=None):
    """The short account of a run that the dashboard shows."""
    summary = {
        "knowledge_name": names["knowledge"],
        "data_name": names["data"],
        "observations": len(rows),
        "total_rows": total,
        "row_offset": offset,
        "questions": [
            {
                "name": name,
                "instructions": question["instructions"],
                "counts": {
                    option: len(ids) for option, ids in _members(name, question, rows).items()
                },
            }
            for name, question in questions.items()
        ],
        "low_confidence": sum(
            any(row["answers"][name][1] < LOW_CONFIDENCE for name in questions) for row in rows
        ),
        "seconds": round(seconds, 1),
    }
    if any(row.get("lookup") for row in rows):
        summary["site_check"] = {
            group: sum(bool(row.get("lookup")) and row["lookup"]["triage"] == group for row in rows)
            for group in GROUPS
        }
        summary["site_report"] = build_site_report(rows, jamming)
    return summary
