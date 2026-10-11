"""Runtime helpers for Pi-friendly CPU use."""

from __future__ import annotations

import os


_THREAD_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)


def limit_compute_threads(n: int = 1) -> None:
    """Cap BLAS/OpenMP thread pools so detection does not pin every core."""
    value = str(max(1, n))
    for key in _THREAD_ENV:
        os.environ.setdefault(key, value)


def compute_env(base: dict[str, str] | None = None, n: int = 1) -> dict[str, str]:
    env = dict(base or os.environ)
    value = str(max(1, n))
    for key in _THREAD_ENV:
        env[key] = value
    return env
