"""simready MCP server (stdio). Importing this module does no network I/O."""
from __future__ import annotations

from pathlib import Path

import anyio
import anyio.from_thread
import anyio.to_thread
from mcp.server.fastmcp import Context, FastMCP, Image

from . import catalog, hub

mcp = FastMCP("simready")

_GUIDES = Path(__file__).with_name("guides")
_MB = 1024 * 1024
_ROOT_EXTS = ("usd", "usda", "usdc")


def _not_found(name: str) -> dict:
    return {"error": f"{name}: not found. Use search_assets to find valid asset names."}


def _bad_profile(profile: str) -> dict | None:
    if profile not in hub.PROFILES:
        return {"error": f"unknown profile {profile!r}; choose one of: {', '.join(hub.PROFILES)}"}
    return None


@mcp.tool()
def list_groups() -> dict:
    """List asset groups (categories) in the offline SimReady catalog with asset counts. No network."""
    return {"groups": catalog.groups()}


@mcp.tool()
def search_assets(query: str, group: str | None = None, limit: int = 50) -> dict:
    """Search the offline SimReady catalog by name words (e.g. "conveyor", "pallet"), optionally within a group
    from list_groups. Returns {"total", "assets": [{"name", "group"}]}; no network, no sizes."""
    try:
        rows, total = catalog.search(query, group, limit)
        return {"total": total, "assets": [{"name": r.name, "group": r.group} for r in rows]}
    except Exception as e:  # never raise from a tool
        return {"error": str(e)}


@mcp.tool()
def asset_info(name: str, profile: str = "sim") -> dict:
    """Show what downloading an asset would fetch: size_mb (megabytes) for the profile ("sim" = everything,
    "web" = USD + textures only, "thumb" = thumbnail), file count, root_usd (path inside the dataset) and
    local_path (under SIMREADY_DIR, or null if not downloaded). Makes one Hugging Face listing call."""
    try:
        bad = _bad_profile(profile)
        if bad:
            return bad
        listing = hub.list_files(name)
        picked = [f for f in listing if hub.matches(f.path, name, profile)]
        roots = [f.path for f in picked if f.path.count("/") == 2 and f.path.split("/")[1] == "simready_usd"
                 and f.path.rsplit(".", 1)[-1] in _ROOT_EXTS]
        local = hub.default_dir() / name
        return {"name": name, "profile": profile,
                "size_mb": round(sum(f.size for f in picked) / _MB, 2), "files": len(picked),
                "root_usd": sorted(roots)[0] if roots else None,
                "local_path": str(local) if hub.is_downloaded(local) else None}
    except hub.AssetNotFound:
        return _not_found(name)
    except Exception as e:
        return {"error": f"{name}: {e}"}


@mcp.tool()
def get_thumbnail(name: str):
    """Return the asset's preview thumbnail image (PNG). Downloads one small file into SIMREADY_DIR."""
    try:
        return Image(path=str(hub.thumbnail(name, hub.default_dir())))
    except hub.AssetNotFound:
        return _not_found(name)
    except Exception as e:
        return {"error": f"{name}: {e}"}


@mcp.tool()
async def download_assets(names: list[str], profile: str = "sim", max_total_mb: float = 1024,
                          ctx: Context = None) -> dict:
    """Download assets from Hugging Face into SIMREADY_DIR (default ~/simready). Sizes are in MB. Refuses and
    downloads nothing if the combined size exceeds max_total_mb (the message lists per-asset sizes); check
    asset_info first and confirm large downloads with the user. Unknown names are reported in "missing" while
    valid ones still proceed. Profiles: "sim" (full), "web" (USD+textures, enough for convert_to_glb), "thumb". If a download times out or is interrupted, just
    call it again: it resumes (files already completed are skipped). Progress is reported per file."""
    dest = hub.default_dir()
    try:
        bad = _bad_profile(profile)
        if bad:
            return {"downloaded": [], "missing": [], "total_mb": 0.0, "dest": str(dest),
                    "message": bad["error"], "error": bad["error"]}
        plan = await anyio.to_thread.run_sync(hub.plan_download, list(names), profile)
        sizes_mb = {n: round(s / _MB, 1) for n, s in plan.sizes.items()}
        total_mb = round(plan.total_bytes / _MB, 1)
        out = {"downloaded": [], "missing": list(plan.missing), "total_mb": total_mb, "dest": str(dest),
               "message": ""}
        notes = [f"{m}: not found. Use search_assets to find valid asset names." for m in plan.missing]
        if not plan.sizes:
            out["message"] = " ".join(notes) or "nothing to download"
            return out
        if plan.total_bytes > max_total_mb * _MB:
            per = ", ".join(f"{n}: {s} MB" for n, s in sizes_mb.items())
            notes.append(f"Total {total_mb} MB exceeds max_total_mb={max_total_mb}; nothing downloaded. "
                         f"Per-asset sizes: {per}. Raise max_total_mb or pick fewer assets / profile 'web'.")
            out["message"] = " ".join(notes)
            return out
        warn = hub.long_path_warning(dest)
        if warn:
            notes.append(warn)

        def on_file(done: int, total: int) -> None:
            # runs in a worker thread; hop back onto the event loop to send the notification
            if ctx is not None:
                try:
                    anyio.from_thread.run(ctx.report_progress, done, total)
                except Exception:  # progress is best-effort; never fail the download
                    pass

        await anyio.to_thread.run_sync(lambda: hub.download(plan, dest, on_file=on_file))
        out["downloaded"] = list(plan.sizes)
        notes.append(f"Downloaded {len(plan.sizes)} asset(s), {total_mb} MB, to {dest}.")
        out["message"] = " ".join(notes)
        return out
    except Exception as e:
        return {"downloaded": [], "missing": [], "total_mb": 0.0, "dest": str(dest),
                "message": f"error: {e}", "error": str(e)}


@mcp.tool()
async def convert_to_glb(name_or_path: str, max_tex: int = 1024, jpeg: bool = True,
                         ctx: Context = None) -> dict:
    """Convert a downloaded asset (bare name under SIMREADY_DIR, or a path to an asset folder or .usd file) to a
    web-ready .glb (Y-up, metres, textures embedded). max_tex caps texture side in pixels; jpeg re-encodes
    textures to shrink the file. Needs the asset downloaded with profile "web" or "sim" first. Returns path,
    size_mb (MB), meshes, triangles, materials, textures, dims_m (metres, [x, y, z])."""
    try:
        from . import convert as conv

        target = hub.resolve_target(name_or_path, hub.default_dir())
        r = await anyio.to_thread.run_sync(conv.convert, target, None, max_tex, jpeg)
        return {"path": str(r.path), "meshes": r.meshes, "triangles": r.triangles, "materials": r.materials,
                "textures": r.textures, "size_mb": r.size_mb, "dims_m": list(r.dims_m)}
    except (FileNotFoundError, ValueError) as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"conversion failed: {e}"}


def _guide(name: str) -> str:
    return (_GUIDES / f"{name}.md").read_text(encoding="utf-8")


@mcp.resource("simready://guide/isaac-sim", mime_type="text/markdown")
def guide_isaac_sim() -> str:
    """Using SimReady USD assets in Isaac Sim / Isaac Lab."""
    return _guide("isaac-sim")


@mcp.resource("simready://guide/web-threejs", mime_type="text/markdown")
def guide_web_threejs() -> str:
    """Converting SimReady assets to GLB and loading them in three.js."""
    return _guide("web-threejs")


@mcp.prompt(name="factory-scene")
def factory_scene(description: str) -> str:
    """Plan a simulation scene (Isaac Sim) from available SimReady assets."""
    return (f"Build a factory/simulation scene: {description}\n\n"
            "1. Read resource simready://guide/isaac-sim.\n"
            "2. Use list_groups and search_assets to find candidate assets for each object in the scene.\n"
            "3. Call asset_info on each pick (profile 'sim') and report sizes in MB.\n"
            "4. Confirm the asset list and total size with the user before downloading.\n"
            "5. Call download_assets (raise max_total_mb only if the user agreed).\n"
            "6. Write the Isaac Sim script that places the downloaded USD files, following the guide.\n"
            "Credit: 3D assets: NVIDIA SimReady Assets (CC BY 4.0).")


@mcp.prompt(name="web-scene")
def web_scene(description: str) -> str:
    """Plan a three.js web scene from available SimReady assets."""
    return (f"Build a web 3D scene: {description}\n\n"
            "1. Read resource simready://guide/web-threejs.\n"
            "2. Use list_groups and search_assets to find candidate assets.\n"
            "3. Call asset_info on each pick (profile 'web') and report sizes in MB.\n"
            "4. Confirm the asset list and total size with the user before downloading.\n"
            "5. Call download_assets with profile 'web'.\n"
            "6. Call convert_to_glb for each asset (max_tex 1024, jpeg true unless a hero object).\n"
            "7. Write the three.js loading code from the web guide, using the produced .glb files.\n"
            "Credit: 3D assets: NVIDIA SimReady Assets (CC BY 4.0).")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
