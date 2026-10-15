"""Run each test module in its own process (every Lambda is named lambda_function)."""
import pathlib
import subprocess
import sys

here = pathlib.Path(__file__).parent
failed = 0
for t in sorted(here.glob("test_*.py")):
    r = subprocess.run([sys.executable, "-m", "unittest", f"tests.{t.stem}", "-q"], cwd=here.parent)
    failed |= r.returncode
sys.exit(failed)
