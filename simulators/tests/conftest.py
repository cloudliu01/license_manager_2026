from __future__ import annotations

import sys
from pathlib import Path


SIM_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SIM_SRC))
