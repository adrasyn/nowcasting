"""Extract the NY Fed's PUBLISHED nowcasts and news tables into a fixture.

``nyfed_matlab/output/Update_<date>.mat`` holds, for each published week, the
headline nowcast and the per-series news table that the Fed actually released.
Task 9 gates the whole port against those numbers, so they have to reach the
Python side.

Only the headline scalar is reachable through a documented API. ``output.date``
is a MATLAB ``datetime`` and ``output.news_table`` is a MATLAB ``table``; both
are MCOS classdef objects. scipy sees a ``MatlabOpaque`` wrapper with no
content, and Octave 11.3.0 refuses them outright with

    warning: load: classdef not found. Element loaded as uint32

leaving a 6x1 uint32 stub in place of the object. The real payload sits in the
file's undocumented ``__function_workspace__`` MCOS subsystem, which neither
tool decodes.

This module recovers it by locating the four numeric columns and the row names
inside that subsystem directly. That is byte-level archaeology on an
undocumented format, so it is guarded by checks that make a wrong read fail
loudly rather than silently produce a plausible fixture:

  1. Every row name must be a series name from model_spec_FRED.csv, and the
     number of names must equal the number of rows in the numeric block.
  2. ``Impact == (Actual - Forecast) .* Weight`` must hold to the BIT for every
     row. example_nowcast.m computes impacts exactly that way, so a misaligned
     read cannot satisfy it across every row of four separate byte regions.
  3. Every (start, stride) alignment that satisfies 1-2 must agree on the
     numbers, so the read is unambiguous rather than merely self-consistent.

Sanity-checked against reality for the 2023-10-06 vintage: the recovered
Actuals are JOLTS +690k, nonfarm payrolls +336k, unemployment rate change 0.0,
ADP +89k - the September 2023 prints.

Usage:
    ../.venv/bin/python extract_published.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from scipy.io import loadmat

HERE = Path(__file__).resolve().parent
MATLAB = HERE.parent / "nyfed_matlab"
NPZ = HERE.parent / "tests" / "fixtures" / "published_nowcasts.npz"

VINTAGES = ["2023_09_29", "2023_10_06"]
COLUMNS = ["forecast", "actual", "weight", "impact"]


def spec_names() -> list[str]:
    with open(MATLAB / "model_spec_FRED.csv", newline="", encoding="utf-8") as fh:
        return [row["SeriesName"] for row in csv.DictReader(fh)]


def find_row_names(raw: bytes, names: list[str]) -> list[tuple[int, str, int]]:
    """Locate every spec series name in the subsystem, in byte order.

    MATLAB stores pure-ASCII char arrays as 8-bit and any string containing a
    non-Latin-1 codepoint (four of these names carry U+2019) as UTF-16LE, so
    both encodings have to be searched.
    """
    found: list[tuple[int, str, int]] = []
    for index, name in enumerate(names, start=1):
        for encoded in filter(None, [
            name.encode("latin1") if max(name) < "Ā" else None,
            name.encode("utf-16-le"),
        ]):
            offset = raw.find(encoded)
            if offset != -1:
                found.append((offset, name, index))
                break
    return sorted(found)


def find_table(raw: bytes, nrows: int) -> np.ndarray:
    """Recover the 4 x nrows numeric block. Raises unless the read is unambiguous."""
    solutions = []
    limit = len(raw) - 8 * nrows
    for stride in range(8 * nrows, 8 * nrows + 264, 8):
        for start in range(0, limit - 3 * stride, 8):
            block = np.stack([
                np.frombuffer(raw[start + j * stride: start + j * stride + 8 * nrows], "<f8")
                for j in range(4)
            ])
            if not np.all(np.isfinite(block)):
                continue
            # reject denormal / absurd garbage
            magnitude = np.abs(block)
            if np.any((magnitude > 0) & (magnitude < 1e-300)) or magnitude.max() > 1e9:
                continue
            forecast, actual, weight, impact = block
            if np.abs(impact).max() < 1e-6:
                continue
            if not np.array_equal(impact, (actual - forecast) * weight):
                continue
            solutions.append(block)

    if not solutions:
        raise RuntimeError(f"no {nrows}-row news table found in the MCOS subsystem")
    first = solutions[0]
    for other in solutions[1:]:
        if not np.array_equal(first, other):
            raise RuntimeError("ambiguous news-table read: alignments disagree")
    return first


def extract(vintage: str, names: list[str]) -> dict[str, np.ndarray]:
    path = MATLAB / "output" / f"Update_{vintage}.mat"
    raw = loadmat(path, struct_as_record=False, squeeze_me=False)
    nowcast = raw["output"][0, 0].nowcast.item()

    workspace = raw["__function_workspace__"].tobytes()
    rows = find_row_names(workspace, names)
    if not rows:
        raise RuntimeError(f"{path.name}: no series names found in the subsystem")
    block = find_table(workspace, len(rows))

    out: dict[str, np.ndarray] = {f"published__{vintage}": np.array(nowcast)}
    for column, values in zip(COLUMNS, block):
        out[f"news_{vintage}__{column}"] = values
    out[f"news_{vintage}__series_name"] = np.array([name for _, name, _ in rows], dtype="U80")
    out[f"news_{vintage}__series_index"] = np.array([idx for _, _, idx in rows], dtype=np.int64)
    return out


def main() -> int:
    names = spec_names()
    out: dict[str, np.ndarray] = {}
    for vintage in VINTAGES:
        part = extract(vintage, names)
        out.update(part)
        impact = part[f"news_{vintage}__impact"]
        print(f"{vintage}: published nowcast = {part[f'published__{vintage}'].item():.16f}, "
              f"{impact.size} releases, sum(impact) = {impact.sum():.8f}")
        for name, forecast, actual, weight, imp in zip(
            part[f"news_{vintage}__series_name"], part[f"news_{vintage}__forecast"],
            part[f"news_{vintage}__actual"], part[f"news_{vintage}__weight"], impact,
        ):
            print(f"    {name[:44]:44s} F={forecast:12.6f} A={actual:12.6f} "
                  f"W={weight:10.6f} I={imp:9.6f}")
    NPZ.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(NPZ, **out)
    print(f"\n-> {NPZ.relative_to(HERE.parent)} ({NPZ.stat().st_size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
