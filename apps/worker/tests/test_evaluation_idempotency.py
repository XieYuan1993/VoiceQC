from contextlib import contextmanager

import worker.tasks.evaluate as evaluate_module


def test_duplicate_evaluation_task_is_ignored_when_recording_lock_is_held(monkeypatch) -> None:
    calls: list[str] = []

    @contextmanager
    def lock_not_acquired(_recording_id: str):
        yield False

    monkeypatch.setattr(evaluate_module, "_evaluation_recording_lock", lock_not_acquired)
    monkeypatch.setattr(
        evaluate_module,
        "_evaluate_locked",
        lambda _task, recording_id: calls.append(recording_id),
    )

    evaluate_module.evaluate.run("recording-1")

    assert calls == []


def test_evaluation_task_runs_after_acquiring_recording_lock(monkeypatch) -> None:
    calls: list[str] = []

    @contextmanager
    def lock_acquired(_recording_id: str):
        yield True

    monkeypatch.setattr(evaluate_module, "_evaluation_recording_lock", lock_acquired)
    monkeypatch.setattr(
        evaluate_module,
        "_evaluate_locked",
        lambda _task, recording_id: calls.append(recording_id),
    )

    evaluate_module.evaluate.run("recording-1")

    assert calls == ["recording-1"]
