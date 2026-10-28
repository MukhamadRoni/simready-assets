import json
import struct

import pytest
from PIL import Image
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, Vt

from simready_assets.convert import ConvertResult, convert


def _material(stage, path, color=None, tex=None):
    mat = UsdShade.Material.Define(stage, path)
    ps = UsdShade.Shader.Define(stage, f"{path}/PS")
    ps.CreateIdAttr("UsdPreviewSurface")
    out = ps.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    mat.CreateSurfaceOutput().ConnectToSource(out)
    dc = ps.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f)
    if tex:
        t = UsdShade.Shader.Define(stage, f"{path}/Tex")
        t.CreateIdAttr("UsdUVTexture")
        t.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(tex))
        rgb = t.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
        dc.ConnectToSource(rgb)
    else:
        dc.Set(Gf.Vec3f(*(color or (1, 0, 0))))
    return mat


def make_stage(tmp_path):
    Image.new("RGB", (4, 4), (10, 200, 30)).save(tmp_path / "t.png")
    stage = Usd.Stage.CreateNew(str(tmp_path / "a.usda"))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    root = UsdGeom.Xform.Define(stage, "/Root")
    stage.SetDefaultPrim(root.GetPrim())
    mesh = UsdGeom.Mesh.Define(stage, "/Proto/Mesh")
    mesh.CreatePointsAttr([(0, 0, 0), (1, 0, 0), (1, 0, 2), (0, 0, 2), (2, 0, 0), (2, 0, 2)])
    mesh.CreateFaceVertexCountsAttr([4, 4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3, 1, 4, 5, 2])
    pv = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying)
    pv.Set(Vt.Vec2fArray([(0, 0), (1, 0), (1, 1), (0, 1)] * 2))
    ma = _material(stage, "/Root/Looks/A", color=(1, 0, 0))
    mb = _material(stage, "/Root/Looks/B", tex="./t.png")
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(ma)
    sub = UsdGeom.Subset.CreateGeomSubset(
        mesh, "sub", UsdGeom.Tokens.face, Vt.IntArray([1]), "materialBind")
    UsdShade.MaterialBindingAPI.Apply(sub.GetPrim()).Bind(mb)
    geo = UsdGeom.Xform.Define(stage, "/Root/Geo")
    geo.GetPrim().GetReferences().AddInternalReference("/Proto")
    geo.GetPrim().SetInstanceable(True)
    stage.GetRootLayer().Save()
    return tmp_path / "a.usda"


def read_glb(path):
    data = open(path, "rb").read()
    n = struct.unpack("<I", data[12:16])[0]
    g = json.loads(data[20:20 + n])
    return g, data[20 + n + 8:]


def test_convert_bakes_units_axis_subsets_and_textures(tmp_path):
    usd = make_stage(tmp_path)
    r = convert(usd, tmp_path / "o.glb", max_tex=2, jpeg=True)
    assert isinstance(r, ConvertResult)
    g, _ = read_glb(r.path)
    assert open(r.path, "rb").read(4) == b"glTF"
    assert r.triangles == 4 and r.materials == 2 and r.textures == 1
    assert max(r.dims_m) == pytest.approx(0.02)
    assert r.dims_m[1] > 0
    assert any("baseColorTexture" in m["pbrMetallicRoughness"] for m in g["materials"])
