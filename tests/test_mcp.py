import asyncio
import subprocess
import sys

import pytest

from simready_assets import hub
from simready_assets.hub import AssetNotFound, DownloadPlan
from simready_assets.mcp_server import (asset_info, convert_to_glb, download_assets,
                                        get_thumbnail, mcp, search_assets)


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
    out = download_assets(["big"])
    assert out["downloaded"] == [] and "max_total_mb" in out["message"] and "big" in out["message"]


def test_download_reports_missing_and_proceeds(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMREADY_DIR", str(tmp_path))
    monkeypatch.setattr(hub, "plan_download", lambda a, p: DownloadPlan(p, {"ok": 1024}, ["ok/f"], ["nope"]))
    monkeypatch.setattr(hub, "download", lambda plan, dest, **k: {"ok": dest / "ok" / "r.usd"})
    out = download_assets(["ok", "nope"])
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
    assert "download" in convert_to_glb("ghost")["error"].lower()


def test_import_does_no_network():
    code = ("import socket\n"
            "def boom(*a, **k): raise RuntimeError('network at import')\n"
            "socket.socket.connect = boom\n"
            "import simready_assets.mcp_server")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
