# `data/curated/bathymetry/`: the lake depth sheets, accepted

| file | kind | written by | read by |
|---|---|---|---|
| `placings.json` (`bathy-placings/1`) | promoted | ONLY `python -m pipeline.bathymetry.placings --freeze` (`curated_write`) | the placed depth contours (T1268) |
| `sheet_units.json` (`bathy-sheet-units/1`) | authored | a person reading the printed chart (AGENTS A2) | `placings --freeze` |
| `matches.json`, `contour_matches.json` (absent until the first accept) | promoted | ONLY `pipeline.bathymetry.accept` | nothing yet |

Nothing of a lake's depth ships without its row in `placings.json` (owner 2026-11-28). The rules (what is accepted, a
mark's pose is the one the page showed plus his adjustment as saved, a row is never rewritten, the units) are the
docstring of `pipeline/bathymetry/placings.py`; held-out sheets by reason: `data/generated/bathymetry/placings_report.json`.
