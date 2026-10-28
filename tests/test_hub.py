from pathlib import Path

import httpx
import pytest

from simready_assets import hub
from simready_assets.hub import (AssetNotFound, RemoteFile, long_path_warning, matches,
                                 plan_download, root_usd)


def test_profiles_web_excludes_mdl_and_thumbs():
    assert matches("a/simready_usd/payloads/base.usda", "a", "web")
    assert not matches("a/simready_usd/source_assets/OmniPBR.mdl", "a", "web")
    assert not matches("a/simready_usd/.thumbs/256x256/x.png", "a", "sim")
    assert matches("a/simready_usd/.thumbs/sm_a_01_thumbnail.png", "a", "thumb")


def test_plan_skips_missing_and_sums_sizes(monkeypatch):
    def fake(asset):
        if asset == "nope":
            raise AssetNotFound(asset)
        return [RemoteFile(f"{asset}/simready_usd/sm_{asset}_01.usd", 100),
                RemoteFile(f"{asset}/simready_usd/source_assets/x.mdl", 50)]
    monkeypatch.setattr(hub, "list_files", fake)
    p = plan_download(["a", "nope"], "web")
    assert p.missing == ["nope"] and p.sizes == {"a": 100} and p.total_bytes == 100
    assert p.files == ["a/simready_usd/sm_a_01.usd"]


def test_root_usd_accepts_usda(tmp_path):
    d = tmp_path / "bolt" / "simready_usd"
    d.mkdir(parents=True)
    (d / "sm_bolt_01.usda").write_text("#usda 1.0")
    assert root_usd(tmp_path / "bolt").name == "sm_bolt_01.usda"


def test_root_usd_missing_says_which_profile(tmp_path):
    (tmp_path / "x").mkdir()
    with pytest.raises(FileNotFoundError, match="profile 'web' or 'sim'"):
        root_usd(tmp_path / "x")


def test_long_path_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(hub.os, "name", "nt")
    assert long_path_warning(Path("C:/" + "d" * 90)) and long_path_warning(Path("C:/simready")) is None


def test_list_files_not_found_family(monkeypatch):
    from huggingface_hub.errors import RepositoryNotFoundError

    class FakeApi:
        def list_repo_tree(self, *a, **k):
            raise RepositoryNotFoundError("404", response=httpx.Response(404, request=httpx.Request("GET", "http://x")))
    monkeypatch.setattr(hub, "HfApi", FakeApi)
    with pytest.raises(AssetNotFound):
        hub.list_files("x")


def test_list_files_empty_and_filters_dirs(monkeypatch):
    class Item:
        def __init__(self, path, size):
            self.path, self.size = path, size

    class FakeApi:
        items = []

        def list_repo_tree(self, *a, **k):
            return iter(FakeApi.items)
    monkeypatch.setattr(hub, "HfApi", FakeApi)
    with pytest.raises(AssetNotFound):
        hub.list_files("x")
    FakeApi.items = [Item("x/d", None), Item("x/f", 3)]
    assert hub.list_files("x") == [RemoteFile("x/f", 3)]


def test_download_uses_per_file_and_returns_roots(monkeypatch, tmp_path):
    calls = []

    def fake(repo, path, repo_type, local_dir):
        calls.append(path)
        f = Path(local_dir) / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
        return str(f)
    monkeypatch.setattr(hub, "hf_hub_download", fake)
    plan = hub.DownloadPlan("web", {"a": 1}, ["a/simready_usd/sm_a.usd"], [])
    out = hub.download(plan, tmp_path)
    assert calls == ["a/simready_usd/sm_a.usd"]
    assert out["a"] == tmp_path / "a" / "simready_usd" / "sm_a.usd"
    plan = hub.DownloadPlan("thumb", {"a": 1}, ["a/simready_usd/.thumbs/t_thumbnail.png"], [])
    assert hub.download(plan, tmp_path) == {"a": None}


def test_root_usd_reads_metadata_entries(tmp_path):
    import json
    a = tmp_path / "box"
    (a / "simready_usd").mkdir(parents=True)
    (a / ".metadata").mkdir()
    (a / "simready_usd" / "a_first.usd").write_text("x")
    (a / "simready_usd" / "z_named.usd").write_text("x")
    (a / ".metadata" / "com.nvidia.simready.root_usds.json").write_text(
        json.dumps({"format_version": "1.0", "entries": ["simready_usd/z_named.usd"]}))
    assert root_usd(a).name == "z_named.usd"


def test_thumbnail_excludes_dark(monkeypatch, tmp_path):
    monkeypatch.setattr(hub, "list_files", lambda a: [
        RemoteFile("a/simready_usd/.thumbs/a_01_thumbnail_dark.png", 1),
        RemoteFile("a/simready_usd/.thumbs/a_01_thumbnail.png", 1)])
    got = []
    monkeypatch.setattr(hub, "hf_hub_download", lambda r, p, **k: got.append(p) or p)
    hub.thumbnail("a", tmp_path)
    assert got == ["a/simready_usd/.thumbs/a_01_thumbnail.png"]


def test_default_dir_expands_tilde_and_vars(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMREADY_DIR", "~/x")
    assert "~" not in str(hub.default_dir())
    monkeypatch.setenv("FOO_T", str(tmp_path))
    monkeypatch.setenv("SIMREADY_DIR", "$FOO_T/y")
    assert hub.default_dir() == tmp_path / "y"


def test_invalid_names_make_no_network_call(monkeypatch):
    class Boom:
        def list_repo_tree(self, *a, **k):
            raise AssertionError("network call")
    monkeypatch.setattr(hub, "HfApi", Boom)
    for bad in ("", "a/../b", "../x", "-x"):
        with pytest.raises(AssetNotFound):
            hub.list_files(bad)
        with pytest.raises(AssetNotFound):
            hub.thumbnail(bad, Path("."))
        assert hub.plan_download([bad], "web").missing == [bad]


def test_download_calls_on_file(monkeypatch, tmp_path):
    def fake(repo, path, repo_type, local_dir):
        f = Path(local_dir) / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
        return str(f)
    monkeypatch.setattr(hub, "hf_hub_download", fake)
    seen = []
    plan = hub.DownloadPlan("thumb", {"a": 1}, ["a/1", "a/2", "a/3"], [])
    hub.download(plan, tmp_path, on_file=lambda d, t: seen.append((d, t)))
    assert sorted(seen) == [(1, 3), (2, 3), (3, 3)]


def test_long_path_warning_wording(monkeypatch):
    monkeypatch.setattr(hub.os, "name", "nt")
    assert "SIMREADY_DIR / --dest" in long_path_warning(Path("C:/" + "a" * 90))
