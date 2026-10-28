"""Convert a SimReady USD asset into a single self-contained .glb for web 3D (three.js etc.).

SimReady materials carry both an MDL (OmniPBR) network and a UsdPreviewSurface fallback.
Generic converters crash on that layout, so this reads only the UsdPreviewSurface network,
which maps onto glTF PBR (albedo -> baseColor, ORM -> occlusion + metallicRoughness,
normal -> normalTexture). Physics (colliders, joints, mass) is NOT carried over.
"""
from __future__ import annotations

import io
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom, UsdShade

from . import hub

try:
    from PIL import Image
except ImportError:  # textures are then embedded untouched
    Image = None


@dataclass
class ConvertResult:
    path: Path
    meshes: int
    triangles: int
    materials: int
    textures: int
    size_mb: float
    dims_m: tuple[float, float, float]


# ---------------------------------------------------------------- materials

def _source(shader_input):
    """Return (shader, output_name) connected to an input, or (None, None)."""
    if not shader_input or not shader_input.HasConnectedSource():
        return None, None
    src = shader_input.GetConnectedSource()
    if not src:
        return None, None
    return UsdShade.Shader(src[0].GetPrim()), src[1]


def _preview_surface(material):
    out = material.GetSurfaceOutput()  # universal render context = UsdPreviewSurface
    shader, _ = _source(out)
    if shader and shader.GetIdAttr().Get() == "UsdPreviewSurface":
        return shader
    for child in Usd.PrimRange(material.GetPrim()):  # fallback: any preview surface inside
        s = UsdShade.Shader(child)
        if s and s.GetIdAttr().Get() == "UsdPreviewSurface":
            return s
    return None


def _texture_info(tex_shader):
    """file path + uv transform (scale, rotation, translation) feeding a UsdUVTexture."""
    f = tex_shader.GetInput("file")
    path = None
    if f and f.Get() is not None:
        path = f.Get().resolvedPath or None
    xf = None
    st_src, _ = _source(tex_shader.GetInput("st"))
    if st_src and st_src.GetIdAttr().Get() == "UsdTransform2d":
        def val(n, d):
            i = st_src.GetInput(n)
            v = i.Get() if i else None
            return d if v is None else v
        xf = (tuple(val("scale", (1, 1))), float(val("rotation", 0.0)), tuple(val("translation", (0, 0))))
    return path, xf


class GlbBuilder:
    def __init__(self, max_tex=None, jpeg=False):
        self.max_tex, self.jpeg = max_tex, jpeg
        self.bin = bytearray()
        self.gltf = {"asset": {"version": "2.0", "generator": "simready-assets convert.py"},
                     "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
                     "materials": [], "accessors": [], "bufferViews": [], "buffers": [],
                     "images": [], "textures": [], "samplers": [{"wrapS": 10497, "wrapT": 10497,
                                                                 "magFilter": 9729, "minFilter": 9987}]}
        self.mat_cache, self.mat_sig, self.img_cache = {}, {}, {}

    def _view(self, data, target=None):
        while len(self.bin) % 4:
            self.bin += b"\0"
        view = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            view["target"] = target
        self.bin += data
        self.gltf["bufferViews"].append(view)
        return len(self.gltf["bufferViews"]) - 1

    def accessor(self, arr, kind, target):
        arr = np.ascontiguousarray(arr)
        comp = {np.float32: 5126, np.uint32: 5125}[arr.dtype.type]
        acc = {"bufferView": self._view(arr.tobytes(), target), "componentType": comp,
               "count": int(arr.shape[0]), "type": kind}
        if kind == "VEC3" and arr.dtype == np.float32:
            acc["min"], acc["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        self.gltf["accessors"].append(acc)
        return len(self.gltf["accessors"]) - 1

    def image(self, path, is_color):
        if not path or not os.path.exists(path):
            return None
        key = (path, is_color)
        if key in self.img_cache:
            return self.img_cache[key]
        with open(path, "rb") as f:
            data = f.read()
        mime = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
        if Image and (self.max_tex or self.jpeg or mime == "image/png" and not path.lower().endswith(".png")):
            im = Image.open(io.BytesIO(data))
            if self.max_tex and max(im.size) > self.max_tex:
                im.thumbnail((self.max_tex, self.max_tex), Image.LANCZOS)
            buf = io.BytesIO()
            # JPEG has no alpha; keep PNG when the image actually uses transparency
            if self.jpeg and not (im.mode in ("RGBA", "LA") and im.getextrema()[-1][0] < 255):
                im.convert("RGB").save(buf, "JPEG", quality=88)
                mime = "image/jpeg"
            else:
                im.save(buf, "PNG", optimize=True)
                mime = "image/png"
            data = buf.getvalue()
        self.gltf["images"].append({"bufferView": self._view(data), "mimeType": mime})
        self.gltf["textures"].append({"sampler": 0, "source": len(self.gltf["images"]) - 1})
        idx = len(self.gltf["textures"]) - 1
        self.img_cache[key] = idx
        return idx

    def material(self, material):
        """Returns (gltf material index, uv transform to bake or None)."""
        key = str(material.GetPath()) if material else None
        if key in self.mat_cache:
            return self.mat_cache[key]
        m = {"name": material.GetPrim().GetName() if material else "default",
             "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1], "metallicFactor": 0.0,
                                      "roughnessFactor": 0.5}}
        uv_xf = None
        ps = _preview_surface(material) if material else None
        if ps:
            pbr = m["pbrMetallicRoughness"]

            def inp(name):
                return ps.GetInput(name)

            src, _ = _source(inp("diffuseColor"))
            if src and src.GetIdAttr().Get() == "UsdUVTexture":
                path, uv_xf = _texture_info(src)
                t = self.image(path, True)
                if t is not None:
                    pbr["baseColorTexture"] = {"index": t}
                    pbr["baseColorFactor"] = [1, 1, 1, 1]
            elif inp("diffuseColor") and inp("diffuseColor").Get() is not None:
                pbr["baseColorFactor"] = list(inp("diffuseColor").Get()) + [1]

            # SimReady packs Occlusion/Roughness/Metallic into one ORM texture (R/G/B),
            # which is exactly glTF's layout, so one texture serves both slots.
            orm_path = None
            for name in ("metallic", "roughness"):
                src, _ = _source(inp(name))
                if src and src.GetIdAttr().Get() == "UsdUVTexture":
                    orm_path = orm_path or _texture_info(src)[0]
                elif inp(name) and inp(name).Get() is not None:
                    pbr[name + "Factor"] = float(inp(name).Get())
            if orm_path:
                t = self.image(orm_path, False)
                if t is not None:
                    pbr["metallicRoughnessTexture"] = {"index": t}
                    pbr["metallicFactor"] = pbr["roughnessFactor"] = 1.0
                    if "orm" in os.path.basename(orm_path).lower():
                        m["occlusionTexture"] = {"index": t}

            src, _ = _source(inp("normal"))
            if src and src.GetIdAttr().Get() == "UsdUVTexture":
                t = self.image(_texture_info(src)[0], False)
                if t is not None:
                    m["normalTexture"] = {"index": t}

            src, _ = _source(inp("emissiveColor"))
            if src and src.GetIdAttr().Get() == "UsdUVTexture":
                t = self.image(_texture_info(src)[0], True)
                if t is not None:
                    m["emissiveTexture"] = {"index": t}
                    m["emissiveFactor"] = [1, 1, 1]
            elif inp("emissiveColor") and inp("emissiveColor").Get() is not None:
                e = list(inp("emissiveColor").Get())
                if any(e):
                    m["emissiveFactor"] = e

            op = inp("opacity")
            src, out = _source(op)
            if src and src.GetIdAttr().Get() == "UsdUVTexture":
                m["alphaMode"] = "BLEND"
            elif op and op.Get() is not None and op.Get() < 0.999:
                pbr["baseColorFactor"][3] = float(op.Get())
                m["alphaMode"] = "BLEND"
            if "transparent" in m["name"].lower() or "glass" in m["name"].lower():
                m.setdefault("alphaMode", "BLEND")
                if pbr["baseColorFactor"][3] >= 0.999:
                    pbr["baseColorFactor"][3] = 0.35
                m["doubleSided"] = True

        # instanced prims each carry their own copy of a material; share identical ones
        sig = json.dumps(m, sort_keys=True)
        if sig not in self.mat_sig:
            self.gltf["materials"].append(m)
            self.mat_sig[sig] = len(self.gltf["materials"]) - 1
        result = (self.mat_sig[sig], uv_xf)
        self.mat_cache[key] = result
        return result

    def write(self, out_path):
        while len(self.bin) % 4:
            self.bin += b"\0"
        self.gltf["buffers"] = [{"byteLength": len(self.bin)}]
        for k in ("images", "textures", "materials"):
            if not self.gltf[k]:
                del self.gltf[k]
        if "textures" not in self.gltf:
            del self.gltf["samplers"]
        js = json.dumps(self.gltf, separators=(",", ":")).encode()
        js += b" " * ((4 - len(js) % 4) % 4)
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(out_path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
            f.write(struct.pack("<II", len(self.bin), 0x004E4942) + self.bin)


# ---------------------------------------------------------------- geometry

def _primvar_per_corner(pv, indices, n_corners):
    """Expand a primvar to one value per face-vertex corner; None if unsupported."""
    if not pv or not pv.HasValue():
        return None
    vals = np.asarray(pv.ComputeFlattened())
    interp = pv.GetInterpolation()
    if interp == UsdGeom.Tokens.faceVarying and len(vals) == n_corners:
        return vals
    if interp in (UsdGeom.Tokens.vertex, UsdGeom.Tokens.varying):
        return vals[indices]
    if interp == UsdGeom.Tokens.constant:
        return np.repeat(vals.reshape(1, -1), n_corners, 0)
    return None


def _apply_uv_xf(uv, xf):
    if not xf:
        return uv
    (sx, sy), rot, (tx, ty) = xf
    if (sx, sy, rot, tx, ty) == (1, 1, 0, 0, 0):
        return uv
    r = np.radians(rot)
    c, s = np.cos(r), np.sin(r)
    u, v = uv[:, 0] * sx, uv[:, 1] * sy
    return np.stack([u * c - v * s + tx, u * s + v * c + ty], 1)


def convert(src: Path, out: Path | None = None, max_tex: int | None = None,
            jpeg: bool = False) -> ConvertResult:
    """Convert an asset folder or root USD file to a GLB. Default out: <asset_dir>/<asset>.glb."""
    src = Path(src)
    if src.is_dir():
        usd_path, asset_dir = hub.root_usd(src), src
    else:
        usd_path = src
        asset_dir = src.parent.parent if src.parent.name == "simready_usd" else src.parent
    out = Path(out) if out else asset_dir / f"{asset_dir.name}.glb"
    stage = Usd.Stage.Open(str(usd_path))
    if not stage:
        raise ValueError(f"Cannot open USD: {usd_path}")
    root = stage.GetDefaultPrim() or stage.GetPseudoRoot()
    meters = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
    # Z-up -> Y-up is a -90 deg rotation about X: (x, y, z) -> (x, z, -y)
    zup = UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z
    b = GlbBuilder(max_tex, jpeg)
    cache = UsdGeom.XformCache()
    tri_total = 0

    for prim in Usd.PrimRange(root, Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        img = UsdGeom.Imageable(prim)
        if img.ComputeVisibility() == UsdGeom.Tokens.invisible:
            continue
        if img.ComputePurpose() not in (UsdGeom.Tokens.default_, UsdGeom.Tokens.render):
            continue  # skip proxy/guide meshes (collision helpers)
        mesh = UsdGeom.Mesh(prim)
        pts = mesh.GetPointsAttr().Get()
        counts = mesh.GetFaceVertexCountsAttr().Get()
        idx = mesh.GetFaceVertexIndicesAttr().Get()
        if not pts or not counts or not idx:
            continue
        pts = np.asarray(pts, dtype=np.float64)
        counts = np.asarray(counts)
        idx = np.asarray(idx)
        n_corners = len(idx)

        xf = np.array(cache.GetLocalToWorldTransform(prim), dtype=np.float64)  # row-vector convention
        P = np.c_[pts, np.ones(len(pts))] @ xf
        P = P[:, :3] * meters
        normal_xf = np.linalg.inv(xf[:3, :3]).T

        pvapi = UsdGeom.PrimvarsAPI(prim)
        N = None
        npv = pvapi.GetPrimvar("normals")
        if npv and npv.HasValue():
            N = _primvar_per_corner(npv, idx, n_corners)
        elif mesh.GetNormalsAttr().HasValue():
            raw = np.asarray(mesh.GetNormalsAttr().Get())
            interp = mesh.GetNormalsInterpolation()
            N = raw if interp == UsdGeom.Tokens.faceVarying and len(raw) == n_corners else (
                raw[idx] if len(raw) == len(pts) else None)
        st = None
        for name in ("st", "st0", "UVMap", "uv"):
            pv = pvapi.GetPrimvar(name)
            if pv and pv.HasValue():
                st = _primvar_per_corner(pv, idx, n_corners)
                break

        # one corner-indexed vertex per face-vertex, triangulated as a fan
        face_start = np.r_[0, np.cumsum(counts)[:-1]]
        left_handed = mesh.GetOrientationAttr().Get() == UsdGeom.Tokens.leftHanded
        if np.linalg.det(xf[:3, :3]) < 0:
            left_handed = not left_handed
        tri_face, tri_corner = [], []
        for k in range(1, counts.max() - 1):
            faces = np.nonzero(counts > k + 1)[0]
            a = face_start[faces]
            c1, c2 = a + k, a + k + 1
            if left_handed:
                c1, c2 = c2, c1
            tri_face.append(faces)
            tri_corner.append(np.stack([a, c1, c2], 1))
        if not tri_face:
            continue
        tri_face = np.concatenate(tri_face)
        tri_corner = np.concatenate(tri_corner)

        pos_c = P[idx]
        if N is None:  # flat normals per face
            v0, v1, v2 = (pos_c[tri_corner[:, i]] for i in range(3))
            fn = np.cross(v1 - v0, v2 - v0)
            N = np.zeros_like(pos_c)
            for i in range(3):
                N[tri_corner[:, i]] = fn
        else:
            N = np.asarray(N, dtype=np.float64) @ normal_xf.T
            if left_handed and mesh.GetOrientationAttr().Get() == UsdGeom.Tokens.leftHanded:
                N = -N
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)

        if zup:
            pos_c = np.c_[pos_c[:, 0], pos_c[:, 2], -pos_c[:, 1]]
            N = np.c_[N[:, 0], N[:, 2], -N[:, 1]]

        # material per face (GeomSubsets) or one bound material
        binding = UsdShade.MaterialBindingAPI(prim)
        groups = []
        subsets = UsdGeom.Subset.GetGeomSubsets(mesh, UsdGeom.Tokens.face, "materialBind")
        covered = np.zeros(len(counts), bool)
        for ss in subsets:
            faces = np.asarray(ss.GetIndicesAttr().Get() or [], dtype=np.int64)
            covered[faces] = True
            mat = UsdShade.MaterialBindingAPI(ss.GetPrim()).ComputeBoundMaterial()[0]
            groups.append((faces, mat))
        rest = np.nonzero(~covered)[0]
        if len(rest):
            groups.append((rest, binding.ComputeBoundMaterial()[0]))

        prims = []
        face_mask_lookup = np.zeros(len(counts), np.int64)
        for gi, (faces, _) in enumerate(groups):
            face_mask_lookup[faces] = gi
        tri_group = face_mask_lookup[tri_face]
        for gi, (faces, mat) in enumerate(groups):
            tris = tri_corner[tri_group == gi]
            if not len(tris):
                continue
            mat_idx, uv_xf = b.material(mat)
            used = np.unique(tris)
            remap = np.full(n_corners, -1, np.int64)
            cols = [pos_c[used], N[used]]
            uv = None
            if st is not None:
                uv = _apply_uv_xf(np.asarray(st, dtype=np.float64)[used], uv_xf)
                uv = np.c_[uv[:, 0], 1.0 - uv[:, 1]]  # USD v-up -> glTF v-down
                cols.append(uv)
            # weld identical corners to keep vertex count low
            stacked = np.round(np.concatenate(cols, 1), 6)
            uniq, first, inv = np.unique(stacked, axis=0, return_index=True, return_inverse=True)
            remap[used] = inv.reshape(-1)
            attrs = {
                "POSITION": b.accessor(pos_c[used][first].astype(np.float32), "VEC3", 34962),
                "NORMAL": b.accessor(N[used][first].astype(np.float32), "VEC3", 34962),
            }
            if uv is not None:
                attrs["TEXCOORD_0"] = b.accessor(uv[first].astype(np.float32), "VEC2", 34962)
            ind = b.accessor(remap[tris].reshape(-1).astype(np.uint32), "SCALAR", 34963)
            prims.append({"attributes": attrs, "indices": ind, "material": mat_idx})
            tri_total += len(tris)
        if prims:
            b.gltf["meshes"].append({"name": prim.GetName(), "primitives": prims})
            b.gltf["nodes"].append({"name": str(prim.GetPath()), "mesh": len(b.gltf["meshes"]) - 1})
            b.gltf["scenes"][0]["nodes"].append(len(b.gltf["nodes"]) - 1)

    if not b.gltf["meshes"]:
        raise ValueError(f"No renderable meshes found in {usd_path}")
    out.parent.mkdir(parents=True, exist_ok=True)
    b.write(out)
    pos = [b.gltf["accessors"][p["attributes"]["POSITION"]] for m in b.gltf["meshes"] for p in m["primitives"]]
    mins, maxs = np.min([a["min"] for a in pos], 0), np.max([a["max"] for a in pos], 0)
    dims = tuple(float(x) for x in (maxs - mins))
    return ConvertResult(
        path=out, meshes=len(b.gltf["meshes"]), triangles=tri_total,
        materials=len(b.gltf.get("materials", [])), textures=len(b.gltf.get("images", [])),
        size_mb=os.path.getsize(out) / 1e6, dims_m=dims)
