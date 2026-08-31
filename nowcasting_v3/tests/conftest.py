from pathlib import Path

import numpy as np
import pytest

from nyfed.ssm import StateSpace

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


def ssm_from_fixture(d: dict, prefix: str = "SSM") -> StateSpace:
    """Rebuild a StateSpace from a fixture's flattened ``prefix__field`` keys.

    ``C`` and ``D`` are absent from some fixtures because the MATLAB defaults
    them; pass None so the port applies the same default.

    Lives here rather than in a test module because test_ssm.py and
    test_nowcast.py both need it and had a verbatim copy each.
    """
    return StateSpace(
        D=d.get(f"{prefix}__D"), H=d[f"{prefix}__H"],
        Sigma_eps=d.get(f"{prefix}__Sigma_eps"), C=d.get(f"{prefix}__C"),
        F=d[f"{prefix}__F"], G=d[f"{prefix}__G"],
        Sigma_eta=d.get(f"{prefix}__Sigma_eta"), mu_1=d[f"{prefix}__mu_1"].ravel(),
        Sigma_1=d[f"{prefix}__Sigma_1"],
    )
