"""bibliograph.installer must be byte-identical to install.py in the six server repos.

CI cannot see the six repositories, so this compares against the sha256
recorded in VENDORED.sha256 — the same file the six carry, copied here when
install.py changes. A mismatch means one side moved without the other.
"""
import hashlib
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
want = None
for line in (root / "VENDORED.sha256").read_text(encoding="utf-8").splitlines():
    if line.strip().endswith(" install.py"):
        want = line.split()[0]
have = hashlib.sha256((root / "src" / "bibliograph" / "installer.py").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
if want is None:
    sys.exit("VENDORED.sha256 has no install.py line")
if want != have:
    sys.exit(f"installer.py {have[:12]} != family install.py {want[:12]}")
print("installer.py matches the family's install.py")
