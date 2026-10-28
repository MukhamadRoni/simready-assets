from simready_assets import cli, hub
from simready_assets.hub import DownloadPlan


def test_find(capsys):
    assert cli.main(["find", "conveyor"]) == 0
    assert "conveyor_belt_a02" in capsys.readouterr().out


def test_groups(capsys):
    assert cli.main(["groups"]) == 0
    out = capsys.readouterr().out
    assert "office" in out and "201" in out


def test_convert_missing(capsys, tmp_path):
    assert cli.main(["convert", "no_such_asset", "--dest", str(tmp_path)]) == 2
    assert "not found at" in capsys.readouterr().err


def test_download_over_limit(capsys, monkeypatch, tmp_path):
    plan = DownloadPlan("web", {"a": 1024 * 1024}, ["a/x"], [])
    monkeypatch.setattr(hub, "plan_download", lambda assets, profile: plan)
    def boom(*a, **k):
        raise AssertionError("download called")
    monkeypatch.setattr(hub, "download", boom)
    rc = cli.main(["download", "a", "--max-total-mb", "0", "--dest", str(tmp_path)])
    assert rc == 1
    assert "1.0 MB" in capsys.readouterr().out


def test_download_missing_and_ok(capsys, monkeypatch, tmp_path):
    plan = DownloadPlan("web", {"a": 10}, ["a/x"], ["nope"])
    monkeypatch.setattr(hub, "plan_download", lambda assets, profile: plan)
    monkeypatch.setattr(hub, "download", lambda p, d: {"a": d / "a" / "r.usd"})
    assert cli.main(["download", "a", "nope", "--dest", str(tmp_path)]) == 0
    out = capsys.readouterr()
    assert "!! nope: not found. Try: simready find <word>" in out.err + out.out


def test_download_all_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(hub, "plan_download", lambda a, p: DownloadPlan(p, {}, [], list(a)))
    assert cli.main(["download", "nope", "--dest", str(tmp_path)]) == 1


def test_default_profile_is_sim():
    p = cli._parser()
    assert p.parse_args(["info", "x"]).profile == "sim"
    assert p.parse_args(["download", "x"]).profile == "sim"


def test_info_thumbnail_only_not_downloaded(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(hub, "plan_download", lambda a, p: DownloadPlan(p, {"a": 1}, ["a/simready_usd/a.usd"], []))
    (tmp_path / "a" / "simready_usd" / ".thumbs").mkdir(parents=True)
    assert cli.main(["info", "a", "--dest", str(tmp_path)]) == 0
    assert "not downloaded" in capsys.readouterr().out
    (tmp_path / "a" / "simready_usd" / "a.usd").write_text("x")
    cli.main(["info", "a", "--dest", str(tmp_path)])
    assert "(present)" in capsys.readouterr().out


def test_convert_not_found_vs_no_usd(capsys, tmp_path):
    assert cli.main(["convert", "ghost", "--dest", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "not found at" in err and "profile 'web' or 'sim'" not in err
    (tmp_path / "empty" / "simready_usd").mkdir(parents=True)
    assert cli.main(["convert", "empty", "--dest", str(tmp_path)]) == 2
    assert "profile 'web' or 'sim'" in capsys.readouterr().err


def test_from_file_bom_and_comments(monkeypatch, tmp_path):
    f = tmp_path / "n.txt"
    f.write_bytes(b"\xef\xbb\xbf# header\n  # indented comment\nalpha\n\nbeta\n")
    got = {}

    def plan(names, profile):
        got["names"] = names
        return DownloadPlan(profile, {}, [], list(names))
    monkeypatch.setattr(hub, "plan_download", plan)
    cli.main(["download", "--from-file", str(f), "--dest", str(tmp_path)])
    assert got["names"] == ["alpha", "beta"]
