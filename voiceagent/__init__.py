"""Hudu: a local voice assistant driven by voice, powered by Gemini."""

import os as _os

# Windows OpenBLAS (pulled in by numpy) reserves a thread stack per core and
# intermittently dies with "Memory allocation still failed after 10 retries"
# before the window ever opens. Capping the pool removes that failure.
# This has to run before numpy is imported, hence living at package import.
for _var in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    _os.environ.setdefault(_var, "1")

from .console import setup as _setup_console  # noqa: E402

_setup_console()
