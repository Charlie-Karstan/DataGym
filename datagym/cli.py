"""Run: python -m datagym.cli [import|list|stats|validate]"""
from __future__ import annotations
import argparse
import json
import random

from .library import Library
from .datasets import build_dataset, variable_name


def main() -> None:
    parser = argparse.ArgumentParser(description='DataGym exercise library manager')
    parser.add_argument('command', choices=['import', 'list', 'stats', 'validate'])
    args = parser.parse_args()
    lib = Library()
    if args.command == 'import':
        print(f'Imported / updated {lib.import_packs()} exercise templates.')
    elif args.command == 'list':
        with lib.connect() as db:
            for id_, category, difficulty in db.execute(
                    'SELECT id, category, difficulty FROM templates ORDER BY category,id'):
                print(f'{category:16} L{difficulty}  {id_}')
    elif args.command == 'stats':
        print(json.dumps(lib.stats(), indent=2))
    elif args.command == 'validate':
        lib.import_packs()
        with lib.connect() as db:
            templates = [json.loads(r[0]) for r in db.execute('SELECT payload FROM templates')]
        import numpy as np
        import pandas as pd
        checked = 0
        for item in templates:
            for seed in (17, 37, 112):
                rnd = random.Random(seed)
                params = {k: rnd.choice(v['choices']) for k, v in item.get('parameters', {}).items()}
                code = item['reference'].format_map(params)
                obj = build_dataset(item['dataset'], seed)
                scope = {variable_name(item['dataset']): obj, 'pd': pd, 'np': np}
                exec('result = ' + code, scope)
                checked += 1
        print(f'Validated {checked} concrete target calculations ({len(templates)} templates × 3 seeds).')


if __name__ == '__main__':
    main()
