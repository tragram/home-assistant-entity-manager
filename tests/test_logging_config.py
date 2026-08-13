import logging

from logging_config import configure_logging


def test_configure_logging_honors_level_without_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    monkeypatch.delenv("LOG_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

    assert configure_logging() == logging.WARNING
    assert logging.getLogger().level == logging.WARNING
    assert not (tmp_path / "web_ui.log").exists()


def test_configure_logging_supports_explicit_file(monkeypatch, tmp_path):
    path = tmp_path / "logs" / "app.log"
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("LOG_FILE", str(path))

    assert configure_logging() == logging.DEBUG
    logging.getLogger("test").warning("written")
    assert "written" in path.read_text(encoding="utf-8")
