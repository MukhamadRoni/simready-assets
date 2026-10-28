# Using SimReady assets in Isaac Sim / Isaac Lab

## What's inside an asset (profile `sim`)

```
<asset>/
├── .metadata/                      license, BOM (sha256 per file), root_usds.json
├── com.nvidia.simready.packaging.json
└── simready_usd/
    ├── sm_<asset>_01.usd           ← ROOT: reference this one
    ├── payloads/
    │   ├── base.usda, geometries.usd, materials.usda, instances*.usda
    │   ├── Physics/physics.usda    shared physics (mass, colliders, physics materials)
    │   ├── PhysX/  enabled|disabled.usda
    │   ├── Newton/ enabled|disabled.usda
    │   └── MuJoCo/ enabled|disabled.usda
    ├── Textures/                   PBR textures (Albedo / ORM / Normal)
    └── source_assets/              OmniPBR*.mdl + texture copies (MDL rendering in RTX)
```

Every reference is relative, so **move/copy the whole `<asset>/` folder**, never the root .usd alone.

## Conventions

- **Z-up, metersPerUnit = 1.0** (meters). Matches Isaac Sim defaults, no rescale needed.
- Default prim `/RootNode`. Children: `Geometry/` (instanceable visual meshes), `PhysicsMaterials/`,
  sometimes `ReferencePrims/` (joint anchors) and `Grasp/` (grasp annotation prims, useful for
  pick-and-place).
- Materials carry semantic labels (`semantics:labels:material`, e.g. `nylon`, `cardboard`) and
  physics hints (`pxr:usd:physics_density`, friction, restitution). Handy for synthetic data
  (Replicator) and for picking physics parameters.
- Validation profile is stored in the layer metadata (`Robotics-Prop`, etc.).

## Physics variant sets

The root prim has three variant sets: `PhysX`, `Newton`, `MuJoCo`, each `Enabled` / `Disabled`.
Default is **PhysX = Enabled**, others Disabled. Pick the one matching the simulator:

| Simulator | Set |
|---|---|
| Isaac Sim (PhysX), Isaac Lab default | `PhysX=Enabled` (default, nothing to do) |
| Isaac Lab with Newton backend | `PhysX=Disabled`, `Newton=Enabled` |
| MuJoCo (via USD import / mujoco-usd) | `PhysX=Disabled`, `MuJoCo=Enabled` |

Enable only one at a time; two active physics schemas on the same prim confuse importers.

```python
from pxr import Usd
stage = Usd.Stage.Open("simready/conveyor_belt_a02/simready_usd/sm_conveyor_belt_a02_01.usd")
root = stage.GetDefaultPrim()
root.GetVariantSet("PhysX").SetVariantSelection("Disabled")
root.GetVariantSet("Newton").SetVariantSelection("Enabled")
```
When the asset is *referenced* into a scene, set the variant on the referencing prim instead
(the variant sets come through the reference).

## Loading into a scene

Isaac Sim 4.5+ / 5.x (module names changed from `omni.isaac.*` to `isaacsim.*` in 4.5):

```python
from isaacsim.core.utils.stage import add_reference_to_stage
prim = add_reference_to_stage(
    usd_path="C:/sim/simready/pallet_a01/simready_usd/sm_pallet_a01_01.usd",
    prim_path="/World/Pallet_01",
)
```
Older Isaac Sim (≤ 4.2): `from omni.isaac.core.utils.stage import add_reference_to_stage`.

Pure USD (works anywhere, e.g. building a scene file offline then opening it in Isaac Sim):

```python
from pxr import Usd, UsdGeom, Gf
stage = Usd.Stage.CreateNew("factory_scene.usda")
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
UsdGeom.SetStageMetersPerUnit(stage, 1.0)
world = UsdGeom.Xform.Define(stage, "/World")
stage.SetDefaultPrim(world.GetPrim())

def place(path, usd, pos, yaw_deg=0):
    x = UsdGeom.Xform.Define(stage, path)
    x.GetPrim().GetReferences().AddReference(usd)   # relative or absolute path
    x.AddTranslateOp().Set(Gf.Vec3d(*pos))
    x.AddRotateZOp().Set(yaw_deg)
    return x

place("/World/Conveyor_01", "./simready/conveyor_belt_a02/simready_usd/sm_conveyor_belt_a02_01.usd", (0, 0, 0))
place("/World/Pallet_01", "./simready/pallet_a01/simready_usd/sm_pallet_a01_01.usd", (2.5, 0, 0), 90)
stage.GetRootLayer().Save()
```
Add a ground plane and a `PhysicsScene` in Isaac Sim (or `UsdPhysics.Scene.Define(stage, "/World/physicsScene")`)
before pressing Play, otherwise dynamic props fall forever.

## Isaac Lab

Use the root .usd as `spawn=sim_utils.UsdFileCfg(usd_path=...)` in a `RigidObjectCfg` or
`AssetBaseCfg` (static fixtures like conveyors, racks, desks). Large static props (shelving,
warehouse modules) → `AssetBaseCfg`; things the robot manipulates (boxes, bolts, tools) →
`RigidObjectCfg`. Many props are big (workstation_factory_a01 ≈ 725 MB); for RL with many
envs prefer small props and instanceable references.

## Gotchas

- Opening the root .usd needs `payloads/` and `Textures/` beside it. Missing textures render pink/black.
- MDL materials need `source_assets/` (profile `sim` keeps it). Profile `web` drops it, so in
  Isaac Sim the material falls back to UsdPreviewSurface, which looks slightly different.
- `factory_bolt_*_loose` vs `_tight` and `factory_nut_*` are sized for assembly tasks (M4–M20).
- License CC-BY-4.0 → credit NVIDIA in the project/publication.
