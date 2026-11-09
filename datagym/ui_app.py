"""Local HTTP API and session state for the VS Code trainer."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import threading
import time
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from .datasets import build_dataset
from .executor import evaluate, check_syntax
from .library import Exercise, Library
from .paths import ROOT, SOLUTION, ensure_dirs
from .serialization import serialize

STATIC = ROOT / 'static'


def _solution_template(exercise: Exercise) -> str:
    value_type = 'pd.DataFrame' if exercise.variable == 'df' else 'np.ndarray'
    return (
        'import numpy as np\n'
        'import pandas as pd\n'
        'from datagym.datasets import build_dataset\n\n'
        f'{exercise.variable}: {value_type} = '
        f'build_dataset({exercise.dataset!r}, {exercise.seed})\n\n'
        f'# {exercise.title}\n'
        f'# {exercise.instructions}\n'
        'result = '
    )


def _exercise_previews(exercise: Exercise) -> tuple[dict, dict]:
    value = build_dataset(exercise.dataset, exercise.seed)
    scope = {'df': value.copy(), 'arr': value.copy(), 'pd': pd, 'np': np}
    exec('result = ' + exercise.reference, scope)
    return serialize(value), serialize(scope['result'])


class Trainer:
    """One exercise and native solution.py file, for one trusted local user."""

    def __init__(self):
        ensure_dirs()
        self.db = Library()
        self.db.import_packs()
        self.lock = threading.RLock()
        self.exercise: Exercise | None = None
        self.input_preview: dict | None = None
        self.target_preview: dict | None = None
        self.live_preview: dict | None = None
        self.status = 'idle'
        self.message = 'Write Python in solution.py.'
        self.started_at = time.monotonic()
        self.finished_at: float | None = None
        self.previews = 0
        self.hints = 0
        self.revealed = False
        self.solved = False
        self.last_source = ''
        self.initial_source = ''
        self.last_mtime = 0
        self.render_version = 0
        self.job_counter = 0
        self.active_job = 0
        self.pending_job = None
        self.worker_active = False
        self.category_filter = 'All'
        self.difficulty_filter = 'All'
        self.new_exercise()

    def new_exercise(self, category: str = 'All', difficulty: str = 'All') -> dict:
        with self.lock:
            if self.exercise is not None:
                self.db.record(self.exercise, self.solved, self.elapsed(),
                               self.previews, self.hints, self.revealed)
            self.exercise = self.db.pick(category, difficulty)
            exercise = self.exercise
            self.input_preview, self.target_preview = _exercise_previews(exercise)
            self.live_preview = None
            self.status = 'idle'
            self.message = 'Write your solution and assign the answer to result.'
            self.started_at = time.monotonic()
            self.finished_at = None
            self.solved = False
            self.revealed = False
            self.previews = 0
            self.hints = 0
            self.category_filter = category
            self.difficulty_filter = difficulty
            self.render_version += 1
            self.job_counter += 1
            self.active_job = self.job_counter
            self.pending_job = None
            template = _solution_template(exercise)
            self.initial_source = template
            SOLUTION.write_text(template, encoding='utf-8')
            self.last_source = template
            self.last_mtime = SOLUTION.stat().st_mtime_ns
            return self.snapshot()

    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0., end - self.started_at)

    def check_file(self):
        """Called on GET /api/state; never blocks on Python worker execution."""
        with self.lock:
            try:
                mtime = SOLUTION.stat().st_mtime_ns
                if mtime == self.last_mtime:
                    return
                source = SOLUTION.read_text(encoding='utf-8')
            except OSError:
                self.status = 'error'
                self.message = 'solution.py was removed. Click New exercise to recreate it.'
                return
            self.last_mtime = mtime
            if source == self.last_source:
                return
            self.last_source = source
            if self.exercise is None:
                return
            self.job_counter += 1
            job = self.job_counter
            self.active_job = job
            valid, msg = check_syntax(source)
            if not valid:
                self.pending_job = None
                self.status = 'incomplete'
                self.message = msg
                return
            self.status = 'running'
            self.message = 'Evaluating saved code…'
            # Discard stale autosaves while the worker is busy.
            self.pending_job = (job, self.exercise, source)
            if not self.worker_active:
                self.worker_active = True
                threading.Thread(target=self._worker_loop, daemon=True).start()

    def _worker_loop(self):
        while True:
            with self.lock:
                pending = self.pending_job
                self.pending_job = None
                if pending is None:
                    self.worker_active = False
                    return
            job, exercise, source = pending
            result = evaluate(exercise, source)
            with self.lock:
                if job != self.active_job or exercise is not self.exercise:
                    continue
                self.previews += 1
                self.status = result['status']
                self.message = result.get('message', '')
                if 'preview' in result:
                    self.live_preview = result['preview']
                    self.render_version += 1
                if result['status'] == 'correct':
                    if self.solved:
                        self.message = 'Correct. This exercise was already credited.'
                    elif self.revealed:
                        self.message = 'Output matches, but this exercise was revealed (no independent credit).'
                    else:
                        self.solved = True
                        self.finished_at = time.monotonic()
                        self.message = 'Correct. ' + self.message

                    self.pending_job = None

    def hint(self) -> dict:
        with self.lock:
            self.hints += 1
            return {'hint': self.exercise.hint if self.exercise else ''}

    def reveal(self) -> dict:
        with self.lock:
            if not self.solved:
                self.revealed = True
            
            if not self.exercise:
                return {'reference': '', 'steps': []}

            return {
                'reference': f'result = {self.exercise.reference}',
                'steps': self.exercise.explanation or [
                    {
                        'code': self.exercise.reference,
                        'meaning': self.exercise.hint
                    }
                ]
            }

    def reset_code(self) -> dict:
        with self.lock:
            self.job_counter += 1
            self.active_job = self.job_counter
            self.pending_job = None
            SOLUTION.write_text(self.initial_source, encoding='utf-8')
            self.last_source = self.initial_source
            self.last_mtime = SOLUTION.stat().st_mtime_ns
            self.live_preview = None
            self.status = 'idle'
            self.message = (
                'Code reset. Your completed solve remains credited.'
                if self.solved
                else 'Code reset. Begin with result = …'
            )
            self.render_version += 1
            return {'ok': True}

    def snapshot(self) -> dict:
        with self.lock:
            ex = self.exercise
            return {
                'exercise': {
                    'id': ex.id, 'title': ex.title,
                    'instructions': ex.instructions, 'category': ex.category,
                    'difficulty': ex.difficulty, 'seed': ex.seed,
                    'variable': ex.variable,
                } if ex else None,
                'input': self.input_preview, 'target': self.target_preview,
                'live': self.live_preview,
                'status': self.status, 'message': self.message,
                'solved': self.solved, 'revealed': self.revealed,
                'previews': self.previews, 'hints_used': self.hints,
                'elapsed': round(self.elapsed(), 1), 'time_goal': 120,
                'render_version': self.render_version,
                'solution_path': str(SOLUTION), 'stats': self.db.stats(),
                'categories': ['All', *sorted(self.db.counts())],
                'template_count': self.db.total_templates(),
                'filters': {'category': self.category_filter,
                            'difficulty': self.difficulty_filter},
            }


def make_handler(trainer: Trainer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args):
            if not self.path.startswith('/api/state'):
                super().log_message(fmt, *args)

        def json_response(self, obj, status=200):
            content = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == '/api/state':
                trainer.check_file()
                return self.json_response(trainer.snapshot())
            if path == '/api/health':
                return self.json_response({'ok': True, 'service': 'DataGym'})
            filemap = {
                '/': STATIC / 'index.html',
                '/static/app.js': STATIC / 'app.js',
                '/static/style.css': STATIC / 'style.css',
            }
            filepath = filemap.get(path)
            if not filepath or not filepath.is_file():
                return self.json_response({'error': 'Not found'}, 404)
            data = filepath.read_bytes()
            mime = mimetypes.guess_type(str(filepath))[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', mime + ('; charset=utf-8' if mime.startswith('text/') or mime == 'application/javascript' else ''))
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            origin = self.headers.get('Origin', '')
            if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
                return self.json_response({'error': 'Unsupported origin'}, 403)
            size = int(self.headers.get('Content-Length', '0'))
            if size > 16000:
                return self.json_response({'error': 'Request too large'}, 413)
            try:
                body = json.loads(self.rfile.read(size) or b'{}')
            except (ValueError, UnicodeDecodeError):
                return self.json_response({'error': 'Invalid JSON'}, 400)
            path = urlparse(self.path).path
            try:
                if path == '/api/new':
                    category = body.get('category', trainer.category_filter)
                    difficulty = str(body.get('difficulty', trainer.difficulty_filter))
                    if not isinstance(category, str) or difficulty not in ('All', '1', '2', '3', '4', '5'):
                        raise ValueError('Invalid filters')
                    return self.json_response(trainer.new_exercise(category, difficulty))
                if path == '/api/hint':
                    return self.json_response(trainer.hint())
                if path == '/api/reveal':
                    return self.json_response(trainer.reveal())
                if path == '/api/reset':
                    return self.json_response(trainer.reset_code())
                if path == '/api/import':
                    n = trainer.db.import_packs()
                    return self.json_response({'imported': n})
                return self.json_response({'error': 'Not found'}, 404)
            except (ValueError, KeyError) as exc:
                return self.json_response({'error': str(exc)}, 400)

    return Handler


def run(host: str = '127.0.0.1', port: int = 8765):
    trainer = Trainer()
    server = ThreadingHTTPServer((host, port), make_handler(trainer))
    print('\nDataGym 0.1 — Visual Python Data Trainer')
    print(f'Local API: http://{host}:{port} (normally launched by the VS Code extension)')
    print(f'Edit with VS Code: {SOLUTION}')
    print(f'Exercise library: {ROOT / "exercise_packs"}')
    print('Press Ctrl+C in this terminal to stop.\n')
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print('\nStopping DataGym…')
    finally:
        server.server_close()

