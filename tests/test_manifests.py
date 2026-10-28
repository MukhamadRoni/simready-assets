import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = "git+https://github.com/MukhamadRoni/simready-assets@v0.1.0"
TOOLS = ["list_groups", "search_assets", "asset_info", "get_thumbnail", "download_assets", "convert_to_glb"]


def load(p):
    return json.loads((ROOT / p).read_text(encoding="utf-8"))


def test_marketplace():
    m = load(".claude-plugin/marketplace.json")
    assert m["name"] == "simready-assets"
    assert m["plugins"][0]["name"] == "simready-assets"
    assert m["plugins"][0]["source"] == "./"


def test_plugin_json():
    p = load(".claude-plugin/plugin.json")
    assert p["name"] == "simready-assets" and p["license"] == "MIT"


def test_mcp_json():
    m = load(".mcp.json")
    assert m["mcpServers"]["simready"]["args"] == ["--from", SPEC, "simready-mcp"]


def test_skill():
    text = (ROOT / "skills/simready-assets/SKILL.md").read_text(encoding="utf-8")
    assert re.match(r"---\nname: simready-assets\n", text)
    for t in TOOLS:
        assert t in text
    assert f"uvx --from {SPEC} simready" in text
    assert "scripts/" not in text


def test_skill_references_match_package_guides():
    for n in ("isaac-sim.md", "web-threejs.md"):
        a = (ROOT / "skills/simready-assets/references" / n).read_bytes()
        b = (ROOT / "src/simready_assets/guides" / n).read_bytes()
        assert a == b


def test_readme_and_license():
    r = (ROOT / "README.md").read_text(encoding="utf-8")
    for s in ["CC BY 4.0", "Claude Code", "Claude Desktop", "Cursor", "VS Code", "simready --help"]:
        assert s in r
    assert "Copyright (c) 2026 Mukhamad Roni" in (ROOT / "LICENSE").read_text(encoding="utf-8")
