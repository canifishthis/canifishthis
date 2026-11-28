"""Fetch the Province's 2001 vector depth files (zips of ArcInfo `.e00`) into `SOURCE.bathymetry_vectors` (T634 item 3;
T1267: the git-ignored source folder, its committed sha256 list `SOURCE.bathymetry_vectors_sha256`).

WHAT IS FETCHED. Every sheet the sheet layer (`WHSE_FISH.BATH_SURVEY_MAP_SHEETS_SVW`, our gpkg layer
`bathymetry_polygons`) flags `VECTORIZED_FLAG = Y`. Two names are tried per sheet: the layer's own `VECTOR_FILE_URL`
(it names sheet 1's zip for every sheet of a multi-sheet lake: 697 flagged sheets, 513 distinct URLs) and the zip named
after the sheet's own image (`MAP_IMAGE_FILENAME`, 684 distinct). Both live on the same FIDQ address as the open PDFs.

POLITE BY CONSTRUCTION: one request at a time, a pause between, a generic client name, resume (a file already on disk
is never fetched again; `status.json` records every answer), and it STOPS at the first refusal (HTTP 403 / 429 / 5xx)
rather than retrying round it. A 200 that is not a zip is the server's "File not found" page: recorded as `missing`.

The zips land in `SOURCE.bathymetry_vectors` (git-ignored; `--out DIR` for another folder), then every listed zip is
CHECKED against the committed hash list (`pipeline.bathymetry.vectors`): exit 1 naming any missing or differing zip.
510 zips cover 512 sheets: 00153501 and 00153701 each hold a second line coverage repeating the first.

    python -m pipeline.bathymetry.fetch_vectors              # fetch what is missing, then check
    python -m pipeline.bathymetry.fetch_vectors --check      # check only (no network)
    python -m pipeline.bathymetry.fetch_vectors --write-hashes   # a DELIBERATE new fetch: rewrite the list, review the diff
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://a100.gov.bc.ca/pub/fidq/downloadBathymetricMap.do?filename="
AGENT = "Mozilla/5.0 (compatible)"
PAUSE_S = 0.5
REFUSED = {403, 429}


def sheets(gpkg: Path) -> list[dict]:
    """Every flagged sheet, with both candidate zip names. Sorted, so a rerun walks the same order."""
    import fiona
    out = []
    with fiona.open(gpkg, layer="bathymetry_polygons") as src:
        for f in src:
            p = f["properties"]
            if p["VECTORIZED_FLAG"] != "Y":
                continue
            url_zip = (p["VECTOR_FILE_URL"] or "").split("filename=")[-1].lower()
            img_zip = (p["MAP_IMAGE_FILENAME"] or "").rsplit(".", 1)[0].lower() + ".zip"
            out.append({"wbid": p["WATERBODY_IDENTIFIER"], "title": p["MAP_TITLE"], "sheet": p["SHEET_NO"],
                        "n_sheets": p["NUMBER_OF_MAP_SHEETS"], "image": p["MAP_IMAGE_FILENAME"],
                        "pdf": (p["PDF_FILE_URL"] or "").split("filename=")[-1], "url_zip": url_zip,
                        "image_zip": img_zip, "gazetted": p["GAZETTED_NAME"], "lake_id": p["LAKE_ID"]})
    return sorted(out, key=lambda r: (r["image"], r["wbid"]))


def _write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True))
    os.replace(tmp, path)


def fetch(out: Path, names: list[str]) -> dict:
    zips = out
    zips.mkdir(parents=True, exist_ok=True)
    status_path = out / "status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    for i, name in enumerate(names):
        dest = zips / name
        if dest.exists() or status.get(name, {}).get("state") == "missing":
            continue
        req = urllib.request.Request(BASE + name, headers={"User-Agent": AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body, ctype = r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            status[name] = {"state": "http_error", "code": e.code}
            _write_json(status_path, status)
            if e.code in REFUSED or e.code >= 500:
                print(f"STOP: server answered {e.code} for {name}; {i} of {len(names)} walked", file=sys.stderr)
                raise SystemExit(2)
            continue
        if body[:2] == b"PK":
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(body)
            os.replace(tmp, dest)
            status[name] = {"state": "ok", "bytes": len(body)}
        else:
            status[name] = {"state": "missing", "content_type": ctype, "bytes": len(body),
                            "body": body[:120].decode("utf-8", "replace")}
        _write_json(status_path, status)
        if i % 25 == 0:
            print(f"{i}/{len(names)} {name} {status[name]['state']}", flush=True)
        time.sleep(PAUSE_S)
    return status


def check_report(out: Path) -> int:
    """Every listed zip proved against the committed list; 0 when all are there and equal, else 1 (named)."""
    from pipeline.bathymetry import vectors
    got = vectors.check(out)
    print(f"check: {len(got['ok'])} ok, {len(got['missing'])} missing, {len(got['differ'])} differ, "
          f"{len(got['unlisted'])} unlisted (never read)")
    for k in ("missing", "differ"):
        for n in got[k]:
            print(f"  {k}: {out / n}")
    return 0 if not got["missing"] and not got["differ"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, help="defaults to SOURCE.bathymetry_vectors (git-ignored)")
    ap.add_argument("--gpkg", type=Path, help="defaults to config fetch.output_gpkg")
    ap.add_argument("--check", action="store_true", help="check the zips against the committed list; no network")
    ap.add_argument("--write-hashes", action="store_true",
                    help="rewrite the committed hash list from the zips on disk (a deliberate new fetch only)")
    a = ap.parse_args(argv)
    from pipeline.common.curated import SOURCE
    out = (a.out.expanduser().resolve() if a.out else Path(SOURCE.bathymetry_vectors))
    if a.write_hashes:
        from pipeline.bathymetry import vectors
        path = Path(SOURCE.bathymetry_vectors_sha256)
        old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        new = vectors.hash_list(out)
        new["_about"] = old.get("_about") or "The sha256 of every vector depth zip a placing may read (T1267)."
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(new, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        print(f"wrote {path} ({len(new['zips'])} zips); review the diff before committing it")
        return 0
    if a.check:
        return check_report(out)
    if a.gpkg is None:
        a.gpkg = SOURCE.fwa_gpkg
    rows = sheets(a.gpkg)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "sheets.json", rows)
    names = sorted({r["url_zip"] for r in rows} | {r["image_zip"] for r in rows})
    status = fetch(out, names)
    ok = sum(1 for v in status.values() if v["state"] == "ok")
    print(f"done: {len(names)} names, {ok} zips, {sum(1 for v in status.values() if v['state'] == 'missing')} missing")
    return check_report(out)


if __name__ == "__main__":
    raise SystemExit(main())
