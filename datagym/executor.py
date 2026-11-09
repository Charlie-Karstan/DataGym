"""Parent-side execution orchestration and validity checks."""
from __future__ import annotations

import codeop
import json
import subprocess
import sys
from pathlib import Path

from .paths import ROOT

WORKER = Path(__file__).resolve().parent / 'worker.py'


def check_syntax(source: str) -> tuple[bool, str]:
    try:
        program = codeop.compile_command(source, filename='workspace/solution.py', symbol='exec')
    except (SyntaxError, OverflowError, ValueError) as exc:
        return False, f'Syntax: {str(exc).splitlines()[0][:130]}'
    if program is None:
        return False, 'Incomplete expression — showing last valid preview.'
    return True, ''


def evaluate(exercise, source: str, timeout: float = 3.5) -> dict:
    valid, message = check_syntax(source)
    if not valid:
        return {'status': 'incomplete', 'message': message}
    payload = {'exercise': exercise.as_worker_payload(), 'source': source}
    try:
        response = subprocess.run(
            [sys.executable, '-I', str(WORKER)], input=json.dumps(payload),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=timeout, cwd=ROOT, check=False,
        )
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'message': f'Execution timed out after {timeout:.1f} seconds.'}
    if response.returncode != 0:
        return {'status': 'error', 'message': 'Python worker crashed: ' + response.stderr[-300:]}
    try:
        return json.loads(response.stdout)
    except json.JSONDecodeError:
        return {'status': 'error', 'message': 'Invalid worker response. Do not print extremely large values.'}
