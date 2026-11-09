"""Apply focused changes to the EXISTING DataGym project; no new installation.

Requires this file, make_quant_packs.py, and datagym/quant_datasets.py in
an existing project tree. Never overwrites core.json or progress.sqlite3.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent

if not (ROOT / 'datagym' / 'quant_datasets.py').is_file():
    raise SystemExit('Missing datagym/quant_datasets.py: put that new file in the existing project first.')
if not (ROOT / 'scripts' / 'make_quant_packs.py').is_file():
    raise SystemExit('Missing make_quant_packs.py: put that new file in the existing project first.')

changes = {}

def edit(path: str, transform):
    file = ROOT / path
    if not file.is_file():
        raise SystemExit(f'Missing required existing file: {path}')
    original = file.read_text(encoding='utf-8')
    updated = transform(original)
    changes[file] = updated


def patch_datasets(s: str) -> str:
    if 'from .quant_datasets import ' not in s:
        marker = 'import pandas as pd\n'
        assert marker in s, 'Unexpected datagym/datasets.py: pandas import missing'
        s = s.replace(marker, marker + '\nfrom .quant_datasets import QUANT_KINDS, build_quant_dataset\n', 1)
    if 'if kind in QUANT_KINDS:' not in s:
        marker = "    raise ValueError(f'Unknown dataset kind: {kind!r}')"
        assert marker in s, 'Unexpected datagym/datasets.py: unknown kind branch missing'
        s = s.replace(marker, "    if kind in QUANT_KINDS:\n        return build_quant_dataset(spec, seed)\n" + marker, 1)
    old = "{'matrix', 'vector', 'inline_array'}"
    new = "{'matrix', 'vector', 'inline_array', 'sim_paths', 'risk_matrix', 'feature_matrix'}"
    if old in s:
        s = s.replace(old, new, 1)
    assert new in s, 'Unexpected datagym/datasets.py: arr variable_name rule not found'
    return s


def patch_library(s: str) -> str:
    s = s.replace("if not 1 <= int(item['difficulty']) <= 3:", "if not 1 <= int(item['difficulty']) <= 5:")
    s = s.replace("Difficulty must be 1, 2, or 3", "Difficulty must be between 1 and 5")
    assert "if not 1 <= int(item['difficulty']) <= 5:" in s, 'Difficulty validator not found in library.py'
    return s


def patch_ui(s: str) -> str:
    # User's v0.1-based patched template and v0.2 both contain this line.
    s = s.replace("'result = ...\\n'", "'result = '")
    s = s.replace("'result = \\n'", "'result = '")
    s = s.replace('Replace ... with an expression. Do not print the answer.',
                  'Write your expression after result =. Do not print the answer.')
    # The generated file should end at result =  (no trailing newline).
    # This does not move the VS Code caret itself, which needs a native extension.
    old = "difficulty not in ('All', '1', '2', '3')"
    new = "difficulty not in ('All', '1', '2', '3', '4', '5')"
    if old in s:
        s = s.replace(old, new)
    assert new in s, 'Difficulty API validation not found in ui_app.py'
    # Make the keyboard shortcut respect filters; user may have done this already.
    s = s.replace("category = body.get('category', 'All')",
                  "category = body.get('category', trainer.category_filter)")
    s = s.replace("difficulty = str(body.get('difficulty', 'All'))",
                  "difficulty = str(body.get('difficulty', trainer.difficulty_filter))")
    return s


def patch_html(s: str) -> str:
    if '<option value="4">Level 4</option>' not in s:
        needle = '<option value="3">Level 3</option>'
        assert needle in s, 'Difficulty dropdown not found in static/index.html'
        s = s.replace(needle, needle + '<option value="4">Level 4</option><option value="5">Level 5</option>', 1)
    s = s.replace('<label>Category <select id="category">', '<label>Track <select id="category">')
    return s


edit('datagym/datasets.py', patch_datasets)
edit('datagym/library.py', patch_library)
edit('datagym/ui_app.py', patch_ui)
edit('static/index.html', patch_html)

# The v0.2 test suite expects the old ellipsis starter. Keep it in sync
# with the deliberately empty assignment (older v0.1 does not have it).
test_file = ROOT / 'tests' / 'test_engine.py'
if test_file.is_file():
    old = test_file.read_text(encoding='utf-8')
    revised = old.replace("assert 'result = ...' in code", "assert code.rstrip().endswith('result =')")
    revised = revised.replace("assert evaluate(trainer.exercise, code)['status'] == 'idle'",
                              "assert evaluate(trainer.exercise, code)['status'] == 'incomplete'")
    changes[test_file] = revised

# Commit each changed file only after ALL source layout checks have succeeded.
for path, source in changes.items():
    compile(source, str(path), 'exec') if path.suffix == '.py' else None
for path, source in changes.items():
    if source != path.read_text(encoding='utf-8'):
        path.write_text(source, encoding='utf-8')
        print('Updated:', path.relative_to(ROOT))

subprocess.run(
    [sys.executable, str(ROOT / 'scripts' / 'make_quant_packs.py')],
    cwd=ROOT,
    check=True
)
print('\nDone. Your original core.json, style.css, and progress.sqlite3 were not modified.')
print('Check: python -m datagym.cli validate')
