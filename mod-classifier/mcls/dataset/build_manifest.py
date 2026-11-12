"""Build data/manifest.jsonl from the front end's per-shard rows.

    python -m mcls.dataset.build_manifest --shards DIR [--shards DIR ...] \
        --out data/manifest.jsonl --seed S [--cross-test DATASET ...] [--cap-per-class N] \
        [--holdout-emitter ID ...] [--holdout-split test] [--classes v1|v2]

Collects rows, caps each class per dataset (PLAN 3.6), splits by recording
(`mcls.manifest.assign_splits`), optionally holds out whole emitters (PLAN
3.5), checks id leakage and identical-sample leakage, writes the manifest
sorted by window_id with shard paths relative to its own directory, and prints
its sha256 (`mcls.manifest.digest`).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from mcls import manifest, taxonomy
from mcls.dataset.rows import DEFAULT_CAP_PER_CLASS, build, relative_to
from mcls.dataset.store import WindowStore, audit_window_hashes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m mcls.dataset.build_manifest", description=__doc__.split("\n\n")[0])
    parser.add_argument("--shards", type=Path, action="append", required=True, help="front-end output directory (repeatable)")
    parser.add_argument("--out", type=Path, default=Path("data/manifest.jsonl"))
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--cross-test", nargs="*", default=[], metavar="DATASET", help="datasets held out whole as cross_test")
    parser.add_argument("--cap-per-class", type=int, default=DEFAULT_CAP_PER_CLASS, help="per class per dataset; 0 = no cap")
    parser.add_argument("--holdout-emitter", nargs="*", default=[], metavar="ID", help="emitter_id(s) held out whole")
    parser.add_argument("--holdout-split", default="test", help="split that held-out emitters go to")
    parser.add_argument("--holdout-match", choices=("emitter", "recording"), default="emitter",
                        help="match emitter_id exactly, or a substring of recording_id")
    parser.add_argument("--classes", choices=("v1", "v2"), default=None,
                        help="validate labels against this class set from configs/taxonomy.toml")
    parser.add_argument("--no-hash-audit", action="store_true", help="skip hashing window samples")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        rows = build(args.shards, args.seed, args.cross_test, args.cap_per_class,
                     args.holdout_emitter, args.holdout_split, args.holdout_match)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.no_hash_audit:
        leaks = audit_window_hashes(rows, WindowStore())
        if leaks:
            for digest, members in leaks[:10]:
                print(f"identical window across splits: {digest[:16]} {members}", file=sys.stderr)
            print(f"error: {len(leaks)} identical windows appear in more than one split", file=sys.stderr)
            return 1
    classes = taxonomy.load().classes(args.classes) if args.classes else None
    out_rows = relative_to(rows, args.out.resolve().parent)
    try:
        count = manifest.write(args.out, out_rows, classes)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for split, n in sorted(Counter(row.split for row in rows).items()):
        print(f"  {split}: {n}")
    print(f"manifest: {args.out} rows={count} sha256={manifest.digest(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
