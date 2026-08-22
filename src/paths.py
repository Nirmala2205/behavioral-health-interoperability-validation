"""Canonical filesystem locations for the project.

Everything that reads or writes a file goes through this module. Hard-coded
relative paths scattered across scripts are the fastest way to make a project
non-reproducible on someone else's machine, and reproducibility is an explicit
success condition (Blueprint Section 19: "another technically competent person
can reproduce the experiment").
"""

from __future__ import annotations

from pathlib import Path

# src/paths.py -> src/ -> project root
ROOT = Path(__file__).resolve().parent.parent

CONFIG = ROOT / "config"

DATA = ROOT / "data"
DATA_RAW = DATA / "raw"
DATA_SOURCE = DATA / "source"
DATA_EXPECTED = DATA / "expected"
DATA_EXCHANGED = DATA / "exchanged"
DATA_RECEIVED = DATA / "received"
DATA_PROCESSED = DATA / "processed"

FHIR = ROOT / "fhir"
FHIR_EXCHANGE = FHIR / "exchange"
FHIR_EXAMPLES = FHIR / "examples"

SQL = ROOT / "sql"
OUTPUTS = ROOT / "outputs"
POWERBI = ROOT / "powerbi"

_ALL_WRITABLE = [
    DATA_RAW,
    DATA_SOURCE,
    DATA_EXPECTED,
    DATA_EXCHANGED,
    DATA_RECEIVED,
    DATA_PROCESSED,
    FHIR_EXCHANGE,
    FHIR_EXAMPLES,
    OUTPUTS,
]


def ensure_dirs() -> None:
    """Create every output directory the pipeline writes into."""
    for directory in _ALL_WRITABLE:
        directory.mkdir(parents=True, exist_ok=True)


def scenario_dir(base: Path, scenario_id: str) -> Path:
    """Per-scenario subdirectory, so Scenario A and B never overwrite each other.

    Stage C compares results across scenarios; that comparison is only possible
    if both scenarios' outputs survive a single pipeline run.
    """
    path = base / f"scenario_{scenario_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path
