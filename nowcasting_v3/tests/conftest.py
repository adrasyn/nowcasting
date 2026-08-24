from pathlib import Path

import numpy as np
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load an Octave-generated fixture as a dict of arrays.

    Fixtures are committed (CI has no Octave), so the skip below only fires on a
    working copy where they have been deleted. Regenerate with:
        cd nowcasting_v3/tools && octave gen_fixtures.m && ../.venv/bin/python matload.py
    """
    path = FIXTURE_DIR / f"{name}.npz"
    if not path.exists():
        pytest.skip(f"fixture {name} absent - run tools/gen_fixtures.m")
    return dict(np.load(path, allow_pickle=False))


@pytest.fixture
def fixture():
    return load_fixture
