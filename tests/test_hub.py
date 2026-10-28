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
