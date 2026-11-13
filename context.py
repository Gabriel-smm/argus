"""Turn Laya's answers into the text the chat model answers from."""

LOW_CONFIDENCE = 0.5
MAX_LOW_CONFIDENCE = 20


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


def build_context(names, questions, rows, total, offset=0):
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
    return "\n".join(lines)


def build_summary(names, questions, rows, total, seconds, offset=0):
    """The short account of a run that the dashboard shows."""
    return {
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


def build_verdict_context(result):
    """The judged result, in words the chat model can quote without counting."""
    verdicts = result["verdicts"]
    by_id = {c["detection_id"]: c for c in result["classifications"]}
    detections = {d["detection_id"]: d for d in result["detections"]}
    counts = {name: sum(v["disposition"] == name for v in verdicts) for name in ("blue", "white", "red")}
    lines = [
        "",
        "Site verdicts (blue = expected here, white = unknown, red = not expected here):",
        f"- blue: {counts['blue']}, white: {counts['white']}, red: {counts['red']}",
        "Every red and white verdict, with the reason the judging step gave:",
    ]
    for v in verdicts:
        if v["disposition"] == "blue":
            continue
        d, c = detections[v["detection_id"]], by_id[v["detection_id"]]
        lines.append(
            f"- {v['detection_id']}: {v['disposition'].upper()}, {c['label']} at {c['confidence']:.2f}, "
            f"{d['center_freq_hz'] / 1e6:.4g} MHz; {v['reason']} Next step: {v['next_step']}"
        )
    return "\n".join(lines)
