"""Offline catalog of NVIDIA SimReady assets: load, search, categorize, rebuild."""
from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import NamedTuple

REPO = "nvidia/simready-assets"

PREFIX_GROUPS = {
    "machinery_robotics": """conveyor robotic robot robotics machine machineGuard equipment powerTool pump
        extrusion hopper airSystem workshopSystem hvac ventilation climate purifier humidifier laser""",
    "vehicle_parts": """engineComponent engineAssembly engine drivetrain suspension brakeSystem steeringSystem
        steering coolingSystem fuelSystem exhaustSystem electricalSystem wheelAssembly carFrame headlight
        interiorPart vehicle vehicleSupport""",
    "factory_tools": """factory workstation handTool serviceTool testingTool tool tools tireTool instrument
        measurement hardware screw detector""",
    "warehouse_logistics": """box pallet palletJack crate container drum ibcTank rack storage storageSystem
        trolley cart handTruck tiltTruck warehouse pail bucket bin tape case paperbag shelve modular
        primitives""",
    "facility_safety": """ppe safety safetyBoard sign barrier fireProtection fireExtinguisher ladder scaffold
        structure rail ramp grid pipe wire electrical socket lighting light lamp facilitySystem
        facilityEquipment construction paint cleaning trash trashCan waste wasteManagement drainage
        environment security power panel fixture consumable digitalSystem unit water clogs facemask
        mask""",
    "office": """stationery stationary computer monitor screen chair desk table cabinet sofa furniture
        facilityFurniture paper blinds decor phone stapler book magazines set TV video dispenser
        mirror stool appliance pendant""",
    "kitchen_food": """food kitchenware dishware utensil utensils bottle refrigerator extractor warmer sink
        washBasin fauset tray""",
    "medical": """IV Xray CT anesthesia bandage blood cannulae catheter defibrillator drape hemodialysis
        medicine medical needle oximeter stethoscope syringe thermometer ultrasound wheelChair bed
        bedding lung bodyPart device pad disinfectant sanitary toilet arm supply""",
}
PREFIX_TO_GROUP = {p: g for g, ps in PREFIX_GROUPS.items() for p in ps.split()}

# substrings that win over the prefix (an office trash can is office furniture, not waste handling)
NAME_OVERRIDES = [("office", "office"), ("conveyor", "machinery_robotics"), ("robot", "machinery_robotics"),
                  ("forklift", "warehouse_logistics"), ("notebook", "office"), ("printerPaper", "office"),
                  ("tape_dispenser", "office"), ("vending", "office"), ("beverageStation", "office"),
                  ("kitchenette", "office"), ("3d_printer", "machinery_robotics"),
                  ("sprayBooth", "machinery_robotics"), ("parts_washer", "machinery_robotics")]


class Asset(NamedTuple):
    name: str
    group: str
    prefix: str


def categorize(name: str) -> str:
    low = name.lower()
    for sub, group in NAME_OVERRIDES:
        if sub.lower() in low:
            return group
    return PREFIX_TO_GROUP.get(name.split("_")[0], "other")


@lru_cache(maxsize=1)
def _load() -> tuple[Asset, ...]:
    text = resources.files("simready_assets").joinpath("catalog.tsv").read_text(encoding="utf-8")
    lines = text.splitlines()[1:]
    return tuple(Asset(*line.split("\t")) for line in lines if line.strip())


def load_catalog() -> list[Asset]:
    return list(_load())


def search(query: str = "", group: str | None = None, limit: int = 50) -> tuple[list[Asset], int]:
    words = query.lower().split()
    hits = [a for a in _load()
            if (not group or a.group == group)
            and all(w in " ".join(a).lower() for w in words)]
    return hits[:limit], len(hits)


def groups() -> dict[str, int]:
    counts: dict[str, int] = {}
    for a in _load():
        counts[a.group] = counts.get(a.group, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def build_catalog(out: Path) -> dict[str, int]:
    """Rebuild catalog.tsv from the live Hugging Face listing (needs network)."""
    from huggingface_hub import HfApi

    names = sorted(e.path for e in HfApi().list_repo_tree(REPO, repo_type="dataset")
                   if "/" not in e.path and e.path not in (".gitattributes", "README.md"))
    rows = [Asset(n, categorize(n), n.split("_")[0]) for n in names]
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("asset\tgroup\tprefix\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.group] = counts.get(r.group, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
