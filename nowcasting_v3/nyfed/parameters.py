"""Parameter vector layout for the nowcast model.

Ports ``functions/model/map_parameter.m`` and ``functions/model/vec_parameter.m``.

MATLAB stores arrays column-major; numpy defaults to row-major. Every
reshape here passes ``order="F"`` so that flattening and un-flattening
match the MATLAB ``(:)`` semantics exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Params:
    """Nowcast model parameters.

    Shapes (``n`` series, ``n_f`` factors, ``p_f`` factor-VAR lags,
    ``p_e`` measurement-error AR lags):
    """

    mu: np.ndarray        # (n,)
    gamma_g: float
    Lambda: np.ndarray    # (n, n_f)
    Phi: np.ndarray        # (n_f, n_f, p_f)
    gamma_f: np.ndarray    # (n_f,)
    pi_f: np.ndarray       # (n_f,)
    phi: np.ndarray        # (n, p_e)
    gamma_e: np.ndarray    # (n,)
    pi_e: np.ndarray       # (n,)


def vec_parameter(param: Params) -> np.ndarray:
    """Turn parameters of nowcast model into a vector.

    Vertically concatenates the individual parameters of ``param``:
    ``N_PARAM = 1 + N*(1 + N_F + P_E + 2) + N_F*(N_F*P_F + 2)``.
    """
    return np.concatenate(
        [
            np.asarray(param.mu, dtype=float).reshape(-1, order="F"),
            np.array([param.gamma_g], dtype=float),
            np.asarray(param.Lambda, dtype=float).reshape(-1, order="F"),
            np.asarray(param.Phi, dtype=float).reshape(-1, order="F"),
            np.asarray(param.gamma_f, dtype=float).reshape(-1, order="F"),
            np.asarray(param.pi_f, dtype=float).reshape(-1, order="F"),
            np.asarray(param.phi, dtype=float).reshape(-1, order="F"),
            np.asarray(param.gamma_e, dtype=float).reshape(-1, order="F"),
            np.asarray(param.pi_e, dtype=float).reshape(-1, order="F"),
        ]
    )


def map_parameter(param_vec: np.ndarray, dims: tuple[int, int, int, int]) -> Params:
    """Extract the parameter vector of the nowcast model into ``Params``.

    ``dims = (n, n_f, p_f, p_e)``:
      - ``n`` is the number of series (monthly and quarterly).
      - ``n_f`` is the number of factors.
      - ``p_f`` is the number of lags in the VAR model for the factors.
      - ``p_e`` is the number of lags in the AR model for measurement errors.
    """
    n, n_f, p_f, p_e = dims
    param_vec = np.asarray(param_vec, dtype=float)

    # Auxiliary numbers and vectors (mirrors n_tmp / n_vec in map_parameter.m)
    sizes = [n, 1, n * n_f, n_f**2 * p_f, n_f, n_f, n * p_e, n, n]
    n_tmp = np.cumsum(sizes)
    starts = np.concatenate(([0], n_tmp[:-1]))
    ends = n_tmp

    def block(i: int) -> np.ndarray:
        return param_vec[starts[i] : ends[i]]

    mu = block(0).reshape((n,), order="F")
    gamma_g = float(block(1).reshape((1,), order="F")[0])
    Lambda = block(2).reshape((n, n_f), order="F")
    Phi = block(3).reshape((n_f, n_f, p_f), order="F")
    gamma_f = block(4).reshape((n_f,), order="F")
    pi_f = block(5).reshape((n_f,), order="F")
    phi = block(6).reshape((n, p_e), order="F")
    gamma_e = block(7).reshape((n,), order="F")
    pi_e = block(8).reshape((n,), order="F")

    return Params(
        mu=mu,
        gamma_g=gamma_g,
        Lambda=Lambda,
        Phi=Phi,
        gamma_f=gamma_f,
        pi_f=pi_f,
        phi=phi,
        gamma_e=gamma_e,
        pi_e=pi_e,
    )
