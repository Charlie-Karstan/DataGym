"""Reproducible, small, intentionally realistic quantitative research datasets.

Every dataset is deterministic for a given seed, and builds from the existing
NumPy / pandas requirements. This is local exercise data, not market quotes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

QUANT_KINDS = {
    'price_panel', 'asset_panel', 'option_chain', 'dispersion',
    'market_events', 'xi_state', 'mot_grid', 'sim_paths',
    'risk_matrix', 'feature_matrix',
}


def build_quant_dataset(spec: dict, seed: int):
    kind = spec['kind']
    if kind not in QUANT_KINDS:
        raise ValueError(f'Unknown quant dataset: {kind}')
    rng = np.random.default_rng(seed)

    if kind == 'price_panel':
        n = int(spec.get('rows', 18))
        dates = pd.bdate_range('2026-09-01', periods=n, name='date')
        symbols = ['AAPL', 'MSFT', 'NVDA', 'JPM']
        returns = rng.normal(0.0006, 0.016, size=(n, len(symbols)))
        prices = np.round(np.array([120., 290., 160., 170.]) * np.exp(returns.cumsum(axis=0)), 2)
        df = pd.DataFrame(prices, index=dates, columns=symbols)
        if spec.get('gaps', True) and n >= 12:
            df.iloc[2, 1] = np.nan
            df.iloc[7, 2] = np.nan
            df.iloc[11, 0] = np.nan
        return df

    if kind == 'asset_panel':
        n = int(spec.get('dates', 6))
        dates = pd.bdate_range('2026-10-01', periods=n)
        symbols = ['AAPL', 'MSFT', 'NVDA', 'JPM']
        index = pd.MultiIndex.from_product([dates, symbols], names=['date', 'ticker'])
        size = len(index)
        raw_weights = rng.uniform(0.5, 2.0, size=(n, 4))
        weights = raw_weights / raw_weights.sum(axis=1, keepdims=True)
        df = pd.DataFrame({
            'date': index.get_level_values('date'),
            'ticker': index.get_level_values('ticker'),
            'sector': np.tile(['Tech', 'Tech', 'Tech', 'Banks'], n),
            'ret': np.round(rng.normal(0, 0.025, size=size), 4),
            'volume': rng.integers(100, 1000, size=size),
            'close': np.round(rng.uniform(70, 350, size=size), 2),
            'weight': weights.reshape(-1).round(7),
            'beta': np.tile([1.10, 0.9, 1.6, 1.05], n),
        })
        return df

    if kind == 'option_chain':
        expiries = pd.to_datetime(['2026-12-18', '2027-01-15', '2027-02-19'])
        strikes = [95., 100., 105.]
        rows = []
        for exp_i, expiry in enumerate(expiries):
            for strike in strikes:
                for cp in ('C', 'P'):
                    mny = abs(strike - 100) / 100
                    iv = round(0.18 + 0.025 * exp_i + 0.3 * mny + rng.uniform(-0.006, 0.006), 4)
                    mid = 1.2 + 0.2 * exp_i + (100-strike if cp == 'C' else strike-100) * 0.27
                    mid = max(mid + rng.uniform(-0.16, 0.16), 0.45)
                    rows.append({
                        'expiry': expiry, 'strike': strike, 'cp': cp,
                        'bid': round(mid - 0.10, 2), 'ask': round(mid + 0.10, 2),
                        'iv': iv, 'volume': int(rng.integers(5, 300)),
                        'spot': 100.0, 'delta': round(
                            (0.5 if cp == 'C' else -0.5) + (100-strike)*0.03, 3),
                    })
        return pd.DataFrame(rows)

    if kind == 'dispersion':
        symbols = ['INDEX', 'AAPL', 'MSFT', 'NVDA', 'JPM']
        weights = [1., 0.25, 0.25, 0.25, 0.25]
        dates = pd.bdate_range('2026-10-01', periods=int(spec.get('dates', 5)))
        rows = []
        for date in dates:
            for name, weight in zip(symbols, weights):
                base_iv = 0.20 if name == 'INDEX' else 0.24
                rows.append({
                    'date': date, 'symbol': name, 'weight': weight,
                    'iv': round(base_iv + rng.normal(0, .018), 4),
                    'realized_vol': round(base_iv * rng.uniform(0.72, 1.05), 4),
                    'vega': round(rng.uniform(20, 120), 2),
                    'delta': round(rng.normal(0, 0.25), 4),
                })
        return pd.DataFrame(rows)

    if kind == 'market_events':
        rows = []
        base = pd.Timestamp('2026-10-12 10:00:00')
        for i in range(6):
            for symbol in ('AAPL', 'MSFT'):
                is_quote = i % 2 == 0
                mid = 100 + (0 if symbol == 'AAPL' else 40) + i * 0.4
                rows.append({
                    'time': base + pd.Timedelta(minutes=i),
                    'symbol': symbol,
                    'event': 'quote' if is_quote else 'trade',
                    'bid': round(mid - 0.08, 2) if is_quote else np.nan,
                    'ask': round(mid + 0.08, 2) if is_quote else np.nan,
                    'trade_px': np.nan if is_quote else round(mid + rng.normal(0, .03), 2),
                    'size': 0 if is_quote else int(rng.integers(10, 100)),
                })
        return pd.DataFrame(rows).sort_values(['time', 'symbol']).reset_index(drop=True)

    if kind == 'xi_state':
        n = int(spec.get('rows', 16))
        dates = pd.bdate_range('2026-09-01', periods=n, name='date')
        p = rng.beta(3, 3, size=n).round(4)
        ret = rng.normal(0.0004, 0.018, n)
        return pd.DataFrame({
            'p_risk': p,
            'p_stress': (1. - p).round(4),
            'signal': np.round(rng.normal(0, 0.7, n), 3),
            'forecast': np.round(rng.normal(0, 0.013, n), 4),
            'ret': np.round(ret, 4),
            'benchmark': np.round(rng.normal(.0003, .013, n), 4),
            'vol': np.round(rng.uniform(0.12, 0.32, n), 3),
            'cost': np.round(rng.uniform(.0001, .0006, n), 5),
        }, index=dates)

    if kind == 'mot_grid':
        s0_values = [90., 100., 110.]
        s1_values = [80., 95., 105., 120.]
        probabilities = rng.dirichlet(np.ones(len(s0_values) * len(s1_values)))
        rows = []
        for i, s0 in enumerate(s0_values):
            for j, s1 in enumerate(s1_values):
                rows.append({
                    's0': s0, 's1': s1, 'mass': round(float(probabilities[i*4+j]), 8),
                    'payoff': max((s0 + s1)/2 - 100., 0.),
                    'move': s1 - s0,
                })
        return pd.DataFrame(rows)

    if kind == 'sim_paths':
        n = int(spec.get('paths', 6))
        steps = int(spec.get('steps', 9))
        shocks = rng.normal(0.0003, 0.018, size=(n, steps-1))
        log_paths = np.c_[np.zeros(n), shocks.cumsum(axis=1)]
        return np.round(100. * np.exp(log_paths), 4)

    if kind == 'risk_matrix':
        x = rng.normal(size=(5, 5))
        return np.round((x @ x.T)/20 + np.eye(5)*.04, 6)

    if kind == 'feature_matrix':
        n = int(spec.get('rows', 12))
        x = rng.normal(size=(n, 3))
        y = 0.4*x[:, 0] - 0.7*x[:, 1] + 0.2*x[:, 2] + rng.normal(0, .03, n)
        return np.column_stack((x, y)).round(5)

    raise AssertionError('Unreachable')
