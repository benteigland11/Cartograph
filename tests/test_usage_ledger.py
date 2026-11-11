"""Machine-local usage ledger: widget history, search prior pool, ledger command."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from cartograph.usage_ledger import (
    RECORD_ACTIONS,
    forget_events,
    ledger_path,
    list_events,
    prior_for_search,
    project_identity,
    record_usage,
    version_status,
)


def _run(args, env, cwd):
    result = subprocess.run(
        [sys.executable, "-m", "cartograph", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


def _parse(stdout):
    return json.loads(stdout)


@pytest.fixture
def cli_env(fixture_library, tmp_path):
    """Isolated library and ledger path for subprocess CLI calls."""
    library = tmp_path / "Widget_Library"
    shutil.copytree(fixture_library, library)
    env = dict(os.environ)
    env["WIDGET_LIBRARY_PATH"] = str(library)
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg-data")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg-config")
    env["CARTOGRAPH_USAGE_LEDGER"] = str(tmp_path / "usage-ledger.jsonl")
    repo_root = os.path.dirname(os.path.dirname(__file__))
    repo_src = os.path.join(repo_root, "src")
    env["PYTHONPATH"] = os.pathsep.join([
        repo_src,
        repo_root,
        env.get("PYTHONPATH", ""),
    ])
    return env


def _rows(path):
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _search_ns(**overrides):
    values = dict(
        query="ledgerhit",
        domain=None,
        language=None,
        top_k=10,
        registries=None,
        owner=None,
        local_only=False,
        no_ledger=False,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


class _Carto:
    def __init__(self, results, widgets):
        self._results = results
        self.widgets = widgets

    def search(self, query, domain_filter=None, language_filter=None, top_k=10):
        return {"results": list(self._results), "query": query}

    def install(self, widget_id, target_dir, version=None):
        return {
            "status": "success",
            "widget_id": widget_id,
            "version": version or "1.0.0",
            "action": "installed",
            "path": target_dir,
        }

    def inspect(self, widget_id, **kwargs):
        return {
            "id": widget_id,
            "name": widget_id,
            "version": "1.2.0",
            "language": "python",
            "domain": "web",
            "description": "fixture",
            "api": {},
        }


def _isolate_config(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "cartograph.config._config_path",
        lambda: str(tmp_path / "absent-config.toml"),
    )


def _local_widgets():
    return [
        {
            "id": "http-client",
            "name": "HTTP Client",
            "version": "1.2.0",
            "description": "http requests",
            "language": "python",
            "domain": "web",
            "relevance_score": 5,
        },
        {
            "id": "json-parser",
            "name": "JSON Parser",
            "version": "1.0.0",
            "description": "parse json",
            "language": "python",
            "domain": "data",
            "relevance_score": 1,
        },
    ]


def _seed_prior(project_root):
    record_usage(
        "install",
        widget_id="http-client",
        version="1.0.0",
        purpose="ledgerhit fetch pages",
        project_root=project_root,
    )
    record_usage(
        "install",
        widget_id="cg-zeta-python",
        version="0.9.0",
        purpose="ledgerhit remote zeta",
        project_root=project_root,
    )
    record_usage(
        "note",
        widget_id="auth-middleware",
        version="unknown",
        purpose="ledgerhit other",
        project_root=project_root,
    )


def test_ledger_path_is_under_user_data_state(monkeypatch, tmp_path):
    monkeypatch.delenv("CARTOGRAPH_USAGE_LEDGER", raising=False)
    data = tmp_path / "cartograph-data"
    monkeypatch.setattr("cartograph.engine._user_data_dir", lambda: str(data))
    path = ledger_path()
    assert path == os.path.join(str(data), ".state", "usage-ledger.jsonl")
    assert ".claude" not in path
    assert ".codex" not in path


def test_install_records_event_with_purpose(cli_env, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    rc, stdout, stderr = _run(
        ["install", "http-client", "--purpose", "fetch pages for the demo"],
        cli_env,
        str(project),
    )
    assert rc == 0, stderr
    result = _parse(stdout)
    assert result.get("status") == "success"
    assert result["usage_ledger"]["recorded"] is True
    rows = _rows(cli_env["CARTOGRAPH_USAGE_LEDGER"])
    assert len(rows) == 1
    assert rows[0]["widget_id"] == "http-client"
    assert rows[0]["action"] == "install"
    assert rows[0]["purpose"] == "fetch pages for the demo"
    assert rows[0]["version"] == "1.2.0"
    assert rows[0]["owner"] is None
    assert rows[0]["used_at"].endswith("Z")


def test_install_without_purpose_stores_null(cli_env, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    rc, stdout, stderr = _run(["install", "http-client"], cli_env, str(project))
    assert rc == 0, stderr
    rows = _rows(cli_env["CARTOGRAPH_USAGE_LEDGER"])
    assert rows[0]["purpose"] is None


def test_upgrade_is_one_event_and_carries_purpose(cli_env, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    rc, stdout, stderr = _run(
        ["install", "http-client", "--purpose", "keep this reason"],
        cli_env,
        str(project),
    )
    assert rc == 0, stderr
    rc, stdout, stderr = _run(
        ["upgrade", str(project / "cg" / "http-client")],
        cli_env,
        str(project),
    )
    assert rc == 0, stderr
    result = _parse(stdout)
    assert result.get("status") == "success", result
    rows = _rows(cli_env["CARTOGRAPH_USAGE_LEDGER"])
    actions = [row["action"] for row in rows]
    assert actions == ["install", "upgrade"]
    assert rows[1]["purpose"] == "keep this reason"
    assert rows[1]["previous_version"] == "1.2.0"
    assert "uninstall" not in actions


def test_uninstall_appends_and_keeps_earlier_lines(cli_env, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    rc, _, stderr = _run(
        ["install", "http-client", "--purpose", "temporary"],
        cli_env,
        str(project),
    )
    assert rc == 0, stderr
    widget_dir = str(project / "cg" / "http-client")
    rc, stdout, stderr = _run(["uninstall", widget_dir], cli_env, str(project))
    assert rc == 0, stderr
    rows = _rows(cli_env["CARTOGRAPH_USAGE_LEDGER"])
    assert [row["action"] for row in rows] == ["install", "uninstall"]
    assert rows[1]["purpose"] == "temporary"
    assert rows[1]["version"] == "1.2.0"
    assert os.path.isfile(cli_env["CARTOGRAPH_USAGE_LEDGER"])


def test_blueprint_install_does_not_record(monkeypatch, tmp_path, capsys):
    from cartograph.cli import cmd_install

    monkeypatch.setattr("cartograph.cli._carto", lambda: _Carto([], []))
    cmd_install(argparse.Namespace(
        widget_id="bp-demo-python",
        target=str(tmp_path),
        version=None,
        purpose="should not be stored",
    ))
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert "usage_ledger" not in payload
    assert not os.path.isfile(ledger_path())


def test_create_leaves_ledger_absent(cli_env, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    rc, stdout, stderr = _run(
        ["create", "sample-bucket", "--domain", "data", "--language", "python"],
        cli_env,
        str(project),
    )
    assert rc == 0, stderr
    assert not os.path.isfile(cli_env["CARTOGRAPH_USAGE_LEDGER"])


def test_authoring_actions_are_not_in_the_record_allowlist():
    assert RECORD_ACTIONS == frozenset({"install", "upgrade", "uninstall", "note"})
    for action in ("create", "validate", "checkin", "rollback", "delete", "rate"):
        assert action not in RECORD_ACTIONS


def test_search_prior_is_first_and_registry_order_unchanged(monkeypatch, tmp_path, capsys):
    from cartograph.cli import cmd_search

    _isolate_config(monkeypatch, tmp_path)
    _seed_prior(os.getcwd())
    captured = []

    def fake_registries(query, domain, language, top_k, registry_filter=None, owner_filter=None):
        captured.append(query)
        rows = [
            {
                "id": "@ada/cg-zeta-python",
                "name": "Zeta",
                "version": "3.0.0",
                "description": "zeta tool",
                "language": "python",
                "domain": "data",
                "deprecated": True,
                "registry_prefix": "cg",
            },
            {
                "id": "@ada/cg-alpha-python",
                "name": "Alpha",
                "version": "1.0.0",
                "description": "alpha tool",
                "language": "python",
                "domain": "data",
                "registry_prefix": "cg",
            },
        ]
        return rows, {}, ["cg"]

    monkeypatch.setattr("cartograph.cli._search_registries", fake_registries)
    monkeypatch.setattr("cartograph.auth.cached_whoami", lambda: {})
    widgets = _local_widgets()
    monkeypatch.setattr(
        "cartograph.cli._carto",
        lambda: _Carto(widgets, [
            {"id": "http-client", "version": "2.0.0"},
            {"id": "json-parser", "version": "1.0.0"},
        ]),
    )
    cmd_search(_search_ns())
    payload = json.loads(capsys.readouterr().out)
    assert list(payload.keys())[0] == "prior"
    assert captured == ["ledgerhit"]
    registry_ids = [row["id"] for row in payload["registry"]["widgets"]]
    assert registry_ids == ["@ada/cg-zeta-python", "@ada/cg-alpha-python"]
    local_ids = [row["id"] for row in payload["local"]["widgets"]]
    assert local_ids == ["http-client", "json-parser"]
    prior_ids = [row["widget_id"] for row in payload["prior"]["widgets"]]
    assert "http-client" in prior_ids
    assert "cg-zeta-python" in prior_ids
    http = next(row for row in payload["prior"]["widgets"] if row["widget_id"] == "http-client")
    assert http["version_status"] == "older"
    assert http["in_library"] is True
    assert http["library_version"] == "2.0.0"
    zeta = next(row for row in payload["prior"]["widgets"] if row["widget_id"] == "cg-zeta-python")
    assert zeta["deprecated"] is True
    other = next(row for row in payload["prior"]["widgets"] if row["widget_id"] == "auth-middleware")
    assert "deprecated" not in other
    assert other["version_status"] == "unknown"
    assert other["in_library"] is False
    assert payload["prior"]["omitted"] == 0


def test_search_annotates_prior_use_without_reordering_local(monkeypatch, tmp_path, capsys):
    from cartograph.cli import cmd_search

    _isolate_config(monkeypatch, tmp_path)
    record_usage(
        "install",
        widget_id="http-client",
        version="1.0.0",
        purpose="ledgerhit local only",
        project_root=os.getcwd(),
    )
    monkeypatch.setattr(
        "cartograph.cli._search_registries",
        lambda *args, **kwargs: ([], {}, ["cg"]),
    )
    monkeypatch.setattr("cartograph.auth.cached_whoami", lambda: {})
    widgets = _local_widgets()
    monkeypatch.setattr("cartograph.cli._carto", lambda: _Carto(widgets, widgets))
    cmd_search(_search_ns(local_only=True))
    payload = json.loads(capsys.readouterr().out)
    local = payload["local"]["widgets"]
    assert [row["id"] for row in local] == ["http-client", "json-parser"]
    assert local[0]["prior_use"]["purpose"] == "ledgerhit local only"
    assert local[0]["prior_use"]["last_action"] == "install"
    assert "prior_use" not in local[1]


def test_search_empty_ledger_omits_prior_key(monkeypatch, tmp_path, capsys):
    from cartograph.cli import cmd_search

    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setattr("cartograph.cli._search_registries", lambda *args, **kwargs: ([], {}, []))
    monkeypatch.setattr("cartograph.auth.cached_whoami", lambda: {})
    widgets = _local_widgets()
    monkeypatch.setattr("cartograph.cli._carto", lambda: _Carto(widgets, widgets))
    cmd_search(_search_ns(query="parser", local_only=True))
    payload = json.loads(capsys.readouterr().out)
    assert "prior" not in payload
    assert "prior_use" not in payload["local"]["widgets"][0]


def test_search_no_ledger_flag(monkeypatch, tmp_path, capsys):
    from cartograph.cli import cmd_search

    _isolate_config(monkeypatch, tmp_path)
    record_usage(
        "install",
        widget_id="http-client",
        version="1.0.0",
        purpose="ledgerhit hidden",
        project_root=os.getcwd(),
    )
    monkeypatch.setattr("cartograph.cli._search_registries", lambda *args, **kwargs: ([], {}, []))
    monkeypatch.setattr("cartograph.auth.cached_whoami", lambda: {})
    widgets = _local_widgets()
    monkeypatch.setattr("cartograph.cli._carto", lambda: _Carto(widgets, widgets))
    cmd_search(_search_ns(local_only=True, no_ledger=True))
    payload = json.loads(capsys.readouterr().out)
    assert "prior" not in payload
    assert "prior_use" not in payload["local"]["widgets"][0]


def test_config_usage_ledger_false_skips_write_and_prior(monkeypatch, tmp_path, capsys):
    from cartograph.cli import cmd_search
    from cartograph.config import get_value, set_value

    _isolate_config(monkeypatch, tmp_path)
    assert get_value("usage-ledger")[0] is True
    set_value("usage-ledger", "false")
    assert get_value("usage-ledger")[0] is False
    info = record_usage(
        "install",
        widget_id="http-client",
        version="1.0.0",
        purpose="should not land",
        project_root=str(tmp_path),
    )
    assert info is None
    assert not os.path.isfile(ledger_path())

    # A file written earlier must not surface while the switch is off.
    path = ledger_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "widget_id": "http-client",
            "purpose": "ledgerhit stale",
            "action": "install",
            "version": "1.0.0",
            "project_key": "x",
            "project_path": "/tmp/proj",
            "used_at": "2020-01-01T00:00:00Z",
        }) + "\n")
    monkeypatch.setattr("cartograph.cli._search_registries", lambda *args, **kwargs: ([], {}, []))
    monkeypatch.setattr("cartograph.auth.cached_whoami", lambda: {})
    widgets = _local_widgets()
    monkeypatch.setattr("cartograph.cli._carto", lambda: _Carto(widgets, widgets))
    cmd_search(_search_ns(local_only=True))
    payload = json.loads(capsys.readouterr().out)
    assert "prior" not in payload

    listed = list_events()
    assert listed["enabled"] is False
    assert listed["count"] == 1
    forgotten = forget_events(everything=True)
    assert forgotten["removed"] == 1


def test_ledger_list_json(capsys):
    from cartograph.cli import cmd_ledger

    record_usage(
        "note",
        widget_id="http-client",
        version="1.2.0",
        purpose="list me",
        project_root=os.getcwd(),
    )
    cmd_ledger(argparse.Namespace(
        action=None,
        widget_id=None,
        purpose=None,
        version=None,
        target=".",
        limit=50,
        widget_filter=None,
        project=False,
        forget_all=False,
    ))
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert payload["enabled"] is True
    assert payload["count"] == 1
    assert payload["events"][0]["purpose"] == "list me"
    assert payload["path"] == ledger_path()


def test_ledger_note_requires_purpose():
    from cartograph.cli import cmd_ledger

    with pytest.raises(SystemExit) as caught:
        cmd_ledger(argparse.Namespace(
            action="note",
            widget_id="http-client",
            purpose=None,
            version=None,
            target=".",
            limit=50,
            widget_filter=None,
            project=False,
            forget_all=False,
        ))
    assert caught.value.code != 0


def test_ledger_forget_widget_and_all(capsys):
    from cartograph.cli import cmd_ledger

    record_usage("note", widget_id="http-client", version="1.0.0",
                 purpose="one", project_root=os.getcwd())
    record_usage("note", widget_id="json-parser", version="1.0.0",
                 purpose="two", project_root=os.getcwd())
    cmd_ledger(argparse.Namespace(
        action="forget",
        widget_id=None,
        purpose=None,
        version=None,
        target=".",
        limit=50,
        widget_filter="http-client",
        project=False,
        forget_all=False,
    ))
    first = json.loads(capsys.readouterr().out)
    assert first["removed"] == 1
    assert first["kept"] == 1
    cmd_ledger(argparse.Namespace(
        action="forget",
        widget_id=None,
        purpose=None,
        version=None,
        target=".",
        limit=50,
        widget_filter=None,
        project=False,
        forget_all=True,
    ))
    second = json.loads(capsys.readouterr().out)
    assert second["removed"] == 1
    assert second["kept"] == 0


def test_forget_requires_a_selector():
    result = forget_events()
    assert "error" in result


def test_missing_widget_version_status_unknown():
    assert version_status("1.0.0", None) == "unknown"
    assert version_status("unknown", "1.2.0") == "unknown"
    assert version_status("1.2", "1.2.0") == "unknown"


def test_newer_library_version_status_older():
    assert version_status("1.0.0", "2.0.0") == "older"
    assert version_status("2.0.0", "2.0.0") == "current"
    assert version_status("3.0.0", "2.0.0") == "ahead"


def test_deprecated_copied_only_from_this_response(tmp_path):
    project = str(tmp_path / "proj")
    os.makedirs(project)
    record_usage("install", widget_id="cg-zeta-python", version="1.0.0",
                 purpose="ledgerhit zeta", project_root=project)
    record_usage("install", widget_id="cg-plain-python", version="1.0.0",
                 purpose="ledgerhit plain", project_root=project)
    found = prior_for_search(
        "ledgerhit",
        project_root=project,
        library_versions={},
        registry_rows=[{"id": "@ada/cg-zeta-python", "deprecated": True, "stale": False}],
        prefixes=["cg"],
    )
    rows = {row["widget_id"]: row for row in found["block"]["widgets"]}
    assert rows["cg-zeta-python"]["deprecated"] is True
    assert rows["cg-zeta-python"]["stale"] is False
    assert "deprecated" not in rows["cg-plain-python"]
    assert "stale" not in rows["cg-plain-python"]


def test_ledger_write_failure_does_not_fail_install(monkeypatch, tmp_path, capsys):
    from cartograph.cli import cmd_install

    monkeypatch.setattr("cartograph.cli._carto", lambda: _Carto([], []))
    monkeypatch.setattr("cartograph.cli._cloud_install_note", lambda result: None)
    cmd_install(argparse.Namespace(
        widget_id="http-client",
        target=str(tmp_path),
        version=None,
        purpose="x" * 201,
    ))
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert payload["usage_ledger"]["recorded"] is False

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("cartograph.usage_ledger.append", boom)
    cmd_install(argparse.Namespace(
        widget_id="http-client",
        target=str(tmp_path),
        version=None,
        purpose="still ok",
    ))
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert payload["usage_ledger"]["recorded"] is False
    assert "disk full" in payload["usage_ledger"]["error"]


def test_project_key_uses_remote_else_realpath(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:example/widget.git"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    ssh = project_identity(str(repo))
    assert ssh["project_key"] == "git@github.com:example/widget"
    assert ssh["project_remote"] == "git@github.com:example/widget.git"
    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/example/widget.git"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    https = project_identity(str(repo))
    assert https["project_key"] == "https://github.com/example/widget"
    assert ssh["project_key"] != https["project_key"]
    plain = tmp_path / "plain"
    plain.mkdir()
    ident = project_identity(str(plain))
    assert ident["project_remote"] is None
    assert ident["project_key"] == os.path.realpath(str(plain))


def test_git_failure_records_path_only(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise OSError("git missing")

    monkeypatch.setattr("cartograph.usage_ledger.subprocess.run", boom)
    ident = project_identity(str(tmp_path))
    assert ident["project_remote"] is None
    assert ident["project_key"] == os.path.realpath(str(tmp_path))
    info = record_usage(
        "install",
        widget_id="http-client",
        version="1.0.0",
        purpose="offline git",
        project_root=str(tmp_path),
    )
    assert info["recorded"] is True
    rows = _rows(ledger_path())
    assert rows[0]["project_remote"] is None


def test_registry_query_is_unchanged(monkeypatch, tmp_path, capsys):
    from cartograph.cli import cmd_search

    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setattr("cartograph.config.get_registries", lambda: [])
    monkeypatch.setattr("cartograph.auth.cached_whoami", lambda: {})
    calls = []

    def fake_search(query, domain_filter=None, language_filter=None, top_k=10,
                    registry_url=None, languages=None):
        calls.append({
            "query": query,
            "domain_filter": domain_filter,
            "language_filter": language_filter,
            "top_k": top_k,
        })
        return {"widgets": [], "source": "cloud"}

    monkeypatch.setattr("cartograph.cloud.search", fake_search)
    monkeypatch.setattr("cartograph.cli._carto", lambda: _Carto([], []))
    cmd_search(_search_ns(query="json parser"))
    payload = json.loads(capsys.readouterr().out)
    assert calls, "registry search was not called"
    assert all(call["query"] == "json parser" for call in calls)
    assert "prior" not in payload


def test_concurrent_appends_under_path_lock_keep_every_line(tmp_path):
    errors = []

    def worker(index):
        try:
            info = record_usage(
                "note",
                widget_id=f"widget-{index}",
                version="1.0.0",
                purpose=f"parallel {index}",
                project_root=str(tmp_path),
            )
            if not info or not info.get("recorded"):
                errors.append(info)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    rows = _rows(ledger_path())
    assert len(rows) == 8
    assert {row["widget_id"] for row in rows} == {f"widget-{i}" for i in range(8)}


def test_inspect_adds_prior_use(monkeypatch, tmp_path, capsys):
    from cartograph.cli import cmd_inspect

    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.chdir(project)
    record_usage(
        "install",
        widget_id="http-client",
        version="1.2.0",
        purpose="inspect me",
        project_root=str(project),
    )

    class Ref:
        ok = True
        is_cloud = False
        id = "http-client"
        error = None

    monkeypatch.setattr("cartograph.cli._resolve_module_ref", lambda *args, **kwargs: Ref())
    monkeypatch.setattr("cartograph.cli._carto", lambda: _Carto([], []))
    cmd_inspect(argparse.Namespace(
        widget_id="http-client",
        source=False,
        all_versions=False,
        reviews=False,
        version=None,
    ))
    payload = json.loads(capsys.readouterr().out)
    assert payload["prior_use"]["purpose"] == "inspect me"
    assert payload["prior_use"]["same_project"] is True


def test_prior_pool_omits_past_five(tmp_path):
    project = str(tmp_path / "proj")
    os.makedirs(project)
    for index in range(6):
        record_usage(
            "note",
            widget_id=f"item-{index}",
            version="1.0.0",
            purpose="capme row",
            project_root=project,
        )
    found = prior_for_search(
        "capme",
        project_root=project,
        library_versions={},
        registry_rows=[],
        prefixes=["cg"],
    )
    assert found["block"]["count"] == 5
    assert found["block"]["omitted"] == 1
    assert len(found["annotations"]) >= 6
