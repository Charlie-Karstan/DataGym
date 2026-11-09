"""SQLite-backed editable library, with source packs imported from JSON."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import random

import numpy as np
import pandas as pd
import sqlite3
import time
from pathlib import Path

from .datasets import build_dataset, variable_name
from .paths import PACKS, DATABASE, ensure_dirs


@dataclass
class Exercise:
    id: str
    title: str
    instructions: str
    category: str
    difficulty: int
    hint: str
    reference: str
    dataset: dict
    seed: int
    variable: str
    explanation: list[dict] = field(default_factory=list)

    def as_worker_payload(self) -> dict:
        return {'dataset': self.dataset, 'seed': self.seed, 'reference': self.reference}


class Library:
    def __init__(self, path: Path = DATABASE):
        ensure_dirs()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY, category TEXT NOT NULL, difficulty INTEGER NOT NULL,
                payload TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, template_id TEXT NOT NULL,
                seed INTEGER NOT NULL, solved INTEGER NOT NULL, elapsed REAL NOT NULL,
                previews INTEGER NOT NULL, hints INTEGER NOT NULL, revealed INTEGER NOT NULL,
                created_at REAL NOT NULL
            )''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def import_packs(self, directory: Path = PACKS) -> int:
        count = 0
        with self.connect() as db:
            for pack in sorted(Path(directory).glob('*.json')):
                items = json.loads(pack.read_text(encoding='utf-8'))
                if not isinstance(items, list):
                    raise ValueError(f'Pack must be a JSON array: {pack}')
                for entry in items:
                    validate_template(entry)
                    db.execute('''INSERT INTO templates(id,category,difficulty,payload,enabled)
                        VALUES(?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET
                        category=excluded.category, difficulty=excluded.difficulty,
                        payload=excluded.payload''', (
                        entry['id'], entry['category'], entry['difficulty'],
                        json.dumps(entry, ensure_ascii=False),
                    ))
                    count += 1
        return count

    def counts(self):
        with self.connect() as db:
            return dict(db.execute('SELECT category, COUNT(*) FROM templates WHERE enabled=1 GROUP BY category'))

    def total_templates(self) -> int:
        with self.connect() as db:
            return db.execute('SELECT COUNT(*) FROM templates WHERE enabled=1').fetchone()[0]

    def pick(self, category: str = 'All', difficulty: str = 'All') -> Exercise:
        entry = self._choose_template(category, difficulty)
        return _prepare_exercise(entry)

    def _choose_template(self, category: str, difficulty: str) -> dict:
        query = 'SELECT id,payload FROM templates WHERE enabled=1'
        params = []
        if category != 'All':
            query += ' AND category=?'
            params.append(category)
        if difficulty != 'All':
            query += ' AND difficulty=?'
            params.append(int(difficulty))

        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
            if not rows:
                raise ValueError('No exercises match these filters.')
            recent = {row[0] for row in db.execute(
                'SELECT template_id FROM attempts ORDER BY id DESC LIMIT 10'
            )}
            attempts = dict(db.execute(
                'SELECT template_id, COUNT(*) FROM attempts GROUP BY template_id'
            ))
            solved = dict(db.execute(
                'SELECT template_id, SUM(solved) FROM attempts GROUP BY template_id'
            ))

        candidates = [(id_, json.loads(payload)) for id_, payload in rows]
        unseen = [(id_, entry) for id_, entry in candidates if id_ not in recent]
        if unseen:
            candidates = unseen

        weights = [
            (1.5 if solved.get(id_, 0) == 0 else 1.0)
            / (1 + 0.25 * attempts.get(id_, 0))
            for id_, _ in candidates
        ]
        return random.choices(candidates, weights=weights, k=1)[0][1]

    def record(self, exercise: Exercise, solved: bool, elapsed: float,
               previews: int, hints: int, revealed: bool) -> None:
        with self.connect() as db:
            db.execute('''INSERT INTO attempts
                (template_id, seed, solved, elapsed, previews, hints, revealed, created_at)
                VALUES(?,?,?,?,?,?,?,?)''',
                (exercise.id, exercise.seed, int(solved), elapsed, previews,
                 hints, int(revealed), time.time()))

    def stats(self) -> dict:
        with self.connect() as db:
            row = db.execute('''SELECT COUNT(*), COALESCE(SUM(solved),0),
                COUNT(DISTINCT CASE WHEN solved=1 THEN template_id END),
                COALESCE(AVG(CASE WHEN solved=1 THEN elapsed END),0)
                FROM attempts''').fetchone()
            recent = db.execute('SELECT solved FROM attempts ORDER BY id DESC LIMIT 100').fetchall()
            by_category = db.execute('''SELECT t.category, COUNT(*), SUM(a.solved)
                FROM attempts a LEFT JOIN templates t ON t.id=a.template_id
                GROUP BY t.category ORDER BY t.category''').fetchall()
        streak = 0
        for (solved,) in recent:
            if not solved:
                break
            streak += 1
        return {'attempted': row[0], 'solved': row[1], 'unique': row[2],
                'average_seconds': row[3], 'streak': streak,
                'by_category': by_category}



def _prepare_exercise(entry: dict) -> Exercise:
    seed = random.randrange(1, 2**31)
    rng = random.Random(seed)
    params = {
        name: rng.choice(definition['choices'])
        for name, definition in entry.get('parameters', {}).items()
    }
    explanation = [
        {
            'code': part['code'].format_map(params),
            'meaning': part['meaning'].format_map(params),
        }
        for part in entry.get('explanation', [])
    ]
    reference = entry['reference'].format_map(params)
    dataset = build_dataset(entry['dataset'], seed)
    scope = {variable_name(entry['dataset']): dataset, 'pd': pd, 'np': np}
    exec('result = ' + reference, scope)

    return Exercise(
        id=entry['id'],
        title=entry['title'],
        instructions=entry['instructions'].format_map(params),
        category=entry['category'],
        difficulty=entry['difficulty'],
        hint=entry.get('hint', '').format_map(params),
        reference=reference,
        dataset=entry['dataset'],
        seed=seed,
        variable=variable_name(entry['dataset']),
        explanation=explanation,
    )


def validate_template(item: dict) -> None:
    required = ('id', 'title', 'instructions', 'category', 'difficulty', 'reference', 'dataset')
    for field in required:
        if field not in item:
            raise ValueError(f'Missing {field!r} in exercise: {item.get("id", "unknown")}')
    if not 1 <= int(item['difficulty']) <= 5:
        raise ValueError('Difficulty must be between 1 and 5')
    if not isinstance(item['dataset'], dict) or 'kind' not in item['dataset']:
        raise ValueError('dataset needs a kind')
    for definition in item.get('parameters', {}).values():
        if not isinstance(definition.get('choices'), list) or not definition['choices']:
            raise ValueError('Each parameter needs nonempty choices array')
