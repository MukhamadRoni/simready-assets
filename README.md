# simready-assets

Find, download and convert [NVIDIA SimReady](https://huggingface.co/datasets/nvidia/simready-assets)
3D assets (2,603 physics-ready USD props) from Claude Code, Claude Desktop, Cursor or VS Code,
as a skill, an MCP server, or a plain CLI.

The full dataset is 476 GB and is **never downloaded whole**. Assets are fetched one at a time,
only when asked, and sizes are shown before anything is downloaded.

## Install

Requirements for every client: [`uv`](https://docs.astral.sh/uv/) and `git`.

**Warm up once** before adding the MCP. The first `uvx` launch builds from git and installs
`usd-core` (~30 MB), which can exceed a client's MCP startup timeout:

```bash
uvx --from git+https://github.com/MukhamadRoni/simready-assets@v0.1.0 simready --help
```

| Client | How |
|---|---|
| Claude Code (skill + MCP) | `/plugin marketplace add MukhamadRoni/simready-assets` then `/plugin install simready-assets@simready-assets` |
| Claude Code (MCP only) | `claude mcp add simready -- uvx --from git+https://github.com/MukhamadRoni/simready-assets@v0.1.0 simready-mcp` |
| Claude Desktop | edit `claude_desktop_config.json` (below); optional skill: upload `simready-assets-skill.zip` from the GitHub release |
| Cursor | `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global), below |
| VS Code | `.vscode/mcp.json`, below |

When both the skill and the MCP are present, the skill tells Claude to use the MCP tools and to fall
back to the `uvx ... simready` CLI only when they are missing.

### Claude Desktop

`claude_desktop_config.json` (Settings > Developer > Edit Config; `%APPDATA%\Claude\` on Windows,
`~/Library/Application Support/Claude/` on macOS). Restart Desktop afterwards.

```json
{
  "mcpServers": {
    "simready": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/MukhamadRoni/simready-assets@v0.1.0", "simready-mcp"]
    }
  }
}
```

In Desktop the MCP server does the work. The uploaded skill zip is guidance only (workflow, Isaac Sim
and web advice): Desktop skills run in a sandbox that usually has no `uv` and limited network.

### Cursor

`.cursor/mcp.json` or `~/.cursor/mcp.json`, same `mcpServers` shape (`"type": "stdio"` is optional):

```json
{
  "mcpServers": {
    "simready": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/MukhamadRoni/simready-assets@v0.1.0", "simready-mcp"]
    }
  }
}
```

### VS Code

`.vscode/mcp.json` (note the `servers` key):

```json
{
  "servers": {
    "simready": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/MukhamadRoni/simready-assets@v0.1.0", "simready-mcp"]
    }
  }
}
```

Cursor and VS Code have no skills; the MCP serves the guides as resources
(`simready://guide/isaac-sim`, `simready://guide/web-threejs`) and two prompts (`factory-scene`, `web-scene`).

### Configuration

| Env var | Meaning |
|---|---|
| `SIMREADY_DIR` | download root, default `~/simready` (on Windows keep it short, e.g. `C:/simready`) |
| `HF_TOKEN` | optional Hugging Face token for higher rate limits |

Set them in the client's `env` block, e.g. `"env": {"SIMREADY_DIR": "C:/simready"}`.

## MCP tools

| Tool | Does |
|---|---|
| `list_groups` | groups and counts from the bundled catalog (offline) |
| `search_assets` | catalog search, all words must match, optional group |
| `asset_info` | file count, size for a profile, root USD, whether already downloaded |
| `get_thumbnail` | the asset's thumbnail as image content |
| `download_assets` | per-file download into `SIMREADY_DIR`; refuses above `max_total_mb` (default 1024) and returns sizes instead; reports progress per file. If a download times out or is interrupted, just call it again: it resumes (completed files are skipped) |
| `convert_to_glb` | converts a downloaded asset to a self-contained Y-up GLB |

## CLI

Prefix with `uvx --from git+https://github.com/MukhamadRoni/simready-assets@v0.1.0` when not installed:

```bash
simready find conveyor
simready groups
simready info conveyor_belt_a02 --profile web
simready download conveyor_belt_a02 --profile web --dry-run
simready convert conveyor_belt_a02 -o conveyor.glb --max-tex 512 --jpeg
# only in a local checkout (or with --out <file>); under uvx it writes into uv's tool
# environment, which the running MCP server does not read
simready build-catalog --out catalog.tsv
```

## Example prompts

- "Build me a small warehouse scene for Isaac Sim: two conveyors, pallets and boxes. Check sizes first."
- "Find an office chair and put it in a three.js scene."
- "Convert conveyor_belt_a02 to a web-sized GLB."

## License and attribution

Code: MIT (see `LICENSE`). The 3D assets belong to NVIDIA and are licensed CC-BY-4.0 (CC BY 4.0).
When you ship them, credit: `3D assets: NVIDIA SimReady Assets (CC BY 4.0)`, and note if you
converted or modified them (GLB conversion counts).
