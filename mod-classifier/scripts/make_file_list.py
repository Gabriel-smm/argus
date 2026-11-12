"""Write the file list a CRC prepare array job reads: one catalog file name per line.

    python scripts/make_file_list.py tampere                # -> runs/file_lists/files_tampere.txt
    python scripts/make_file_list.py tampere --out list.txt
    python scripts/make_file_list.py nist_radar --match Group1/

The names are the `name` fields of configs/catalog.toml (Engineer 2's schema), the same
names `python -m mcls.acquire --dataset D --only NAME` accepts, in catalog order. The
last line printed is the number of files, which is the array size:

    qsub -t 1-<count> -v MCLS_DATASET=tampere,MCLS_FILE_LIST=$PWD/runs/file_lists/files_tampere.txt \
        crc/prepare_array.job

Documentation and helper files the datasets ship (example.py, load_bin.m, figures, notes)
are left out, since preprocess finds no recordings in them and the task would fail: a file
whose catalog entry has `role = "doc"` is skipped, and, when no file of the dataset has a
`role`, so is any file ending in one of DOC_SUFFIXES. Each skipped name is printed to stderr;
--keep-all keeps everything.

Exit codes match mcls.acquire: 0 ok, 2 refused (bad catalog, unknown dataset, access that
mcls.acquire cannot fetch unattended, file list unknown, or no files selected).
Reads the catalog with mcls.acquire.load_catalog, so both agree; reads no network.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = ROOT / "configs" / "catalog.toml"
DEFAULT_OUT_DIR = ROOT / "runs" / "file_lists"
DOC_SUFFIXES = (".py", ".m", ".ipynb", ".md", ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".html")


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from mcls.acquire import FETCHABLE, load_catalog  # noqa: E402  (validates the catalog)


def is_doc(entry: dict, dataset_has_roles: bool) -> bool:
    if dataset_has_roles:
        return entry.get("role", "data") == "doc"
    return entry["name"].lower().endswith(DOC_SUFFIXES)


def file_names(catalog: dict, dataset: str, match: str | None = None, keep_all: bool = False,
               skipped: list[str] | None = None) -> list[str]:
    """Catalog file names for one dataset, documentation files left out (unless keep_all).

    Names left out are appended to `skipped`. Raises ValueError with the reason to refuse.
    """
    datasets = catalog.get("datasets", {})
    if dataset not in datasets:
        raise ValueError(f"unknown dataset {dataset!r}; known: {', '.join(sorted(datasets))}")
    entry = datasets[dataset]
    access = entry.get("access")
    if access not in FETCHABLE:
        raise ValueError(f"{dataset}: access is {access!r}; mcls.acquire fetches only {sorted(FETCHABLE)}")
    if entry.get("files_status") != "complete":
        raise ValueError(f"{dataset}: file list unknown. {entry.get('files_note', '')}")
    files = entry.get("files", [])
    has_roles = any("role" in f for f in files)
    names = []
    for f in files:
        if not keep_all and is_doc(f, has_roles):
            if skipped is not None:
                skipped.append(f["name"])
            continue
        names.append(f["name"])
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
    parser.add_argument("--keep-all", action="store_true", help="do not leave out documentation files")
    args = parser.parse_args(argv)

    if not args.catalog.is_file():
        print(f"ERROR: no catalog at {args.catalog}", file=sys.stderr)
        return 2
    skipped: list[str] = []
    try:
        names = file_names(load_catalog(args.catalog), args.dataset, args.match, args.keep_all, skipped)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    for name in skipped:
        print(f"left out (documentation): {name}", file=sys.stderr)

    out = args.out or DEFAULT_OUT_DIR / f"files_{args.dataset}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(f"{n}\n" for n in names))
    print(f"wrote {out.resolve()}", file=sys.stderr)
    print(len(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
