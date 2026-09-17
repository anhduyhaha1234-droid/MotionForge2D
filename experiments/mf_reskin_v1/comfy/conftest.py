import sys
from pathlib import Path

# The adapter package lives next to the tests; make it importable from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
