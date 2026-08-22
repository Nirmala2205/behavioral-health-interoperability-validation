"""Pytest configuration: put src/ on the import path.

The project keeps the blueprint's folder names (generate/, transform/,
validate/, metrics/) as top-level modules under src/ rather than nesting them
in an installable package. That keeps the repository layout identical to the
specification a reviewer will have read, at the cost of this three-line shim.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
