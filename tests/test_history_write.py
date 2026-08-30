"""history.json es la única fuente de verdad, y se escribe atómicamente.

De él salen todas las páginas, los dos feeds y la ventana de
deduplicación entera. Nada más en disco puede reconstruirlo, así que una
escritura interrumpida a mitad, por un tick de cron cancelado o una
máquina que se apaga, no puede dejar medio documento.
"""

import json

import pytest

from scripts import atomic_io, generate

HISTORY = {"entries": [{"speciesCode": "aaa", "date": "2026-01-01"}]}


def test_history_round_trips(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    monkeypatch.setattr(generate, "HISTORY_PATH", path)
    generate.save_history(HISTORY)
    assert json.loads(path.read_text(encoding="utf-8")) == HISTORY


def test_an_unchanged_history_is_not_rewritten(tmp_path, monkeypatch):
    """El commit diario no puede ensuciarse con un fichero que no cambió.

    Cuenta los ``os.replace`` en los dos sentidos: sin el cambio, uno
    idéntico tampoco lo llama, así que afirmar solo que no se llama lo
    cumpliría cualquier implementación.
    """
    path = tmp_path / "history.json"
    monkeypatch.setattr(generate, "HISTORY_PATH", path)
    generate.save_history(HISTORY)

    calls = []
    real_replace = atomic_io.os.replace
    monkeypatch.setattr(
        atomic_io.os, "replace",
        lambda *a: (calls.append(a), real_replace(*a))[1],
    )
    generate.save_history(HISTORY)
    assert calls == [], "un historial idéntico no se reescribe"

    generate.save_history({"entries": [{"speciesCode": "bbb"}]})
    assert len(calls) == 1, "uno distinto sí, y por la vía atómica"
    assert json.loads(path.read_text(encoding="utf-8"))["entries"][0][
        "speciesCode"
    ] == "bbb"


def test_a_crash_mid_write_leaves_the_previous_history_intact(
    tmp_path, monkeypatch
):
    path = tmp_path / "history.json"
    monkeypatch.setattr(generate, "HISTORY_PATH", path)
    generate.save_history(HISTORY)

    def _boom(*args):
        raise OSError("disk went away")

    monkeypatch.setattr(atomic_io.os, "replace", _boom)
    with pytest.raises(OSError):
        generate.save_history({"entries": [{"speciesCode": "bbb"}]})

    assert json.loads(path.read_text(encoding="utf-8")) == HISTORY
    assert list(tmp_path.glob("*.tmp")) == []
