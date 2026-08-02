"""Regression tests for the behaviours fixed after the first code review.

Each test here maps to a way the tool used to lose data, crash, or shut Steam
down when it had no business doing so.
"""

import os
import subprocess
import sys
from collections import namedtuple

import pytest
import vdf

import steam_launchopts as m

GAME = "553850"
GAME_NAME = "HELLDIVERS™ 2"


@pytest.fixture(autouse=True)
def isolated_steam_root(tmp_path, monkeypatch):
    """Keep every test off the real Steam install on the developer's machine."""
    root = tmp_path / "steam"
    (root / "steamapps").mkdir(parents=True)
    monkeypatch.setattr(m, "STEAM_ROOT", str(root))
    return root


@pytest.fixture
def config(tmp_path):
    """A localconfig.vdf with one game that has launch options set."""
    path = tmp_path / "localconfig.vdf"
    write_config(path, {GAME: {"LaunchOptions": "OLD=1 %command%"}})
    return path


def write_config(path, apps):
    data = {"UserLocalConfigStore": {"Software": {"Valve": {"Steam": {"apps": apps}}}}}
    with open(path, "w", encoding="utf-8") as f:
        vdf.dump(data, f, pretty=True)


def read_apps(path):
    with open(path, encoding="utf-8") as f:
        return m.get_apps(vdf.load(f))


Result = namedtuple("Result", "status message")


def run_cli(monkeypatch, *argv):
    """Invoke main() as the console script would.

    sys.exit("message") carries its text in SystemExit.code rather than printing
    it, so the message is returned alongside the status instead of via capsys.
    """
    monkeypatch.setattr(sys, "argv", ["steam-launchopts", *argv])
    try:
        m.main()
    except SystemExit as e:
        if e.code is None or isinstance(e.code, int):
            return Result(e.code or 0, "")
        return Result(1, str(e.code))
    return Result(0, "")


@pytest.fixture
def steam_running(monkeypatch):
    """Pretend Steam is running and record whether a shutdown was attempted."""
    calls = []
    monkeypatch.setattr(m, "steam_is_running", lambda: True)
    monkeypatch.setattr(m, "shutdown_steam", lambda *a, **kw: calls.append("shutdown"))
    return calls


# --- reading ---------------------------------------------------------------


def test_empty_launch_options_reads_as_unset():
    """Steam writes "LaunchOptions" "" when the field is cleared in its UI."""
    apps = {GAME: {"LaunchOptions": ""}}
    assert m.launch_options(apps, GAME) is None


def test_non_dict_entry_does_not_crash():
    assert m.launch_options({GAME: "unexpected string"}, GAME) is None


def test_get_and_list_agree_on_empty_options(tmp_path, monkeypatch, capsys):
    path = tmp_path / "localconfig.vdf"
    write_config(path, {GAME: {"LaunchOptions": ""}})

    run_cli(monkeypatch, "--file", str(path), "get", GAME)
    assert "(no launch options set)" in capsys.readouterr().out

    run_cli(monkeypatch, "--file", str(path), "list")
    assert "(no games have launch options set)" in capsys.readouterr().out


def test_reads_utf8_regardless_of_locale(tmp_path):
    """Game names are not ASCII; an ASCII locale must not break a read-only list."""
    path = tmp_path / "localconfig.vdf"
    write_config(path, {GAME: {"LaunchOptions": f"# {GAME_NAME} %command%"}})

    env = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, steam_launchopts;"
            f" sys.argv = ['x', '--file', {str(path)!r}, 'list'];"
            " steam_launchopts.main()",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert GAME in result.stdout


# --- library discovery -----------------------------------------------------


def test_legacy_libraryfolders_string_entries(isolated_steam_root, tmp_path):
    """Older Steam releases stored a bare path string instead of {"path": ...}."""
    other = tmp_path / "library2"
    (other / "steamapps").mkdir(parents=True)
    libraryfolders = {"libraryfolders": {"0": str(isolated_steam_root), "1": str(other)}}
    with open(isolated_steam_root / "steamapps" / "libraryfolders.vdf", "w") as f:
        vdf.dump(libraryfolders, f, pretty=True)

    assert str(other) in m.library_paths()


def test_libraryfolders_dict_entries(isolated_steam_root, tmp_path):
    other = tmp_path / "library2"
    (other / "steamapps").mkdir(parents=True)
    libraryfolders = {"libraryfolders": {"0": {"path": str(other)}}}
    with open(isolated_steam_root / "steamapps" / "libraryfolders.vdf", "w") as f:
        vdf.dump(libraryfolders, f, pretty=True)

    paths = m.library_paths()
    assert str(other) in paths
    assert paths.count(str(isolated_steam_root)) == 1  # no duplicate globbing


def test_app_names_read_utf8_manifests(isolated_steam_root):
    manifest = {"AppState": {"appid": GAME, "name": GAME_NAME}}
    with open(
        isolated_steam_root / "steamapps" / f"appmanifest_{GAME}.acf", "w", encoding="utf-8"
    ) as f:
        vdf.dump(manifest, f, pretty=True)

    assert m.load_app_names()[GAME] == GAME_NAME


# --- appid validation ------------------------------------------------------


def test_rejects_non_numeric_appid(config, monkeypatch, capsys):
    assert run_cli(monkeypatch, "--file", str(config), "set", "totally-bogus", "X=1").status == 2
    assert "must be a number" in capsys.readouterr().err
    assert "totally-bogus" not in read_apps(config)


def test_rejects_unknown_appid_without_force(config, monkeypatch):
    result = run_cli(monkeypatch, "--file", str(config), "set", "999999999", "X=1")
    assert result.status == 1
    assert "--force" in result.message
    assert "999999999" not in read_apps(config)


def test_force_accepts_unknown_appid(config, monkeypatch):
    argv = ["--skip-steam-check", "--file", str(config), "set", "999999999", "X=1", "--force"]
    assert run_cli(monkeypatch, *argv).status == 0
    assert read_apps(config)["999999999"]["LaunchOptions"] == "X=1"


# --- writing ---------------------------------------------------------------


def test_set_and_clear_roundtrip(config, monkeypatch):
    run_cli(monkeypatch, "--skip-steam-check", "--file", str(config), "set", GAME, "NEW=1")
    assert read_apps(config)[GAME]["LaunchOptions"] == "NEW=1"

    run_cli(monkeypatch, "--skip-steam-check", "--file", str(config), "clear", GAME)
    assert "LaunchOptions" not in read_apps(config)[GAME]


def test_set_over_non_dict_entry(tmp_path, monkeypatch):
    path = tmp_path / "localconfig.vdf"
    write_config(path, {GAME: "unexpected string"})
    argv = ["--skip-steam-check", "--file", str(path), "set", GAME, "X=1"]
    assert run_cli(monkeypatch, *argv).status == 0
    assert read_apps(path)[GAME]["LaunchOptions"] == "X=1"


def test_failed_dump_leaves_original_intact(config, monkeypatch):
    before = config.read_bytes()

    def explode(data, f, **kw):
        f.write("partial")
        raise RuntimeError("dump failed")

    monkeypatch.setattr(m.vdf, "dump", explode)
    with pytest.raises(RuntimeError):
        m.write(str(config), {})

    assert config.read_bytes() == before


# --- Steam shutdown ordering ----------------------------------------------


def test_bad_file_does_not_shut_steam_down(tmp_path, monkeypatch, steam_running):
    missing = tmp_path / "typo.vdf"
    result = run_cli(monkeypatch, "--file", str(missing), "set", GAME, "X=1")
    assert result.status == 1
    assert "cannot read" in result.message
    assert steam_running == []


def test_noop_clear_does_not_shut_steam_down(tmp_path, monkeypatch, steam_running):
    path = tmp_path / "localconfig.vdf"
    write_config(path, {GAME: {}})
    assert run_cli(monkeypatch, "--file", str(path), "clear", GAME).status == 0
    assert steam_running == []


def test_unchanged_options_do_not_shut_steam_down(config, monkeypatch, steam_running):
    assert run_cli(monkeypatch, "--file", str(config), "set", GAME, "OLD=1 %command%").status == 0
    assert steam_running == []


def test_unknown_appid_does_not_shut_steam_down(config, monkeypatch, steam_running):
    assert run_cli(monkeypatch, "--file", str(config), "set", "999999999", "X=1").status == 1
    assert steam_running == []


def test_real_change_does_shut_steam_down(config, monkeypatch, steam_running):
    assert run_cli(monkeypatch, "--file", str(config), "set", GAME, "NEW=1").status == 0
    assert steam_running == ["shutdown"]


def test_config_is_reread_after_shutdown(config, monkeypatch):
    """Steam rewrites localconfig.vdf as it exits; the pre-shutdown read is stale."""

    def steam_rewrites_config_on_exit(*a, **kw):
        write_config(
            config,
            {
                GAME: {"LaunchOptions": "OLD=1 %command%"},
                "999": {"LaunchOptions": "WRITTEN_BY_STEAM"},
            },
        )

    monkeypatch.setattr(m, "steam_is_running", lambda: True)
    monkeypatch.setattr(m, "shutdown_steam", steam_rewrites_config_on_exit)

    assert run_cli(monkeypatch, "--file", str(config), "set", GAME, "NEW=1").status == 0

    apps = read_apps(config)
    assert apps[GAME]["LaunchOptions"] == "NEW=1"
    assert apps["999"]["LaunchOptions"] == "WRITTEN_BY_STEAM"  # not clobbered


def test_non_tty_stdin_exits_instead_of_raising(monkeypatch):
    monkeypatch.setattr(m.sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit) as excinfo:
        m.shutdown_steam()
    assert "not a terminal" in str(excinfo.value)


def test_missing_steam_binary_is_reported(monkeypatch):
    monkeypatch.setattr(m.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    def no_steam(cmd, **kw):
        raise FileNotFoundError(2, "No such file or directory", "steam")

    monkeypatch.setattr(m.subprocess, "run", no_steam)
    with pytest.raises(SystemExit) as excinfo:
        m.shutdown_steam()
    assert "no `steam` binary" in str(excinfo.value)


def test_failed_shutdown_command_is_reported(monkeypatch):
    monkeypatch.setattr(m.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))
    with pytest.raises(SystemExit) as excinfo:
        m.shutdown_steam()
    assert "failed with exit status 1" in str(excinfo.value)


def test_declining_shutdown_aborts(monkeypatch):
    monkeypatch.setattr(m.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    with pytest.raises(SystemExit) as excinfo:
        m.shutdown_steam()
    assert "aborted" in str(excinfo.value)


def test_missing_pgrep_is_reported(monkeypatch):
    def no_pgrep(cmd, **kw):
        raise FileNotFoundError(2, "No such file or directory", "pgrep")

    monkeypatch.setattr(m.subprocess, "run", no_pgrep)
    with pytest.raises(SystemExit) as excinfo:
        m.steam_is_running()
    assert "--skip-steam-check" in str(excinfo.value)


# --- config discovery ------------------------------------------------------


def test_multiple_accounts_error_names_the_flag(isolated_steam_root):
    for account in ("111", "222"):
        config_dir = isolated_steam_root / "userdata" / account / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "localconfig.vdf").touch()

    with pytest.raises(SystemExit) as excinfo:
        m.find_localconfig()
    assert "--file" in str(excinfo.value)
