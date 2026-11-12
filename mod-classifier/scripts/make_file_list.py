"""Write the file list a CRC prepare array job reads: one catalog file name per line.

    python scripts/make_file_list.py tampere                # -> runs/file_lists/files_tampere.txt
    python scripts/make_file_list.py tampere --out list.txt
    python scripts/make_file_list.py nist_radar --match Group1/

The names are the `name` fields of configs/catalog.toml (Engineer 2's schema), the same
names `python -m mcls.acquire --dataset D --only NAME` accepts, in catalog order. The
last line printed is the number of files, which is the array size:

    qsub -t 1-<count> -v MCLS_DATASET=tampere,MCLS_FILE_LIST=$PWD/runs/file_lists/files_tampere.txt \
        crc/prepare_array.job

Exit codes match mcls.acquire: 0 ok, 2 refused (unknown dataset, access not "direct",
files_status not "complete" without --allow-incomplete, or no files selected).
Standard library only; reads no network.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = ROOT / "configs" / "catalog.toml"
DEFAULT_OUT_DIR = ROOT / "runs" / "file_lists"


def load_catalog(path: Path) -> dict:
    """The parsed catalog. Uses mcls.acquire.load_catalog when it exists, so both agree."""
    try:
        sys.path.insert(0, str(ROOT))
        from mcls.acquire import load_catalog as acquire_load  # type: ignore
    except ImportError:
        acquire_load = None
    finally:
        sys.path.pop(0)
    if acquire_load is not None:
        return acquire_load(path)
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def file_names(catalog: dict, dataset: str, match: str | None = None,
               allow_incomplete: bool = False) -> list[str]:
    """Catalog file names for one dataset. Raises ValueError with the reason to refuse."""
    datasets = catalog.get("datasets", {})
    if dataset not in datasets:
        raise ValueError(f"unknown dataset {dataset!r}; known: {', '.join(sorted(datasets))}")
    entry = datasets[dataset]
    access = entry.get("access", "direct")
    if access != "direct":
        raise ValueError(f"{dataset}: access is {access!r}, not 'direct'; a batch job cannot fetch it")
    status = entry.get("files_status", "complete")
    if status != "complete" and not allow_incomplete:
        note = entry.get("files_note", "")
        raise ValueError(f"{dataset}: files_status is {status!r} ({note}); pass --allow-incomplete to list anyway")
    names = [f["name"] for f in entry.get("files", [])]
    if match:
        names = [n for n in names if match in n]
    for name in names:
        if not name or "\n" in name or name.startswith("#") or name != name.strip():
            raise ValueError(f"{dataset}: file name {name!r} cannot be one line of a file list")
    if len(set(names)) != len(names):
        raise ValueError(f"{dataset}: duplicate file names in the catalog")
    if not names:
        raise ValueError(f"{dataset}: no files selected")
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dataset")
    parser.add_argument("--out", type=Path, help="default runs/file_lists/files_<dataset>.txt")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--match", help="keep only names containing this text")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args(argv)

    if not args.catalog.is_file():
        print(f"ERROR: no catalog at {args.catalog}", file=sys.stderr)
        return 2
    try:
        names = file_names(load_catalog(args.catalog), args.dataset, args.match, args.allow_incomplete)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    out = args.out or DEFAULT_OUT_DIR / f"files_{args.dataset}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(f"{n}\n" for n in names))
    print(f"wrote {out.resolve()}", file=sys.stderr)
    print(len(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
