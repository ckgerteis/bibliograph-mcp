<!-- One change per pull request. First line: what a user of the server sees differently. -->

## What changes

## Why

<!-- The fault or the need, with the request that showed it if there was one. -->

## Checks

- [ ] `python -m pytest -q tests` and `python tests/smoke_stdio.py` pass locally
- [ ] `CHANGELOG.md` has a line for this under the version at the top
- [ ] A new or changed tool is reflected in the README's tool table (the smoke test compares them)
- [ ] `python tests/check_installer_identity.py` passes

- [ ] Nothing from my machine (paths, credentials, `.env`) is in the diff
