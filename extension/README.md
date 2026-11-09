# DataGym for VS Code

Practice pandas and NumPy with a three-panel view of the source data, your result, and the target result. Solutions are written in a normal VS Code Python editor, with hints and explanations available from the training panel.

**v0.1 requires a local checkout of the DataGym source and a Python virtual environment.** This VSIX only contains the VS Code integration, not the Python backend or all exercise packs. The full installation instructions are in the repository's `README.md` and `START_HERE.md`.

## Setup

1. Clone or download DataGym. In the project folder, create `.venv` and install `requirements.txt`.
2. Install this VSIX through VS Code's **Install from VSIX...** command.
3. Open the DataGym project folder in VS Code (it must contain `app.py`).
4. Run **DataGym: Open Trainer** from the Command Palette.
5. Edit `workspace/solution.py` and press `Cmd+Option+N` for the next exercise.

DataGym starts its local Python server automatically. It evaluates **saved** Python in a separate process. The process is not a security sandbox; execute only trusted local code and exercise packs.

The extension exposes commands to open the trainer, load the next exercise, reset code, reveal the answer, and show a hint.

MIT licensed. See `LICENSE`.
