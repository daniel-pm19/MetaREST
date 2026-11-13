from __future__ import annotations

import os

from scripts._env import load_env


def test_load_env_sets_only_missing_variables(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n\nMETAREST_A=one\nexport METAREST_B='two words'\nMETAREST_C=\"x=y\"\nMETAREST_D=keep\nnot a pair\n",
        encoding="utf-8",
    )
    for key in ("METAREST_A", "METAREST_B", "METAREST_C"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("METAREST_D", "from-shell")

    assert load_env(env) == ["METAREST_A", "METAREST_B", "METAREST_C"]
    assert (os.environ["METAREST_A"], os.environ["METAREST_B"], os.environ["METAREST_C"]) == ("one", "two words", "x=y")
    assert os.environ["METAREST_D"] == "from-shell"
    for key in ("METAREST_A", "METAREST_B", "METAREST_C"):
        monkeypatch.delenv(key)


def test_missing_env_file_is_fine(tmp_path):
    assert load_env(tmp_path / "nope.env") == []
