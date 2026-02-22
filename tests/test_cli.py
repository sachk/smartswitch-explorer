from __future__ import annotations

from gui import main as cli_main


def test_main_prints_version(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_main, "get_app_version", lambda: "9.9.9")
    code = cli_main.main(["--version"])
    assert code == 0
    assert capsys.readouterr().out.strip() == "9.9.9"


def test_main_runs_smoke_mode(monkeypatch) -> None:
    called: dict[str, list[str]] = {}

    def fake_smoke(argv: list[str] | None = None) -> int:
        called["argv"] = [] if argv is None else list(argv)
        return 0

    monkeypatch.setattr(cli_main, "_run_smoke_test", fake_smoke)
    monkeypatch.setattr(cli_main, "_run_app", lambda *_: 7)
    code = cli_main.main(["--smoke-test", "--style", "Fusion"])
    assert code == 0
    assert called["argv"][1:] == ["--style", "Fusion"]


def test_main_runs_gui_app(monkeypatch) -> None:
    called: dict[str, list[str]] = {}

    def fake_run(argv: list[str] | None = None) -> int:
        called["argv"] = [] if argv is None else list(argv)
        return 3

    monkeypatch.setattr(cli_main, "_run_app", fake_run)
    code = cli_main.main(["--platform", "minimal"])
    assert code == 3
    assert called["argv"][1:] == ["--platform", "minimal"]
