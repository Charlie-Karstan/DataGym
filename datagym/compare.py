"""Compare actual pandas/NumPy objects rather than matching solution strings."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compare(actual, target) -> tuple[bool, str]:
    if type(actual) is not type(target):
        return False, f'Type mismatch: expected {type(target).__name__}, got {type(actual).__name__}.'
    if isinstance(target, pd.DataFrame):
        if actual.shape != target.shape:
            return False, f'Shape mismatch: expected {target.shape}, got {actual.shape}.'
        try:
            pd.testing.assert_frame_equal(actual, target, check_exact=False, rtol=1e-7, atol=1e-10)
        except AssertionError as err:
            return False, _shorten(str(err))
        return True, 'Exact structure and values match (numeric tolerance applied).'
    if isinstance(target, pd.Series):
        if actual.shape != target.shape:
            return False, f'Shape mismatch: expected {target.shape}, got {actual.shape}.'
        try:
            pd.testing.assert_series_equal(actual, target, check_exact=False, rtol=1e-7, atol=1e-10)
        except AssertionError as err:
            return False, _shorten(str(err))
        return True, 'Series values, index, name and dtype match.'
    if isinstance(target, np.ndarray):
        if actual.shape != target.shape:
            return False, f'Shape mismatch: expected {target.shape}, got {actual.shape}.'
        if actual.dtype != target.dtype:
            return False, f'Dtype mismatch: expected {target.dtype}, got {actual.dtype}.'
        if np.issubdtype(target.dtype, np.number):
            matched = bool(np.allclose(actual, target, rtol=1e-7, atol=1e-10, equal_nan=True))
        else:
            matched = bool(np.array_equal(actual, target))
        return (matched, 'Array matches.' if matched else 'One or more array elements differ.')
    if isinstance(target, (int, float, str, bool, np.generic)):
        try:
            if isinstance(target, (float, np.floating)):
                matched = bool(np.isclose(actual, target, rtol=1e-7, atol=1e-10, equal_nan=True))
            else:
                matched = bool(actual == target)
        except Exception:
            matched = False
        return matched, 'Value matches.' if matched else f'Expected {target!r}; received {actual!r}.'
    return False, f'Unsupported target type: {type(target).__name__}.'


def _shorten(message: str) -> str:
    return ' '.join(message.split())[:260]
