"""Let tests import `mcls` when pytest runs from mod-classifier/."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
