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

Do not commit the generated runtime, virtual environments, local databases, or VSIX builds.

## Publish

Upload the new VSIX through [Marketplace Publisher Management](https://marketplace.visualstudio.com/manage) under the existing `charliekarstan` publisher.

The extension's `name` and `publisher` must remain unchanged. Increase its version for each Marketplace update.

After publication, create an annotated Git tag and a GitHub release for the same version.

Use a separate VS Code profile to test development builds before publishing them.