from pathlib import Path
import json
import numpy as np
import pandas as pd

from datagym.compare import compare
from datagym.datasets import build_dataset, variable_name
from datagym.executor import check_syntax, evaluate
from datagym.library import Library
from datagym.serialization import serialize


def test_all_reference_expressions(tmp_path):
    lib = Library(tmp_path / 'test.sqlite3')
    assert lib.import_packs() >= 50
    with lib.connect() as db:
        payloads = [json.loads(x[0]) for x in db.execute('SELECT payload FROM templates')]
    for entry in payloads:
        for seed in (17, 37):
            import random
            r = random.Random(seed)
            params = {name: r.choice(d['choices']) for name, d in entry.get('parameters', {}).items()}
            expr = entry['reference'].format_map(params)
            df = build_dataset(entry['dataset'], seed)
            ns = {variable_name(entry['dataset']): df, 'pd': pd, 'np': np}
            exec('result = ' + expr, ns)
            assert compare(ns['result'], ns['result'])[0]
            assert serialize(ns['result'])['kind'] in {'array', 'series', 'dataframe', 'scalar'}


def test_grading_dimensions_and_values():
    df = pd.DataFrame({'x': [1.0, 2.0]})
    assert compare(df, df.copy())[0]
    assert not compare(df['x'], df[['x']])[0]
    assert not compare(df.iloc[::-1], df)[0]
    assert not compare(np.array([1, 2]), np.array([[1, 2]]))[0]
    assert compare(0.1 + 0.2, 0.3)[0]


def test_syntax_state():
    assert not check_syntax('result = df.loc[')[0]
    assert check_syntax('result = df["price"]')[0]
    assert not check_syntax('result = df + )')[0]


def test_executor_real_process(tmp_path):
    lib = Library(tmp_path / 't.sqlite3')
    lib.import_packs()
    with lib.connect() as db:
        entry = json.loads(db.execute('SELECT payload FROM templates WHERE id="sel-series"').fetchone()[0])
    from datagym.library import Exercise
    exercise = Exercise(entry['id'], entry['title'], entry['instructions'],
                        entry['category'], entry['difficulty'], entry['hint'],
                        entry['reference'], entry['dataset'], 123, 'df')
    good = evaluate(exercise, 'result = df["price"]')
    assert good['status'] == 'correct', good
    bad = evaluate(exercise, 'result = df[["price"]]')
    assert bad['status'] == 'wrong'
    incomplete = evaluate(exercise, 'result = df[')
    assert incomplete['status'] == 'incomplete'
    runtime = evaluate(exercise, 'result = df["not_a_column"]')
    assert runtime['status'] == 'error'


def test_custom_inline_dataset():
    frame = build_dataset({'kind': 'inline_dataframe', 'records': [
        {'symbol': 'AAPL', 'bid': 11}, {'symbol': 'MSFT', 'bid': 12}],
        'index_column': 'symbol'}, 99)
    assert frame.loc['MSFT', 'bid'] == 12
    arr = build_dataset({'kind': 'inline_array', 'values': [[1, 2], [3, 4]]}, 42)
    assert arr.shape == (2, 2)
    assert variable_name({'kind': 'inline_array'}) == 'arr'


def test_dataset_generation_is_reproducible():
    datasets = [
        {'kind': 'stocks', 'rows': 8},
        {'kind': 'dispersion', 'dates': 4},
        {'kind': 'risk_matrix'},
        {'kind': 'mot_grid'},
    ]
    for spec in datasets:
        first = build_dataset(spec, seed=97)
        second = build_dataset(spec, seed=97)
        assert compare(first, second)[0]


def test_comparison_rejects_wrong_values_and_labels():
    target = pd.Series([1.0, 2.0], index=['A', 'B'], name='ret')
    assert not compare(pd.Series([1.0, 3.0], index=['A', 'B'], name='ret'), target)[0]
    assert not compare(pd.Series([1.0, 2.0], index=['B', 'A'], name='ret'), target)[0]
    assert not compare(pd.Series([1.0, 2.0], index=['A', 'B']), target)[0]


def test_packs_contain_unique_ids():
    from datagym.paths import PACKS

    ids = []
    for pack in PACKS.glob('*.json'):
        entries = json.loads(pack.read_text(encoding='utf-8'))
        ids.extend(entry['id'] for entry in entries)
    assert len(ids) >= 150
    assert len(ids) == len(set(ids))
