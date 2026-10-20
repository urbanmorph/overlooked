import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE, HERE.parents[1], HERE.parents[1] / "experiments" / "model_check"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
