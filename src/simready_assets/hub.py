"""Per-asset Hugging Face listing and download (never snapshot_download)."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NamedTuple

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.errors import HfHubHTTPError

try:  # names vary across huggingface_hub versions
    from huggingface_hub.errors import EntryNotFoundError
except ImportError:  # pragma: no cover
    EntryNotFoundError = None
try:
    from huggingface_hub.errors import RemoteEntryNotFoundError
except ImportError:  # pragma: no cover
    RemoteEntryNotFoundError = None
from huggingface_hub.errors import RepositoryNotFoundError

REPO = "nvidia/simready-assets"

PROFILES: dict[str, tuple[list[str], list[str]]] = {
    # keep folder layout intact: the root .usd references payloads/ and Textures/ by relative path
    "sim": (["{a}/**"], ["{a}/simready_usd/.thumbs/256x256/*"]),
    "web": (["{a}/simready_usd/*.usd*", "{a}/simready_usd/payloads/**", "{a}/simready_usd/Textures/**",
             "{a}/.metadata/*", "{a}/com.nvidia.simready.packaging.json"], []),
    "thumb": (["{a}/simready_usd/.thumbs/*_thumbnail.png"], []),
}

_NOT_FOUND = tuple(e for e in (EntryNotFoundError, RemoteEntryNotFoundError, RepositoryNotFoundError) if e)


class AssetNotFound(Exception):
    pass


class RemoteFile(NamedTuple):
    path: str
    size: int


def matches(path: str, asset: str, profile: str) -> bool:
    inc, exc = PROFILES[profile]
    ok = any(fnmatch.fnmatch(path, p.format(a=asset)) for p in inc)
    return ok and not any(fnmatch.fnmatch(path, p.format(a=asset)) for p in exc)


_NAME_RE = re.compile(r"^[A-Za-z0-9][\w.-]*$")


def valid_name(asset: str) -> bool:
    return bool(_NAME_RE.fullmatch(asset))


def _is_404(e: Exception) -> bool:
    resp = getattr(e, "response", None)
    return isinstance(e, HfHubHTTPError) and getattr(resp, "status_code", None) == 404


def list_files(asset: str) -> list[RemoteFile]:
    """One recursive listing for a single asset folder."""
    if not valid_name(asset):
        raise AssetNotFound(asset)
    try:
        items = list(HfApi().list_repo_tree(REPO, repo_type="dataset", path_in_repo=asset, recursive=True))
    except _NOT_FOUND as e:
        raise AssetNotFound(asset) from e
    except HfHubHTTPError as e:
        if _is_404(e):
            raise AssetNotFound(asset) from e
        raise
    files = [RemoteFile(f.path, f.size) for f in items if getattr(f, "size", None) is not None]
    if not files:
        raise AssetNotFound(asset)
    return files


@dataclass
class DownloadPlan:
    profile: str
    sizes: dict[str, int]
    files: list[str]
    missing: list[str]

    @property
    def total_bytes(self) -> int:
        return sum(self.sizes.values())


def plan_download(assets: list[str], profile: str) -> DownloadPlan:
    sizes: dict[str, int] = {}
    files: list[str] = []
    missing: list[str] = []
    for asset in assets:
        try:
            listing = list_files(asset)
        except AssetNotFound:
            missing.append(asset)
            continue
        picked = [f for f in listing if matches(f.path, asset, profile)]
        files += [f.path for f in picked]
        sizes[asset] = sum(f.size for f in picked)
    return DownloadPlan(profile, sizes, files, missing)


def root_usd(asset_dir: Path) -> Path:
    asset_dir = Path(asset_dir)
    sr = asset_dir / "simready_usd"
    meta = asset_dir / ".metadata" / "com.nvidia.simready.root_usds.json"
    if meta.is_file():
        try:
            for n in json.loads(meta.read_text(encoding="utf-8"))["entries"]:
                cand = asset_dir / n
                if cand.is_file():
                    return cand
        except (ValueError, KeyError, TypeError, OSError):
            pass
    if sr.is_dir():
        roots = sorted(p for p in sr.iterdir() if p.is_file() and p.suffix in (".usd", ".usda", ".usdc"))
        if roots:
            return roots[0]
    raise FileNotFoundError(f"No USD in {asset_dir}. Download it with profile 'web' or 'sim' first.")


def default_dir() -> Path:
    return Path(os.path.expandvars(os.environ.get("SIMREADY_DIR") or "~/simready")).expanduser()


def is_downloaded(asset_dir: Path) -> bool:
    """True only if a root USD is present (a thumbnail-only folder does not count)."""
    try:
        root_usd(asset_dir)
        return True
    except FileNotFoundError:
        return False


def resolve_target(name_or_path: str, dest: Path) -> Path:
    """Bare name -> <dest>/<name> first, then as a path; paths are used as given.
    Raises FileNotFoundError('... not found at <path>') if nothing exists, and (via root_usd) the
    profile hint if an asset folder exists but holds no USD."""
    raw = Path(name_or_path)
    if "/" not in name_or_path and "\\" not in name_or_path:
        cand = Path(dest) / name_or_path
        target = cand if cand.exists() or not raw.exists() else raw
    else:
        target = raw
    if not target.exists():
        raise FileNotFoundError(f"{name_or_path}: not found at {target}. "
                                f"Download it first (simready download / download_assets).")
    if target.is_dir():
        root_usd(target)
    return target


def long_path_warning(dest: Path) -> str | None:
    n = len(os.path.abspath(dest))
    if os.name == "nt" and n > 80:
        return (f"The download folder (SIMREADY_DIR / --dest) is a long path ({n} chars); on Windows this can fail with FileNotFoundError "
                f"(Hugging Face temp files overflow the 260-char limit). Prefer a short folder such as C:/simready.")
    return None


def _asset_of(path: str) -> str:
    return path.split("/", 1)[0]


def download(plan: DownloadPlan, dest: Path, workers: int = 8,
             on_file: Callable[[int, int], None] | None = None) -> dict[str, Path | None]:
    """Download every file in the plan; completed files are skipped on a retry (resume).
    on_file(done, total) is called from worker threads after each file."""
    dest = Path(dest)
    total = len(plan.files)
    lock = threading.Lock()
    state = {"done": 0}

    def fetch(path: str):
        r = hf_hub_download(REPO, path, repo_type="dataset", local_dir=dest)
        if on_file is not None:
            with lock:
                state["done"] += 1
                n = state["done"]
                try:
                    on_file(n, total)
                except Exception:  # progress is best-effort
                    pass
        return r

    if plan.files:
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(fetch, plan.files))
    out: dict[str, Path | None] = {}
    for asset in plan.sizes:
        out[asset] = None if plan.profile == "thumb" else root_usd(dest / asset)
    return out


def thumbnail(asset: str, dest: Path) -> Path:
    if not valid_name(asset):
        raise AssetNotFound(asset)
    paths = [f.path for f in list_files(asset)
             if f.path.endswith("_thumbnail.png") and "_dark" not in f.path.rsplit("/", 1)[-1]
             and matches(f.path, asset, "thumb")]
    if not paths:
        raise AssetNotFound(asset)
    return Path(hf_hub_download(REPO, paths[0], repo_type="dataset", local_dir=Path(dest)))
