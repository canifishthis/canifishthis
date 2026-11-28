"""The 2001 vector depth zips as a SOURCE input, hash-checked (T1267 W2).

The zips live git-ignored in `SOURCE.bathymetry_vectors` (`python -m pipeline.bathymetry.fetch_vectors` writes them);
their sha256 list `SOURCE.bathymetry_vectors_sha256` is committed. Every reader opens a zip through `zip_path`, which
RAISES (never skips) when the folder is missing, the zip is missing, the zip is not in the list, or its bytes differ:
a build cannot prove its input otherwise, and a placing frozen against one file must never be drawn from another.

    from pipeline.bathymetry.vectors import zip_path
    sheets = e00.read_zip_all(zip_path("00005801.zip"))
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

#: the hash list's schema tag
SCHEMA = "bathy-vector-hashes/1"
FETCH = "python -m pipeline.bathymetry.fetch_vectors"


class VectorSourceError(RuntimeError):
    """A vector zip that cannot be proved: missing folder, missing zip, unlisted zip or a differing hash."""


def _folder() -> Path:
    from pipeline.common.curated import SOURCE
    return Path(SOURCE.bathymetry_vectors)


def _list_path() -> Path:
    from pipeline.common.curated import SOURCE
    return Path(SOURCE.bathymetry_vectors_sha256)


def read_hashes(path: Optional[Path] = None) -> Dict[str, dict]:
    """zip name -> {sha256, bytes}, from the committed list. Raises on a missing or malformed list."""
    p = Path(path) if path else _list_path()
    if not p.is_file():
        raise VectorSourceError(f"{p}: the vector zips' hash list is missing (it is committed; restore it from git)")
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA or not isinstance(d.get("zips"), dict):
        raise VectorSourceError(f"{p}: not a {SCHEMA} file")
    return d["zips"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@lru_cache(maxsize=None)
def _checked(folder: str, list_path: str, name: str) -> str:
    hashes = read_hashes(Path(list_path))
    d = Path(folder)
    if not d.is_dir():
        raise VectorSourceError(f"{d}: the vector depth zips are not on this machine; fetch them: {FETCH}")
    if name not in hashes:
        raise VectorSourceError(f"{name}: not in {list_path}; a zip outside the committed list is never read")
    p = d / name
    if not p.is_file():
        raise VectorSourceError(f"{p}: missing; fetch it: {FETCH} (then `{FETCH} --check`)")
    got = sha256(p)
    if got != hashes[name]["sha256"]:
        raise VectorSourceError(f"{p}: sha256 {got[:12]} differs from the committed {hashes[name]['sha256'][:12]} "
                                f"({list_path}); refetch it ({FETCH}) or, for a deliberate new fetch, "
                                f"`{FETCH} --write-hashes` and review the diff")
    return got


def zip_path(name: str, *, folder: Optional[Path] = None, hashes: Optional[Path] = None) -> Path:
    """The path of the vector zip `name` after proving its bytes against the committed list (once per process)."""
    f = Path(folder) if folder else _folder()
    h = Path(hashes) if hashes else _list_path()
    _checked(str(f), str(h), name)
    return f / name


def zip_sha256(name: str, *, folder: Optional[Path] = None, hashes: Optional[Path] = None) -> str:
    """The proved sha256 of `name` (what a frozen placing records)."""
    f = Path(folder) if folder else _folder()
    h = Path(hashes) if hashes else _list_path()
    return _checked(str(f), str(h), name)


def default_folder() -> Path:
    """THE home of the zips: `SOURCE.bathymetry_vectors` (git-ignored). Every reader's default (refit_all, place_more,
    placed_contours); there is no other default."""
    return _folder()


def listed_paths(folder: Optional[Path] = None, hashes: Optional[Path] = None) -> Dict[str, Path]:
    """zip name -> its proved path, for EVERY zip of the committed list, from `folder` (default the source home). A
    missing folder, a missing or differing zip raises, naming it and the fetch command (never a partial set)."""
    f = Path(folder) if folder else _folder()
    if not f.is_dir():
        raise VectorSourceError(f"{f}: the vector depth zips are not on this machine; fetch them: {FETCH}")
    return {n: zip_path(n, folder=f, hashes=hashes) for n in sorted(read_hashes(hashes))}


def check(folder: Optional[Path] = None, hashes: Optional[Path] = None) -> dict:
    """Every listed zip proved; returns {ok, missing, differ, unlisted} (names). Raises nothing: the caller decides."""
    f = Path(folder) if folder else _folder()
    listed = read_hashes(hashes)
    out = {"ok": [], "missing": [], "differ": [], "unlisted": []}
    if not f.is_dir():
        out["missing"] = sorted(listed)
        return out
    for name, row in sorted(listed.items()):
        p = f / name
        if not p.is_file():
            out["missing"].append(name)
        elif sha256(p) != row["sha256"]:
            out["differ"].append(name)
        else:
            out["ok"].append(name)
    out["unlisted"] = sorted(p.name for p in f.glob("*.zip") if p.name not in listed)
    return out


def hash_list(folder: Path) -> dict:
    """A fresh hash list of every zip in `folder` (a deliberate new fetch only)."""
    zips = {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size} for p in sorted(Path(folder).glob("*.zip"))}
    return {"_about": "", "schema": SCHEMA, "zips": zips}
