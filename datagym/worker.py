"""Execute one local user's candidate in a short-lived process.

This process is NOT a secure sandbox against hostile code. Only use with
trusted local files. Parent imposes a wall-clock timeout.
"""
from __future__ import annotations

# Running an absolute script with `python -I` requires adding the package root.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import contextlib
import io
import json

import numpy as np
import pandas as pd
from datagym.compare import compare
from datagym.datasets import build_dataset, variable_name
from datagym.serialization import serialize


def run(request: dict) -> dict:
    exercise = request['exercise']
    source = request['source']
    dataset = build_dataset(exercise['dataset'], int(exercise['seed']))
    variable = variable_name(exercise['dataset'])
    target_env = {'pd': pd, 'np': np, variable: dataset.copy()}
    exec('result = ' + exercise['reference'], target_env)
    target = target_env['result']
    namespace = {'pd': pd, 'np': np, variable: dataset.copy()}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(source, 'workspace/solution.py', 'exec'), namespace)
        if 'result' not in namespace:
            return {'status': 'no_result', 'message': 'Assign the answer to result, e.g. result = df["price"].'}
        actual = namespace['result']
        if actual is Ellipsis:
            return {
                'status': 'idle',
                'message': 'Replace ... with your Python expression.'
            }
        success, message = compare(actual, target)
        return {'status': 'correct' if success else 'wrong',
                'message': message, 'preview': serialize(actual)}
    except SyntaxError as exc:
        return {'status': 'syntax', 'message': f'{exc.msg} (line {exc.lineno})'}
    except Exception as exc:
        return {'status': 'error', 'message': f'{type(exc).__name__}: {str(exc)[:220]}'}


def main():
    try:
        request = json.loads(sys.stdin.read())
        response = run(request)
    except Exception as exc:
        response = {'status': 'error', 'message': f'Worker: {type(exc).__name__}: {str(exc)[:200]}'}
    sys.stdout.write(json.dumps(response, allow_nan=False))


if __name__ == '__main__':
    main()
