---
name: simready-assets
description: Find, download and use NVIDIA SimReady 3D assets (Hugging Face dataset nvidia/simready-assets, 2,600+ physics-ready USD props, CC-BY-4.0) for robotics simulation (Isaac Sim, Isaac Lab, MuJoCo, Newton) and web 3D (three.js, React Three Fiber, glTF/GLB). Covers machinery, conveyors, robots, factory/manufacturing workstations, tools, bolts/nuts, warehouse logistics (boxes, pallets, racks, carts), facility/safety items and office furniture/equipment. Use this skill whenever the user wants 3D models or props for a factory, warehouse, manufacturing line, workshop or office scene, a digital twin, a robot simulation environment, pick-and-place objects, or a web 3D scene, or asks about SimReady, Omniverse assets, or converting USD to GLB, even if they don't name the dataset.
---

# SimReady Assets

NVIDIA's SimReady dataset is ~476 GB, so never download it whole. The workflow is:
**search the bundled catalog -> check the size -> download only the picked assets -> use them in
the simulator directly, or convert them to GLB for the web.**

## How to run each step

Two interchangeable routes. Use the MCP tool when the `simready` MCP server is connected;
otherwise run the CLI through uv (needs `uv` and `git`):

```
uvx --from git+https://github.com/MukhamadRoni/simready-assets@v0.1.0 simready <subcommand>
```

The first launch is slow (git build plus the `usd-core` wheel). If it times out, run
`uvx --from git+https://github.com/MukhamadRoni/simready-assets@v0.1.0 simready --help` once to warm the cache.

**Claude Desktop:** uploaded skills run in a sandbox that usually has no `uv` and limited network.
There the MCP server does the work and this skill is guidance only (workflow, Isaac Sim and web
advice). Do not promise that the skill alone can download assets in Desktop.

| Step | MCP tool | CLI fallback (`simready` = the uvx command above) |
|---|---|---|
| Group counts | `list_groups` | `simready groups` |
| Search | `search_assets` | `simready find <words> [--group G]` |
| Size and root USD | `asset_info` | `simready info <name> --profile sim` |
| Look at it | `get_thumbnail` | `simready download <name> --profile thumb` |
| Download | `download_assets` | `simready download <names> --profile sim [--dry-run]` |
| USD to GLB | `convert_to_glb` | `simready convert <name or asset dir> -o out.glb --max-tex 1024 --jpeg` |
| Refresh catalog (local checkout only) | (none) | `simready build-catalog --out <file>` |

Downloads go to `SIMREADY_DIR` (default `~/simready`). `HF_TOKEN` is optional (higher Hugging Face
rate limits). An unknown asset name returns "not found, try search_assets": fix the name, don't retry blindly.

## 1. Find assets

Groups in the catalog (counts as of Oct 2026):

| group | n | examples |
|---|---|---|
| `machinery_robotics` | 131 | conveyor_belt_*, robotic_system_arm_*, equipment_3d_printer, powerTool_welding_station, airSystem_compressor, machineGuard |
| `factory_tools` | 265 | workstation_factory_a01, factory_bolt/nut (M4–M20, loose/tight), handTool_*, serviceTool_*, testingTool_* |
| `vehicle_parts` | 220 | engineComponent_*, drivetrain_*, brakeSystem_*, vehicleSupport_* (automotive manufacturing/service) |
| `warehouse_logistics` | 447 | box_*, pallet_*, crate_*, rack_*, palletJack_*, vehicle_forklift_*, cart_*, drum_*, ibcTank_* |
| `facility_safety` | 380 | barrier_*, sign_*, ppe_*, fireProtection_*, ladder_*, structure_* (walls, beams), lighting_* |
| `office` | 201 | chair_office_*, desk_a01, computer_*, monitor_*, cabinet_*, stationery_*, trashCan_office_* |
| `kitchen_food`, `medical`, `other` | rest | food, kitchenware, hospital devices, toys |

Use `list_groups` for counts, then `search_assets` with space-separated words (all must match),
optionally with a `group`. CLI: `simready find bolt m8`, `simready find --group office chair`.

The catalog doesn't tell you what an asset looks like. When the choice matters (e.g. which of 6
conveyors), fetch thumbnails first with `get_thumbnail` (CLI: `download --profile thumb`, about
1 MB each) and look at them before pulling full assets. Suffixes `_a01`, `_b02` are variants of the
same object family.

If a search finds nothing, the bundled catalog may be older than the dataset (under `uvx` it can't be
refreshed in place). Some things simply aren't in it (e.g. CNC machines, injection-molding lines,
jewelry/gold processing). Say so plainly and suggest the nearest substitutes instead of inventing names.

## 2. Check size, then download

Assets range from a few MB to ~725 MB (workstation_factory_a01); even a small M8 bolt is 80 MB
because of 4K textures. Always check the total first (`asset_info`, or `download --dry-run`) and
tell the user before downloading anything big (>1 GB). `download_assets` refuses and returns sizes
when the total exceeds `max_total_mb` (default 1024); only re-call with a higher limit after the
user agrees.

| profile | use for | contents |
|---|---|---|
| `sim` | Isaac Sim / Isaac Lab / MuJoCo | everything incl. physics variants + MDL materials |
| `web` | converting to GLB | USD + payloads + textures (no MDL copies; ~40 % smaller) |
| `thumb` | choosing | thumbnails only |

For many assets pass a list of names (CLI: `--from-file picks.txt`). On Windows keep `SIMREADY_DIR`
short (e.g. `C:/simready`): deep paths overflow the 260-character limit. Keep each asset's folder
intact: the root `.usd` (sometimes `.usda`) references `payloads/` and `Textures/` by relative path.

## 3a. Robotics simulation

Read `references/isaac-sim.md` (the MCP also serves it as resource `simready://guide/isaac-sim`).
The essentials: the root file is `<asset>/simready_usd/sm_<asset>_01.usd`; Z-up, meters (matches
Isaac Sim, no rescale); default prim `/RootNode` has variant sets `PhysX` (default Enabled),
`Newton`, `MuJoCo`. Enable exactly one, matching the target simulator. Static fixtures (conveyors,
racks, desks) vs. manipulable props (boxes, bolts, tools) get different treatment in Isaac Lab.

## 3b. Web 3D

Read `references/web-threejs.md` (MCP resource `simready://guide/web-threejs`). Convert with
`convert_to_glb` (`max_tex` 1024, `jpeg` true), or from the CLI:

```bash
simready convert conveyor_belt_a02 -o public/assets/conveyor_belt_a02.glb --max-tex 1024 --jpeg
```

Output is Y-up, meters, textures embedded. It reports triangle count, file size and real-world
dimensions. Raw SimReady assets are heavy (a conveyor is 59 MB unconverted, 290k triangles), so
for the web always downscale textures and then meshopt-compress (about 1.6 MB for that conveyor;
recipe in the reference). Physics does not survive the conversion; glTF has none.

The converter reads the UsdPreviewSurface fallback of each material (not MDL), bakes instance
transforms, and splits per-face material subsets. If an asset converts with no textures or odd
colors, check that its `Textures/` folder was downloaded (`web` or `sim` profile, not `thumb`).
Converting an asset fetched only as `thumb` (or not fetched) returns an error naming the profile to download.

## Scene building tips

- For a whole factory/office scene, plan a short shopping list first (e.g. 2 conveyors, 3 pallet
  types, boxes, 1 robot arm, barriers, signage) and check the total size together, so the user sees it up front.
- Reuse: one download per asset, many placements (USD references / three.js `clone()`).
- Real-world scale is already correct, so place by meters and don't rescale.

## License

CC-BY-4.0. When the output ships (web page, paper, video, repo), add attribution such as
"3D assets: NVIDIA SimReady Assets (CC BY 4.0)" and mention that GLB files were converted/modified.
