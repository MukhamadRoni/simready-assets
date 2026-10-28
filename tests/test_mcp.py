import asyncio
import subprocess
import sys

import pytest

from simready_assets import hub
from simready_assets.hub import AssetNotFound, DownloadPlan
from simready_assets.mcp_server import (asset_info, convert_to_glb, download_assets,
                                        get_thumbnail, mcp, search_assets)


class FakeCtx:
    def __init__(self):
        self.progress = []

    async def report_progress(self, progress, total=None, message=None):
        self.progress.append((progress, total))


def test_tools_resources_prompts_registered():
    tools = {t.name for t in asyncio.run(mcp.list_tools())}
    assert tools == {"list_groups", "search_assets", "asset_info", "get_thumbnail", "download_assets", "convert_to_glb"}
    uris = {str(r.uri) for r in asyncio.run(mcp.list_resources())}
    assert {"simready://guide/isaac-sim", "simready://guide/web-threejs"} <= uris
    assert {p.name for p in asyncio.run(mcp.list_prompts())} == {"factory-scene", "web-scene"}


def test_guides_readable():
    for g in ("isaac-sim", "web-threejs"):
        res = asyncio.run(mcp.read_resource(f"simready://guide/{g}"))
        text = "".join(c.content for c in res)
        assert len(text) > 200 and "scripts/" not in text


def test_prompts_render():
    msgs = asyncio.run(mcp.get_prompt("web-scene", {"description": "a packing line"}))
    text = msgs.messages[0].content.text
    assert "a packing line" in text and "asset_info" in text and "convert_to_glb" in text


def test_search_tool_shape():
    out = search_assets("conveyor")
    assert out["total"] >= 6 and out["assets"][0].keys() == {"name", "group"}


def test_download_over_limit_downloads_nothing(monkeypatch):
    monkeypatch.setattr(hub, "plan_download", lambda a, p: DownloadPlan(p, {"big": 2_000_000_000}, ["x"], []))
    monkeypatch.setattr(hub, "download", lambda *a, **k: pytest.fail("must not download"))
    out = asyncio.run(download_assets(["big"], ctx=FakeCtx()))
    assert out["downloaded"] == [] and "max_total_mb" in out["message"] and "big" in out["message"]


def test_download_reports_missing_and_proceeds(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMREADY_DIR", str(tmp_path))
    monkeypatch.setattr(hub, "plan_download", lambda a, p: DownloadPlan(p, {"ok": 1024}, ["ok/f"], ["nope"]))
    monkeypatch.setattr(hub, "download", lambda plan, dest, **k: {"ok": dest / "ok" / "r.usd"})
    out = asyncio.run(download_assets(["ok", "nope"], ctx=FakeCtx()))
    assert out["downloaded"] == ["ok"] and out["missing"] == ["nope"] and out["dest"] == str(tmp_path)


def test_unknown_asset_is_a_message_not_an_exception(monkeypatch):
    monkeypatch.setattr(hub, "list_files", lambda a: (_ for _ in ()).throw(AssetNotFound(a)))
    assert "search_assets" in asset_info("no_such_asset")["error"]
    monkeypatch.setattr(hub, "thumbnail", lambda a, d: (_ for _ in ()).throw(AssetNotFound(a)))
    assert "search_assets" in get_thumbnail("no_such_asset")["error"]


def test_asset_info_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMREADY_DIR", str(tmp_path))
    files = [hub.RemoteFile("a/simready_usd/a.usd", 1048576), hub.RemoteFile("a/simready_usd/payloads/p.usd", 1048576)]
    monkeypatch.setattr(hub, "list_files", lambda a: files)
    out = asset_info("a")
    assert out["name"] == "a" and out["profile"] == "sim" and out["size_mb"] == 2.0
    assert out["root_usd"] == "a/simready_usd/a.usd" and out["local_path"] is None and out["files"] == 2


def test_convert_missing_is_error(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMREADY_DIR", str(tmp_path))
    err = asyncio.run(convert_to_glb("ghost", ctx=FakeCtx()))["error"]
    assert "not found at" in err and str(tmp_path / "ghost") in err
    assert "profile 'web' or 'sim'" not in err


def test_convert_existing_folder_without_usd_hints_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMREADY_DIR", str(tmp_path))
    (tmp_path / "thumbonly" / "simready_usd" / ".thumbs").mkdir(parents=True)
    err = asyncio.run(convert_to_glb("thumbonly", ctx=FakeCtx()))["error"]
    assert "profile 'web' or 'sim'" in err


def test_asset_info_thumbnail_only_is_not_downloaded(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMREADY_DIR", str(tmp_path))
    files = [hub.RemoteFile("a/simready_usd/a.usd", 10)]
    monkeypatch.setattr(hub, "list_files", lambda a: files)
    thumbs = tmp_path / "a" / "simready_usd" / ".thumbs"
    thumbs.mkdir(parents=True)
    (thumbs / "t_thumbnail.png").write_text("x")
    assert asset_info("a")["local_path"] is None
    (tmp_path / "a" / "simready_usd" / "a.usd").write_text("x")
    assert asset_info("a")["local_path"] == str(tmp_path / "a")


def test_download_reports_progress_and_runs_off_loop(monkeypatch, tmp_path):
    import threading
    monkeypatch.setenv("SIMREADY_DIR", str(tmp_path))
    monkeypatch.setattr(hub, "plan_download", lambda a, p: DownloadPlan(p, {"ok": 1024}, ["ok/f", "ok/g"], []))
    seen = {}

    def fake_download(plan, dest, on_file=None, **k):
        seen["thread"] = threading.current_thread()
        on_file(1, 2)
        on_file(2, 2)
        return {"ok": None}
    monkeypatch.setattr(hub, "download", fake_download)
    ctx = FakeCtx()
    out = asyncio.run(download_assets(["ok"], ctx=ctx))
    assert out["downloaded"] == ["ok"]
    assert ctx.progress == [(1, 2), (2, 2)]
    assert seen["thread"] is not threading.main_thread()


def test_download_progress_failure_does_not_break(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMREADY_DIR", str(tmp_path))
    monkeypatch.setattr(hub, "plan_download", lambda a, p: DownloadPlan(p, {"ok": 1024}, ["ok/f"], []))
    monkeypatch.setattr(hub, "download", lambda plan, dest, on_file=None, **k: (on_file(1, 1), {"ok": None})[1])

    class Bad(FakeCtx):
        async def report_progress(self, *a, **k):
            raise RuntimeError("client gone")
    assert asyncio.run(download_assets(["ok"], ctx=Bad()))["downloaded"] == ["ok"]


def test_ctx_not_in_tool_schema():
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for n in ("download_assets", "convert_to_glb"):
        assert "ctx" not in tools[n].inputSchema["properties"]
    assert tools["download_assets"].inputSchema["properties"]["max_total_mb"]["type"] == "number"


def test_import_does_no_network():
    code = ("import socket\n"
            "def boom(*a, **k): raise RuntimeError('network at import')\n"
            "socket.socket.connect = boom\n"
            "import simready_assets.mcp_server")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
