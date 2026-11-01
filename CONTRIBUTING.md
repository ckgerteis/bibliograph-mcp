# Contributing to bibliograph-mcp

Issues and pull requests are welcome. This file says what a change needs to carry so that it can be
merged without a second round.

## Before you start

- **Report the fault, not the fix, first** if you are unsure. An issue with the request that failed,
  the envelope or log you got back, the source key involved, and the Python version takes five
  minutes and often settles the design before any code is written.
- **Read the README's "Response format" section.** Every tool answers with one typed envelope, and
  every query-answering tool deposits a receipt. A change that returns something outside the
  envelope, or that answers a query without a receipt, will be asked to change.
- **The server does not summarise, rank by relevance of its own, or invent.** It reports what a
  source returned and how it matched. That is the point of the project; changes that add
  interpretation on the server side are out of scope.
- **Each source keeps its own behaviour.** bibliograph gathers `src/bibliograph/sources/*/server.py` modules
  into one process (`src/bibliograph/server.py`); a source's rate limits, credentials, credit lines and
  diagnostics are its own. Read `docs/sources/<source>/README.md` before changing a source, and
  `docs/CONTRACT.md` before changing anything that an outside `--with` package also relies on
  (`src/bibliograph/mediation.py`, `src/bibliograph/ledger.py`, `src/bibliograph/server.py`'s loading contract).

## Setting up

```bash
git clone https://github.com/ckgerteis/bibliograph-mcp
cd bibliograph-mcp
python -m venv .venv
.venv/bin/pip install -e ".[test,names]"        # Windows: .venv\Scripts\pip
```

Python 3.10 or later; 3.10, 3.12, 3.13 and 3.14 are what CI runs, on Windows, macOS and Linux.

The names source needs a local index before its tests that touch it will pass:

```bash
set JMNEDICT_DATA_DIR=C:\Tools\jmnedict-data
bibliograph-build-names
```

## Running the checks

```bash
python -m pytest -q
python set_version.py --check
```

### The Claude Desktop bundle

`python mcpb/build.py` writes `dist/bibliograph-mcp-<version>.mcpb`. The bundle vendors nothing: its
manifest declares `server.type: "uv"`, and `pyproject.toml`, `uv.lock` and the entry point
`main.py` sit at the bundle root, where Claude Desktop's UV runtime looks. The app runs `uv sync`
there when the extension is installed and reuses that environment at every launch; a
`pyproject.toml` anywhere else makes the app skip the install step and download everything inside
the launch timeout. Two checks gate the bundle, and both must pass before a change to `mcpb/` is
merged:

```bash
npx --yes @anthropic-ai/mcpb validate build/bundle/manifest.json
python tests/bundle_handshake.py dist/*.mcpb --cold
```

`mcpb validate` checks the manifest. The handshake gate unpacks the bundle, runs the install phase
the host runs (`uv sync` at the bundle root), then launches it with the manifest's own args and
requires the `initialize` reply to name the manifest's version within thirty seconds, on an empty
uv cache and under interpreters other than the one that built it (run with `--python 3.13` or
`--python 3.14`; not 3.12, which the family's earlier bundles pinned and this one does not). A
bundle that builds is not a bundle that runs.

## What a pull request should carry

- One change per pull request, described in the first line of the description in terms of what a
  user of the server sees differently.
- A `CHANGELOG.md` line under the version at the top of the file. Entries are written for the
  reader who has to decide whether to upgrade: say what was wrong, what changed, and what it costs.
- Tests where the change is testable without the network: `tests/<source>` uses captured responses
  under `tests/<source>/fixtures`, and a parser change should come with the response that exposed
  it.
- No credentials, no paths from your machine, and no dictionary data files.

## Versions and releases

Releases are tags cut by the maintainer; contributors do not bump versions. A version touches
`pyproject.toml`, `.zenodo.json`, `CITATION.cff`, `mcpb/manifest.template.json`, the package's
`__version__` and the README's pinned install lines — `python set_version.py X.Y.Z` sets all six
in one step and `python set_version.py --check` verifies them. The `CHANGELOG.md` section is
written by hand; `tests/test_release_metadata.py` fails until it exists, and fails whenever any
of the six disagree with `pyproject.toml`. The release workflow
attaches the wheel, the sdist and the bundle to a GitHub release that Zenodo archives under the
concept DOI in the README.

## Conduct

Be direct, be specific, and assume good faith. Security-relevant reports go by the route in
[SECURITY.md](SECURITY.md), not to the public tracker.
