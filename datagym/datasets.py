"""Deterministic small datasets: same seed -> identical questions and targets."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .quant_datasets import QUANT_KINDS, build_quant_dataset

SECTORS = {
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology',
    'AMD': 'Technology', 'GOOG': 'Technology', 'META': 'Technology',
    'TSLA': 'Consumer', 'AMZN': 'Consumer', 'WMT': 'Consumer',
    'COST': 'Consumer', 'JPM': 'Financials', 'BAC': 'Financials',
    'V': 'Financials', 'XOM': 'Energy', 'PFE': 'Healthcare',
    'ORCL': 'Technology', 'IBM': 'Technology', 'UBER': 'Consumer',
}
SYMBOLS = list(SECTORS)


def build_dataset(spec: dict, seed: int):
    rng = np.random.default_rng(seed)
    kind = spec['kind']
    if kind == 'inline_dataframe':
        # Hand-authored table stored directly in JSON, without editing Python.
        df = pd.DataFrame(spec['records'])
        if 'columns' in spec:
            df = df.loc[:, spec['columns']]
        if spec.get('index_column') is not None:
            df = df.set_index(spec['index_column'])
        elif 'index' in spec:
            if len(spec['index']) != len(df):
                raise ValueError('inline_dataframe index length must equal number of records')
            df.index = pd.Index(spec['index'], name=spec.get('index_name'))
        return df
    if kind == 'inline_array':
        return np.array(spec['values'], dtype=spec.get('dtype'))
    if kind == 'stocks':
        n = int(spec.get('rows', 10))
        if not 4 <= n <= len(SYMBOLS):
            raise ValueError('stocks rows must be between 4 and 18')
        remaining = [s for s in SYMBOLS if s not in ('AAPL', 'MSFT', 'NVDA', 'JPM')]
        extra = list(rng.choice(remaining, size=n - 4, replace=False))
        tickers = ['AAPL', 'MSFT', 'NVDA', 'JPM', *extra]
        df = pd.DataFrame({
            'sector': [SECTORS[s] for s in tickers],
            'price': rng.integers(35, 351, size=n).astype(float) + rng.integers(0, 100, size=n) / 100,
            'volume': rng.integers(6, 80, size=n) * 10,
            'return_1d': np.round(rng.normal(0, 0.027, size=n), 3),
            'pe': rng.integers(7, 49, size=n).astype(float),
        }, index=pd.Index(tickers, name='ticker'))
        return df
    if kind == 'trades':
        n = int(spec.get('rows', 14))
        return pd.DataFrame({
            'symbol': rng.choice(['AAPL', 'MSFT', 'NVDA', 'JPM'], size=n),
            'side': rng.choice(['BUY', 'SELL'], size=n),
            'qty': rng.integers(2, 75, size=n),
            'price': np.round(rng.uniform(50, 300, size=n), 2),
            'fee': np.round(rng.uniform(0.1, 3.0, size=n), 2),
        })
    if kind == 'returns':
        n = int(spec.get('rows', 9))
        dates = pd.bdate_range('2026-10-05', periods=n)
        df = pd.DataFrame(
            np.round(rng.normal(0, 0.021, size=(n, 4)), 3),
            columns=['AAPL', 'MSFT', 'NVDA', 'JPM'],
            index=pd.Index(dates.strftime('%Y-%m-%d'), name='date'),
        )
        return df
    if kind == 'matrix':
        return rng.integers(0, 11, size=(5, 6))
    if kind == 'vector':
        return rng.integers(0, 21, size=12)
    if kind in QUANT_KINDS:
        return build_quant_dataset(spec, seed)
    raise ValueError(f'Unknown dataset kind: {kind!r}')


def variable_name(spec: dict) -> str:
    return 'arr' if spec['kind'] in {'matrix', 'vector', 'inline_array', 'sim_paths', 'risk_matrix', 'feature_matrix'} else 'df'
