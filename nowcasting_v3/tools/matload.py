"""Convert the Octave-generated ``.mat`` fixtures into flat ``.npz`` fixtures.

``gen_fixtures.m`` writes one ``-v7`` ``.mat`` per fixture into
``tools/fixtures_mat/``. Those files contain MATLAB structs, which
``numpy.load`` cannot read, so this converter flattens every struct into plain
numeric arrays keyed ``struct__field`` (``SSM.H`` becomes ``"SSM__H"``, nested
structs chain: ``a.b.c`` becomes ``"a__b__c"``).

Output goes to ``tests/fixtures/<name>.npz``, which IS committed: CI has no
Octave and cannot regenerate these, and a gitignored fixture makes every
fixture-backed test skip in CI while still reporting green.

Arrays are written with ``savez_compressed``. The state-space arrays are
overwhelmingly zeros, so this is worth roughly an order of magnitude.

Notes for test authors:
  * ``loadmat`` is called with ``squeeze_me=False``, so MATLAB scalars arrive as
    shape ``(1, 1)`` arrays. Use ``.item()``.
  * MATLAB is column-major and 1-based; the arrays keep their MATLAB shapes and
    any index stored in a fixture is provided in both conventions (``t_now`` and
    ``t_now_py``, ``sub_t`` and ``sub_t_py``, ``window_start`` and
    ``window_start_py``).

Usage:
    python matload.py                      # convert every fixtures_mat/*.mat
    python matload.py in.mat out.npz       # convert one file
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.io import loadmat

HERE = Path(__file__).resolve().parent
MAT_DIR = HERE / "fixtures_mat"
NPZ_DIR = HERE.parent / "tests" / "fixtures"

# Anything above this in a single fixture directory means the windowing in
# gen_fixtures.m has drifted; fail loudly rather than commit a binary blob.
MAX_TOTAL_BYTES = 5 * 1024 * 1024


def flatten(value, prefix: str, out: dict[str, np.ndarray]) -> None:
    """Recursively flatten MATLAB structs into ``out`` under ``a__b`` keys."""
    # scipy represents a MATLAB struct as a struct-array with named dtype fields.
    if isinstance(value, np.ndarray) and value.dtype.names:
        if value.size != 1:
            raise ValueError(f"{prefix}: struct arrays are not supported")
        record = value.reshape(-1)[0]
        for name in value.dtype.names:
            flatten(record[name], f"{prefix}__{name}" if prefix else name, out)
        return

    array = np.asarray(value)
    if array.dtype == object:
        raise ValueError(f"{prefix}: object arrays are not supported")
    out[prefix] = array


def convert(src: Path, dst: Path) -> dict[str, np.ndarray]:
    raw = loadmat(src, struct_as_record=True, squeeze_me=False)
    out: dict[str, np.ndarray] = {}
    for key, value in raw.items():
        if key.startswith("__"):  # __header__, __version__, __globals__
            continue
        flatten(value, key, out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dst, **out)
    return out


def convert_all(verbose: bool = True) -> int:
    sources = sorted(MAT_DIR.glob("*.mat"))
    if not sources:
        print(f"no .mat files in {MAT_DIR}; run: octave gen_fixtures.m")
        return 1
    total = 0
    for src in sources:
        dst = NPZ_DIR / f"{src.stem}.npz"
        out = convert(src, dst)
        size = dst.stat().st_size
        total += size
        print(f"{src.name} -> {dst.relative_to(HERE.parent)}  ({size / 1024:.0f} KiB)")
        if verbose:
            for key, array in sorted(out.items()):
                print(f"    {key}: {array.shape} {array.dtype}")
    print(f"\n{len(sources)} fixtures, {total / 1024 / 1024:.2f} MiB total")
    if total > MAX_TOTAL_BYTES:
        print(f"FAIL: over the {MAX_TOTAL_BYTES / 1024 / 1024:.0f} MiB budget; "
              f"shrink WINDOW or sub_t in gen_fixtures.m")
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 1:
        return convert_all()
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    out = convert(src, dst)
    print(f"{src} -> {dst}")
    for key, array in sorted(out.items()):
        print(f"  {key}: {array.shape} {array.dtype}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
