#! python 3
"""
For unbent parts: pick a planar face lying on World XY at Z0.
Outer boundary -> outside layer, holes -> inside layer, part luid as text curves
(area centroid) -> mark layer. All grouped per face. Part is left untouched. Repeats until Esc.
Requires Rhino 8, Python 3.
"""

import System
import System.Drawing
import Rhino
import scriptcontext as sc
from Rhino import RhinoMath, UnitSystem
from Rhino.Geometry import BrepLoopType, Plane, Vector3d, AreaMassProperties, TextEntity
from Rhino.Input.Custom import GetObject
from Rhino.Input import GetResult
from Rhino.DocObjects import (ObjectType, ObjectAttributes, DimensionStyle, Font,
                              TextHorizontalAlignment, TextVerticalAlignment)

OUTSIDE_LAYER  = "06 - 2D Geo::Outside cut"   # configurable
INSIDE_LAYER   = "06 - 2D Geo::Inside cut"    # configurable
MARK_LAYER     = "06 - 2D Geo::Mark"          # configurable
TEXT_FONT      = "MecSoft_Font 1"             # configurable
LUID_HEIGHT_IN = 1                            # configurable


def log(msg):
    Rhino.RhinoApp.WriteLine("FabFlat: " + msg)


def find_font(target):
    """Installed font matching target (case, _/space ignored); else any MecSoft font; else None."""
    t = target.lower().replace("_", " ")
    fallback = None
    for f in System.Drawing.FontFamily.Families:
        n = f.Name.lower().replace("_", " ")
        if n == t:
            return f.Name
        if fallback is None and "mecsoft" in n:
            fallback = f.Name
    return fallback


def layer_index(doc, path):
    """Index of layer, or -1 (with message) if missing / hidden / locked, incl. parents."""
    idx = doc.Layers.FindByFullPath(path, -1)
    if idx < 0:
        log('Layer "{}" not found. Aborting.'.format(path))
        return -1
    lyr = doc.Layers[idx]
    while lyr is not None:
        if not lyr.IsVisible or lyr.IsLocked:
            log('Layer "{}" (or a parent) is hidden or locked. Aborting.'.format(path))
            return -1
        if lyr.ParentLayerId == System.Guid.Empty:
            break
        lyr = doc.Layers.FindId(lyr.ParentLayerId)
    return idx


def check_face(face, tol):
    """None if face is planar and lies on World XY at Z0, else a reason string."""
    ok, pl = face.TryGetPlane(tol)
    if not ok:
        return "Face is not planar."
    if abs(abs(pl.Normal.Z) - 1.0) > 1e-6:
        return "Face is not parallel to World XY. Run FabOrient first."
    fb = face.DuplicateFace(False)
    if any(abs(v.Location.Z) > tol * 10 for v in fb.Vertices) or abs(pl.OriginZ) > tol * 10:
        return "Face is not at Z0. Run FabOrient first."
    return None


def main():
    doc = sc.doc
    tol = doc.ModelAbsoluteTolerance

    font_name = find_font(TEXT_FONT)
    if font_name is None:
        log('No MecSoft font installed ("{}"). Install RhinoCAM/VisualCAM fonts. Aborting.'.format(TEXT_FONT))
        return

    out_idx = layer_index(doc, OUTSIDE_LAYER)
    in_idx = layer_index(doc, INSIDE_LAYER)
    mark_idx = layer_index(doc, MARK_LAYER)
    if min(out_idx, in_idx, mark_idx) < 0:
        return

    u = RhinoMath.UnitScale(UnitSystem.Inches, doc.ModelUnitSystem)
    ds = DimensionStyle()
    ds.Font = Font(font_name)
    ds.TextHeight = LUID_HEIGHT_IN * u
    ds.TextHorizontalAlignment = TextHorizontalAlignment.Center
    ds.TextVerticalAlignment = TextVerticalAlignment.Middle

    def attrs(idx):
        at = ObjectAttributes()
        at.LayerIndex = idx
        return at

    while True:
        go = GetObject()
        go.SetCommandPrompt("Select flat face at Z0")
        go.GeometryFilter = ObjectType.Surface  # solids, polysurfaces, surfaces, extrusions
        go.SubObjectSelect = True
        go.EnablePreSelect(False, True)
        if go.Get() != GetResult.Object:
            break
        ref = go.Object(0)
        doc.Objects.UnselectAll()

        face = ref.Face()
        if face is None:
            log("Pick a face.")
            continue
        err = check_face(face, tol)
        if err:
            log(err)
            continue

        ids = []
        for loop in face.Loops:
            crv = loop.To3dCurve()  # joined loop = DupBorder result for this face
            if crv is None:
                continue
            ids.append(doc.Objects.AddCurve(crv, attrs(out_idx if loop.LoopType == BrepLoopType.Outer else in_idx)))

        # Part luid as text curves at the face's area centroid.
        luid = ref.Object().Attributes.GetUserString("luid")  # same key stamp_luid writes
        if not luid:
            log("Part has no luid; luid text skipped.")
        else:
            amp = AreaMassProperties.Compute(face.DuplicateFace(False))
            if amp:
                c = amp.Centroid
                pl = Plane(c, Vector3d.XAxis, Vector3d.YAxis)
                te = TextEntity.Create(luid, pl, ds, False, 0.0, 0.0)
                crvs = te.CreateCurves(ds, True, 0.0, 0.0) if te else None  # allowOpen: single-stroke font
                if crvs:
                    for crv in crvs:
                        ids.append(doc.Objects.AddCurve(crv, attrs(mark_idx)))
                else:
                    log("Could not convert luid to curves.")

        ids = [i for i in ids if i != System.Guid.Empty]
        if len(ids) > 1:
            doc.Groups.Add(ids)
        log("{} curve(s) added.".format(len(ids)))
        doc.Views.Redraw()


if __name__ == "__main__":
    main()
