# Releasing DataGym

The repository and the Marketplace extension are **two distributions of the same codebase**.

## Before the first public push

1. Edit the copyright holder in `LICENSE` and `extension/LICENSE` if you prefer a specific author name instead of "DataGym contributors".
2. Check every tracked file with `git status` and `git diff --cached --name-only`. Do not commit `.venv`, SQLite progress, generated `solution.py`, secrets, or VSIX files.
3. Test a fresh checkout on your Mac. The extension currently needs the repository open and a `.venv` containing its dependencies.
4. Add an actual `repository` URL to `extension/package.json` after creating your GitHub repository. The URL is not filled in because your account/repository address was not provided.
5. Register a publisher in the [Visual Studio Marketplace](https://marketplace.visualstudio.com/manage), then set `publisher` in `extension/package.json` to that exact publisher ID. It is initially `datagym-local` as a development placeholder.

## Test

From the repository root:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m datagym.cli validate
node --check extension/extension.js
node --check static/app.js
node --test tests/test_extension.js
```

## Package the extension

```bash
cd extension
npx @vscode/vsce ls
npx @vscode/vsce package
```

Check that the package contains `extension.js`, `package.json`, `README.md`, and `LICENSE`. The Python engine and question packs remain outside the VSIX for this preview release; users obtain them from GitHub using the documented setup.

Test the new VSIX with **Extensions → ... → Install from VSIX...**, ideally in a separate VS Code profile. Check opening, next exercise, the existing solution tab, correct/wrong evaluation, hints, reset, and persistence after restart.

## Publish

1. Create the public `DataGym` GitHub repository; push the audited source and tag it `v0.1.0`.
2. Create a GitHub release describing the setup requirements and linking to the Marketplace once published.
3. Upload the tested VSIX through your Marketplace publisher account.
4. For an update, make changes here, run tests, bump the version in `extension/package.json`, tag a new release, and publish a newly built VSIX. A GitHub push alone does not update the Marketplace.

Do not publish a package that still claims a publisher ID you have not registered. Do not use the old VSIX found in the original local project: build from `extension/` instead.
