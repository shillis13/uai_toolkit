# Third-Party Notices

uai_toolkit is MIT licensed (see `LICENSE`). Its declared Python dependencies are
downloaded from PyPI by pip at install time rather than copied into this repository;
each stays under its own license and copyright holders.

This is a transparency inventory based on the current dependency manifests and
package metadata. Re-check it against upstream license files before publishing any
artifact that bundles dependencies; an inventory is not a substitute for those
license texts or for legal review. License labels were reviewed on 2026-07-26;
because the dependency ranges are not fully pinned, verify the versions resolved
for each release.

## Python packages

| Package | License | Tier in `pyproject.toml` |
|---|---|---|
| pyyaml | MIT | core |
| tomli | MIT | core (Python < 3.11 only) |
| psutil | BSD-3-Clause | `full` |
| httpx | BSD-3-Clause | `full` |
| websockets | BSD-3-Clause | `full` |
| tqdm | MPL-2.0 AND MIT | `full` |
| mcp (Model Context Protocol SDK) | MIT | `mcp` |
| jsonschema | MIT | `mcp` |
| pillow | MIT-CMU | `images` |
| pytest | MIT | `dev` |

Note on **tqdm**: its current package metadata declares `MPL-2.0 AND MIT`. Consult
the upstream license file when redistributing it rather than relying on this summary.

## System binaries

Not distributed here either; installed via the OS package manager. Listed so their
licenses are visible: `zellij` (MIT), `tmux` (ISC), `ripgrep` (MIT OR Unlicense),
`git` (GPL-2.0-only), `node` (MIT), and the npm CLI (Artistic-2.0).

## Node (the vendored `uai_app/` Electron source)

`uai_app/` ships **source only** — `node_modules` is excluded by the materialize
step. Its dependencies are declared in the app's `package.json` files and restored
with `npm ci`, so they are likewise not redistributed here.

## When this changes

Re-run a license review and include every applicable upstream notice/license text if
this repo ever **distributes** dependency code itself, for example by:

- vendoring a library's source into this tree,
- shipping a bundled artifact (PyInstaller/py2exe, a wheel with dependencies
  bundled, or a built Electron `.app`/installer containing `node_modules`).

The following commands can seed that review; inspect their output rather than treating
it as an automatic compliance decision:

```bash
pip install pip-licenses
pip-licenses --with-license-file --format=plain-vertical \
             --output-file=THIRD_PARTY_LICENSES.txt
# Node side, if bundling the app:
npx license-checker --production --out uai_app/THIRD_PARTY_LICENSES.txt
```
