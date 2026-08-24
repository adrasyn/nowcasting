"""Convert an Octave/MATLAB v7 ``.mat`` fixture into a flat ``.npz``.

Fixtures are generated in Octave (see ``gen_fixtures.m``) and consumed by the
Python tests via ``tests/conftest.py``. Octave writes structs, which
``np.load`` cannot read; this converter flattens them so the ``.npz`` holds
nothing but plain numeric arrays.

Struct fields are flattened to dotted keys, so a MATLAB ``filt.mu`` becomes the
array ``"filt.mu"``.

Usage:
    python matload.py probe_out.mat ../tests/fixtures/probe.npz
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.io import loadmat


def flatten(value, prefix: str, out: dict[str, np.ndarray]) -> None:
    """Recursively flatten MATLAB structs into ``out`` under dotted keys."""
    # scipy represents a MATLAB struct as a struct-array with named dtype fields.
    if isinstance(value, np.ndarray) and value.dtype.names:
        if value.size != 1:
            raise ValueError(f"{prefix}: struct arrays are not supported")
        record = value.reshape(-1)[0]
        for name in value.dtype.names:
            flatten(record[name], f"{prefix}.{name}" if prefix else name, out)
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
    np.savez(dst, **out)
    return out


def main(argv: list[str]) -> int:
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
