
import time

from datagym.library import Library
import datagym.ui_app as app


def make_trainer(tmp_path, monkeypatch):
    solution = tmp_path / 'solution.py'
    library = Library(tmp_path / 'progress.sqlite3')

    monkeypatch.setattr(app, 'SOLUTION', solution)
    monkeypatch.setattr(app, 'Library', lambda: library)

    return app.Trainer(), solution, library


def test_previous_restores_exercise_and_code(tmp_path, monkeypatch):
    trainer, solution, library = make_trainer(tmp_path, monkeypatch)

    first = (trainer.exercise.id, trainer.exercise.seed)
    assert not trainer.snapshot()['can_previous']

    solution.write_text('result = invalid[', encoding='utf-8')
    trainer.check_file()
    trainer.new_exercise()

    second = (trainer.exercise.id, trainer.exercise.seed)
    assert trainer.snapshot()['can_previous']

    trainer.previous_exercise()

    assert (trainer.exercise.id, trainer.exercise.seed) == first
    assert solution.read_text(encoding='utf-8') == 'result = invalid['

    trainer.new_exercise()

    assert (trainer.exercise.id, trainer.exercise.seed) == second
    assert library.stats()['attempted'] == 2


def test_navigation_preserves_solved_credit(tmp_path, monkeypatch):
    trainer, _, library = make_trainer(tmp_path, monkeypatch)

    trainer.solved = True
    trainer.finished_at = time.monotonic()

    trainer.new_exercise()
    trainer.previous_exercise()

    assert trainer.solved
    assert not trainer.snapshot()['current_unrecorded']
    assert library.stats()['solved'] == 1

    trainer.new_exercise()

    assert library.stats()['solved'] == 1
