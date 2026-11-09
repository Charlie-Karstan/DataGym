"""JSON-friendly previews. Limit large objects before they reach the browser."""
from __future__ import annotations

from datetime import date, datetime
import math
import numpy as np
import pandas as pd

MAX_ROWS = 20
MAX_COLS = 12


def fmt(obj):
    if obj is None or obj is pd.NA:
        return 'None'
    if isinstance(obj, (float, np.floating)):
        if math.isnan(float(obj)):
            return 'NaN'
        if math.isinf(float(obj)):
            return '∞' if obj > 0 else '-∞'
        return f'{float(obj):.6g}'
    if isinstance(obj, (bool, np.bool_)):
        return 'True' if obj else 'False'
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def serialize(value) -> dict:
    if isinstance(value, pd.DataFrame):
        v = value.iloc[:MAX_ROWS, :MAX_COLS]
        return {
            'kind': 'dataframe', 'type': 'DataFrame', 'shape': list(value.shape),
            'meta': f'{value.shape[0]} rows × {value.shape[1]} columns',
            'columns': [fmt(c) for c in v.columns],
            'index': [fmt(i) for i in v.index],
            'index_name': fmt(value.index.name) if value.index.name is not None else 'index',
            'rows': [[fmt(x) for x in row] for row in v.itertuples(index=False, name=None)],
            'dtypes': [str(d) for d in v.dtypes],
            'truncated': value.shape[0] > MAX_ROWS or value.shape[1] > MAX_COLS,
        }
    if isinstance(value, pd.Series):
        v = value.iloc[:MAX_ROWS]
        return {
            'kind': 'series', 'type': 'Series', 'shape': list(value.shape),
            'meta': f'{len(value)} values · dtype {value.dtype}',
            'columns': [fmt(value.name) if value.name is not None else 'value'],
            'index': [fmt(i) for i in v.index],
            'index_name': fmt(value.index.name) if value.index.name is not None else 'index',
            'rows': [[fmt(x)] for x in v.tolist()],
            'dtypes': [str(value.dtype)], 'truncated': len(value) > MAX_ROWS,
        }
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return serialize(value.item())
        if value.ndim == 1:
            v = value[:MAX_ROWS]
            rows = [[fmt(x)] for x in v]
            columns = ['value']
        elif value.ndim == 2:
            v = value[:MAX_ROWS, :MAX_COLS]
            rows = [[fmt(x) for x in row] for row in v]
            columns = [str(i) for i in range(v.shape[1])]
        else:
            return {'kind': 'scalar', 'type': 'ndarray', 'shape': list(value.shape),
                    'meta': f'shape {value.shape} · dtype {value.dtype}',
                    'value': f'{value.ndim}-dimensional array (preview not supported)'}
        return {
            'kind': 'array', 'type': 'ndarray', 'shape': list(value.shape),
            'meta': f'shape {value.shape} · dtype {value.dtype}',
            'columns': columns, 'index': [str(i) for i in range(len(rows))],
            'index_name': 'row', 'rows': rows, 'dtypes': [str(value.dtype)] * len(columns),
            'truncated': value.shape[0] > MAX_ROWS or (value.ndim == 2 and value.shape[1] > MAX_COLS),
        }
    if isinstance(value, (str, int, float, bool, np.generic)) or value is None:
        return {'kind': 'scalar', 'type': type(value).__name__, 'shape': [],
                'meta': f'{type(value).__name__} · scalar', 'value': fmt(value)}
    return {'kind': 'scalar', 'type': type(value).__name__, 'shape': [],
            'meta': type(value).__name__, 'value': repr(value)[:150]}
