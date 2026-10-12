"""This repository's copies of family files must be byte-identical to the six server repos.

bibliograph.installer must equal install.py there, and set_version.py and
tests/test_release_metadata.py must equal theirs. CI cannot see the six
repositories, so this compares against the sha256 recorded in VENDORED.sha256
— the same file the six carry, copied here when a vendored file changes. A
mismatch means one side moved without the other.
"""
import hashlib
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
want = {}
for line in (root / "VENDORED.sha256").read_text(encoding="utf-8").splitlines():
    if line.strip():
        h, rel = line.split(None, 1)
        want[rel.strip()] = h

# family path in VENDORED.sha256 -> this repository's copy
copies = {
    "install.py": root / "src" / "bibliograph" / "installer.py",
    "set_version.py": root / "set_version.py",
    "tests/test_release_metadata.py": root / "tests" / "test_release_metadata.py",
}
bad = 0
for rel, path in copies.items():
    if rel not in want:
        print(f"VENDORED.sha256 has no {rel} line")
        bad += 1
        continue
    have = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    if have != want[rel]:
        print(f"{path.relative_to(root).as_posix()} {have[:12]} != family {rel} {want[rel][:12]}")
        bad += 1
    else:
        print(f"{path.relative_to(root).as_posix()} matches the family's {rel}")
sys.exit(1 if bad else 0)
