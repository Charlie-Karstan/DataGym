# Start DataGym

DataGym is a VS Code extension backed by a local Python project. **This v0.1 release still needs the project folder open**; the VSIX is not a standalone Python installation.

## First-time setup

1. Download or clone the repository, and open the `DataGym` folder in a terminal.
2. Set up the Python environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

   On Windows, use `.venv\\Scripts\\activate` in Command Prompt.
3. Install the DataGym `.vsix` in VS Code with **Extensions → ... → Install from VSIX...**. If needed, build it from `extension/` with `npx @vscode/vsce package`.
4. Open the project folder (containing `app.py`) in VS Code.
5. Open the Command Palette and run **DataGym: Open Trainer**.

## Each time you open VS Code

Open the same `DataGym` folder and run **DataGym: Open Trainer**. The extension starts the backend automatically; you do not need to run `python app.py` yourself.

Write code in the generated `workspace/solution.py`, assigning your answer to `result`. Use **Cmd+Option+N** to advance. The file is overwritten with a fresh starter on each exercise; the SQLite progress file is stored separately in `workspace/`.

For installation, developer commands, limitations, and adding exercises, see [`README.md`](README.md).
