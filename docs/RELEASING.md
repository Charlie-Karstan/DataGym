# Releasing DataGym

DataGym's GitHub repository contains the source. The VS Code Marketplace distributes the extension built from that source.

## Release checklist

1. Merge tested changes into `main`.
2. Update `extension/package.json`, both READMEs, and `CHANGELOG.md`.
3. Run the Python and JavaScript test suites.
4. Build the VSIX from `main` and verify that the Python runtime and exercise packs are included.
5. Test installation in a separate VS Code profile without opening the DataGym source folder.
6. Upload the new VSIX to the existing Marketplace listing.
7. Tag the released commit and create a corresponding GitHub release.

## Verify

From the repository root:

```bash
python -m pytest -q
python -m datagym.cli validate
node --check extension/extension.js
node --check static/app.js
node --test tests/test_extension.js
```

## Package

```bash
cd extension
npx --yes @vscode/vsce package
```

The `vscode:prepublish` script stages the Python engine, exercise packs, and frontend into `extension/runtime/`.

Verify the generated VSIX contains `runtime/app.py`, `runtime/datagym/`, `runtime/exercise_packs/`, and `runtime/static/`.

Run the desktop acceptance test from the repository root with VS Code and Python 3.11+ installed.

```bash
node tests/vscode/run.js extension/datagym-vscode-0.2.2.vsix
```

The runner installs the VSIX and Microsoft extensions in a disposable profile, opens the trainer, and checks Pylance completions and import definitions in `solution.py`. Set `DATAGYM_TEST_PYTHON_ENVS=0` to exercise legacy interpreter selection, `DATAGYM_TEST_REQUIRE_TRUST=1` to grant Workspace Trust interactively, or `DATAGYM_TEST_RESTRICTED_REOPEN=1` to test reopening a pending launch from Restricted Mode. For an offline run, set `DATAGYM_TEST_EXTENSION_CACHE` to a directory of installed Microsoft extensions, `PIP_NO_INDEX=1`, and `PIP_FIND_LINKS` to a directory of compatible Python wheels.

Do not commit the generated runtime, virtual environments, local databases, or VSIX builds.

## Publish

Upload the new VSIX through [Marketplace Publisher Management](https://marketplace.visualstudio.com/manage) under the existing `charliekarstan` publisher.

The extension's `name` and `publisher` must remain unchanged. Increase its version for each Marketplace update.

After publication, create an annotated Git tag and a GitHub release for the same version.

Use a separate VS Code profile to test development builds before publishing them.
