"""Build the Claude Desktop bundle (.mcpb) for bibliograph-mcp.

    python mcpb/build.py                              # one bundle: dist/bibliograph-mcp-<version>.mcpb
    python mcpb/build.py --release-notes v1.0.0       # print that version's CHANGELOG section

The bundle vendors no libraries. Its manifest declares server.type "uv"
(manifest 0.4), and its layout is the one Claude Desktop's UV runtime expects:

    manifest.json
    pyproject.toml        <- at the root: this is what the host looks for
    uv.lock
    main.py               <- the entry point
    src/bibliograph/...
    README.md, LICENSE, NOTICE, CHANGELOG.md, response-schema.json

Claude Desktop does two things with a uv-type bundle, and the layout matters
for both. At install time it looks for pyproject.toml at the bundle root and,
if it is there, takes a uv already on the PATH or downloads its own, then
runs `uv sync` in the bundle folder with a progress bar: that is when the
interpreter and the locked libraries are fetched. If pyproject.toml is not at
the root, the app logs "missing pyproject.toml. Cannot proceed with UV setup"
and installs the extension anyway, with nothing provisioned. At launch time
it runs its own uv with the manifest's args and the bundle folder as the
working directory. This layout, and the reasoning above it, follow the family
convention worked out and proved in semantic-scholar-mcp/cinii-mcp/ndl-mcp
(mcpb 2.1.2 there).

The lock is written at build time by the uv that builds, so the bundle pins
what CI resolved on the release day; tests/bundle_handshake.py then installs
and launches the built bundle the way the host does, under interpreters other
than the one that built it.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10: no tomllib; a regex over [project] is enough here
    tomllib = None

import os


def _load_project(text: str) -> dict:
    """[project] name/version/scripts, via tomllib where present."""
    if tomllib is not None:
        return tomllib.loads(text)["project"]
    proj: dict = {}
    body = text.split("[project]", 1)[1]
    for key in ("name", "version"):
        m = re.search(rf'^{key}\s*=\s*"([^"]+)"', body, re.M)
        if m:
            proj[key] = m.group(1)
    return proj


ROOT = Path(__file__).resolve().parent.parent
# No .python-version in the bundle. uv then takes any installed interpreter
# that satisfies pyproject's requires-python and downloads one only when none
# exists, so most first launches skip the interpreter download. The lock
# resolves for every version the range allows, and tests/bundle_handshake.py
# proves the bundle under several of them before each release.


def _pyproject() -> dict:
    return _load_project((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- release notes

def release_notes(tag: str) -> str:
    version = tag.lstrip("v")
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(version)}\b.*?$(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        return f"See CHANGELOG.md for {version}."
    return m.group(1).strip() + "\n"


# ---------------------------------------------------------------- bundle

def _uv(explicit: str | None) -> str:
    uv = explicit or os.environ.get("UV") or shutil.which("uv")
    if not uv:
        sys.exit("uv is needed to write the bundle's lock file; install it "
                 "(https://docs.astral.sh/uv/) or pass --uv PATH")
    return uv


def build(uv_exe: str | None) -> Path:
    proj = _pyproject()
    name, version = proj["name"], proj["version"]
    template = json.loads((ROOT / "mcpb" / "manifest.template.json").read_text(encoding="utf-8"))
    if template["version"] != version:
        sys.exit(f"manifest.template.json says {template['version']}, pyproject says {version}")
    if template["server"]["type"] != "uv":
        sys.exit('manifest.template.json must declare server.type "uv"; this build vendors nothing')
    if template["server"]["entry_point"] != "main.py":
        sys.exit('manifest.template.json must set entry_point "main.py": the entry point sits beside '
                 "pyproject.toml at the bundle root, where Claude Desktop's UV runtime looks")

    out = ROOT / "build" / "bundle"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # The project, as uv will see it from the bundle root: sources, metadata,
    # the files pyproject refers to, and the entry point. No lib tree, no venv.
    shutil.copytree(ROOT / "src", out / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in ("pyproject.toml", "README.md", "LICENSE", "NOTICE", "CHANGELOG.md"):
        if (ROOT / f).exists():
            shutil.copy(ROOT / f, out / f)
    if (ROOT / "tests" / "response-schema.json").exists():
        shutil.copy(ROOT / "tests" / "response-schema.json", out / "response-schema.json")
    shutil.copy(ROOT / "mcpb" / "main.py", out / "main.py")
    subprocess.run([_uv(uv_exe), "lock", "--directory", str(out)], check=True)
    if not (out / "uv.lock").exists():
        sys.exit("uv lock wrote no uv.lock")

    (out / "manifest.json").write_text(json.dumps(template, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    bundle = dist / f"{name}-{version}.mcpb"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and ".venv" not in p.parts:
                z.write(p, p.relative_to(out).as_posix())
    size = bundle.stat().st_size // 1024
    print(f"built {bundle.relative_to(ROOT)} ({size} KB): server.type=uv, pyproject.toml at the bundle root, "
          f"python: any that satisfies requires-python, platforms {', '.join(template['compatibility']['platforms'])}")
    return bundle


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uv", help="uv executable that writes the lock (default: UV env var, then PATH)")
    ap.add_argument("--release-notes", metavar="TAG")
    a = ap.parse_args()
    if a.release_notes:
        sys.stdout.write(release_notes(a.release_notes))
        return 0
    build(a.uv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
