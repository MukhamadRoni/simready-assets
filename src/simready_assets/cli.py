"""simready command line interface."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import catalog, hub


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _not_found(name: str) -> None:
    _err(f"!! {name}: not found. Try: simready find <word>")


def cmd_find(a) -> int:
    rows, total = catalog.search(" ".join(a.words), a.group, a.limit)
    for r in rows:
        print(f"{r.name}\t{r.group}")
    print(f"-- {total} match(es)")
    return 0


def cmd_groups(a) -> int:
    for g, n in catalog.groups().items():
        print(f"{g}\t{n}")
    return 0


def cmd_info(a) -> int:
    dest = Path(a.dest) if a.dest else hub.default_dir()
    plan = hub.plan_download([a.name], a.profile)
    if a.name in plan.missing:
        _not_found(a.name)
        return 1
    print(f"{a.name}: profile {a.profile}, {_mb(plan.total_bytes)}, {len(plan.files)} file(s)")
    roots = [f for f in plan.files if f.count("/") == 2 and f.split("/")[1] == "simready_usd"
             and f.rsplit(".", 1)[-1] in ("usd", "usda", "usdc")]
    if roots:
        print(f"root USD: {roots[0]}")
    local = dest / a.name
    print(f"local: {local} ({'present' if local.exists() else 'not downloaded'})")
    return 0


def cmd_download(a) -> int:
    names = list(a.names)
    if a.from_file:
        text = Path(a.from_file).read_text(encoding="utf-8")
        names += [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
    if not names:
        _err("no asset names given")
        return 2
    dest = Path(a.dest) if a.dest else hub.default_dir()
    plan = hub.plan_download(names, a.profile)
    for m in plan.missing:
        _not_found(m)
    if not plan.sizes:
        return 1
    for n, s in plan.sizes.items():
        print(f"{n}\t{_mb(s)}")
    print(f"-- total {_mb(plan.total_bytes)} ({a.profile})")
    if plan.total_bytes > a.max_total_mb * 1024 * 1024:
        print(f"over --max-total-mb {a.max_total_mb}; nothing downloaded")
        return 1
    if a.dry_run:
        return 0
    warn = hub.long_path_warning(dest)
    if warn:
        print(warn)
    for n, p in hub.download(plan, dest).items():
        print(f"{n}\t{p if p else dest / n}")
    return 0


def cmd_convert(a) -> int:
    from . import convert as conv

    dest = Path(a.dest) if a.dest else hub.default_dir()
    target = Path(a.target)
    if not target.exists():
        target = dest / a.target
    try:
        if not target.exists():
            hub.root_usd(target)  # raises with the download hint
        r = conv.convert(target, Path(a.output) if a.output else None, a.max_tex, a.jpeg)
    except (FileNotFoundError, ValueError) as e:
        _err(f"error: {e}")
        return 2
    print(f"{r.path}  {r.size_mb:.2f} MB  meshes={r.meshes} tris={r.triangles} "
          f"materials={r.materials} textures={r.textures} dims_m={r.dims_m}")
    return 0


def cmd_build_catalog(a) -> int:
    out = Path(a.out) if a.out else Path(catalog.__file__).with_name("catalog.tsv")
    for g, n in catalog.build_catalog(out).items():
        print(f"{g}\t{n}")
    print(f"wrote {out}")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="simready", description="NVIDIA SimReady assets")
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("find"); s.add_argument("words", nargs="*")
    s.add_argument("--group"); s.add_argument("--limit", type=int, default=50); s.set_defaults(fn=cmd_find)
    sp.add_parser("groups").set_defaults(fn=cmd_groups)
    s = sp.add_parser("info"); s.add_argument("name")
    s.add_argument("--profile", choices=list(hub.PROFILES), default="web"); s.add_argument("--dest")
    s.set_defaults(fn=cmd_info)
    s = sp.add_parser("download"); s.add_argument("names", nargs="*")
    s.add_argument("--from-file"); s.add_argument("--profile", choices=list(hub.PROFILES), default="web")
    s.add_argument("--dest"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--max-total-mb", type=float, default=1024); s.set_defaults(fn=cmd_download)
    s = sp.add_parser("convert"); s.add_argument("target")
    s.add_argument("-o", "--output"); s.add_argument("--max-tex", type=int)
    s.add_argument("--jpeg", action="store_true"); s.add_argument("--dest"); s.set_defaults(fn=cmd_convert)
    s = sp.add_parser("build-catalog"); s.add_argument("--out"); s.set_defaults(fn=cmd_build_catalog)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
