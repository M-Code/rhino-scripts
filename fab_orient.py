#! python 3
"""
Copy a bent part to the fab layer with the selected face on World XY at Z0,
face normal +Z (material below that face), longest outer edge along +X.
Original is turned red. Repeats until Esc.
Requires Rhino 8, Python 3.
"""

import System
import Rhino
import scriptcontext as sc
from Rhino.Geometry import (Point3d, Vector3d, Plane, Transform,
                            AreaMassProperties, BrepSolidOrientation, BrepTrimType)
from Rhino.Input.Custom import GetObject, GetPoint
from Rhino.Input import GetResult, RhinoGet
from Rhino.DocObjects import ObjectType, ObjectColorSource
from Rhino.Commands import Result

FAB_LAYER   = "05 - Fab 3D"                            # configurable: full layer path; sublayer = "Parent::Fab 3D"
RED         = System.Drawing.Color.FromArgb(255, 0, 0)  # configurable: "processed" color on original
INK_LAYER   = "07 - Ink Lines"                          # configurable: mark curves drawn on the 3D part (exact layer, no sublayers)
MARK_LAYER  = "06 - 2D Geo::Mark"                       # configurable: oriented copies of ink curves go here
EDGE_ON_TOL = 0.05                                      # configurable: |view dir Z| below this = view is edge-on to XY

CANCEL, NEXT = 0, 1


def log(msg):
    Rhino.RhinoApp.WriteLine("FabOrient: " + msg)


def unit(v):
    L = v.Length
    return Vector3d(v.X / L, v.Y / L, v.Z / L)


def dot(a, b):
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def layer_index(doc, path):
    """Return layer index, or -1 (with message) if missing / hidden / locked, incl. parents."""
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


def curve_samples(crv, n=20):
    """Points along a curve: n divisions incl. ends; falls back to ends + mid for short curves."""
    ts = crv.DivideByCount(n, True)
    if not ts:
        d = crv.Domain
        ts = [d.Min, d.Mid, d.Max]
    return [crv.PointAt(t) for t in ts]


def ink_on_brep(doc, brep, ink_idx, tol):
    """Visible, unlocked curves on the ink layer whose sample points all lie on the brep."""
    if ink_idx < 0:
        return []
    bb = brep.GetBoundingBox(True)
    bb.Inflate(tol * 10)
    found = []
    for obj in doc.Objects.FindByLayer(doc.Layers[ink_idx]) or []:
        if obj.ObjectType != ObjectType.Curve or obj.IsHidden or obj.IsLocked or obj.IsReference:
            continue
        crv = obj.Geometry
        cbb = crv.GetBoundingBox(True)
        if not (bb.Contains(cbb.Min) and bb.Contains(cbb.Max)):
            continue  # quick reject
        if all(brep.ClosestPoint(pt).DistanceTo(pt) <= tol * 10 for pt in curve_samples(crv)):
            found.append(obj)
    return found


def source_plane(face, tol):
    """Plane at face centroid. Z = outward face normal, X = longest outer-loop edge chord."""
    ok, fit = face.TryGetPlane(tol)
    if not ok:
        return None, "Face is not planar. Pick a planar face."

    amp = AreaMassProperties.Compute(face.DuplicateFace(False))  # trimmed-face centroid
    if amp is None:
        return None, "Could not compute face centroid."
    c = amp.Centroid

    # Outward normal: underlying surface normal, flipped if face orientation is reversed.
    # Valid for outward-oriented solids (checked by caller).
    ok, u, v = face.ClosestPoint(c)
    n = face.UnderlyingSurface().NormalAt(u, v)
    if face.OrientationIsReversed:
        n = Vector3d(-n.X, -n.Y, -n.Z)
    n = unit(n)

    # Longest outer-loop edge; curved edge -> use end-to-end chord.
    edges = []
    for trim in face.OuterLoop.Trims:
        if trim.TrimType == BrepTrimType.Singular or trim.Edge is None:
            continue
        e = trim.Edge
        edges.append((e.GetLength(), e.PointAtEnd - e.PointAtStart))
    edges.sort(key=lambda t: t[0], reverse=True)

    x = None
    for _, chord in edges:
        d = dot(chord, n)
        cand = Vector3d(chord.X - n.X * d, chord.Y - n.Y * d, chord.Z - n.Z * d)  # project into face plane
        if cand.Length > tol:  # skips closed edges (zero chord)
            x = unit(cand)
            break
    if x is None:  # e.g. circular face: fall back to fitted plane's X
        x = unit(fit.XAxis)

    y = Vector3d.CrossProduct(n, x)  # x × y = n
    return Plane(c, x, y), None


def resolve_to_xy(vp, pt, tol):
    """Map a picked/cursor point to World XY regardless of view or its CPlane."""
    cp = vp.ConstructionPlane()
    if abs(abs(cp.ZAxis.Z) - 1.0) < 1e-6 and abs(cp.OriginZ) < tol:
        # View CPlane is world XY (Top, default Perspective): drop Z. Osnaps -> vertical projection.
        return Point3d(pt.X, pt.Y, 0.0)
    d = (pt - vp.CameraLocation) if vp.IsPerspectiveProjection else vp.CameraDirection
    d = unit(d)
    if abs(d.Z) > EDGE_ON_TOL:
        # Slide along view ray to Z0 = spot on XY under the cursor.
        # NOTE: an osnapped point here lands where the snap *appears* on XY, not straight below it.
        s = -pt.Z / d.Z
        return Point3d(pt.X + d.X * s, pt.Y + d.Y * s, 0.0)
    # Edge-on view (Front/Right etc.): project straight down.
    return Point3d(pt.X, pt.Y, 0.0)


def locate(doc, wires):
    """Float edge preview (already at origin) on World XY; return drop point or None."""
    tol = doc.ModelAbsoluteTolerance
    color = Rhino.ApplicationSettings.AppearanceSettings.FeedbackColor

    def on_draw(sender, e):
        p = resolve_to_xy(e.Viewport, e.CurrentPoint, tol)
        e.Display.PushModelTransform(Transform.Translation(Vector3d(p)))
        for crv in wires:
            e.Display.DrawCurve(crv, color, 1)
        e.Display.PopModelTransform()
        e.Display.DrawPoint(p, color)

    gp = GetPoint()
    gp.SetCommandPrompt("Locate closed solid")
    gp.DynamicDraw += on_draw
    res = gp.Get()
    gp.DynamicDraw -= on_draw
    if res != GetResult.Point:
        return None
    return resolve_to_xy(gp.View().ActiveViewport, gp.Point(), tol)


def commit(doc, rhobj, objref, xf, fab_idx, inks, mark_idx):
    """Add transformed identical copy on fab layer; copy ink curves to mark layer; turn original red."""
    geo = rhobj.Geometry.Duplicate()  # keeps geometry UserText / user data
    if not geo.Transform(xf):
        if rhobj.ObjectType == ObjectType.Extrusion:
            geo = objref.Brep().DuplicateBrep()  # extrusion fallback -> polysurface
            if not geo.Transform(xf):
                return False
        else:
            return False

    attrs = rhobj.Attributes.Duplicate()  # name, color, attribute UserText, etc.
    attrs.LayerIndex = fab_idx
    attrs.RemoveFromAllGroups()           # don't drag flats along with boat groups
    if doc.Objects.Add(geo, attrs) == System.Guid.Empty:
        return False

    for ink in inks:  # same transform as the part; originals untouched
        crv = ink.Geometry.Duplicate()
        crv.Transform(xf)
        ia = ink.Attributes.Duplicate()
        ia.LayerIndex = mark_idx
        ia.RemoveFromAllGroups()
        doc.Objects.Add(crv, ia)

    oa = rhobj.Attributes.Duplicate()
    oa.ColorSource = ObjectColorSource.ColorFromObject
    oa.ObjectColor = RED
    doc.Objects.ModifyAttributes(rhobj, oa, True)
    return True


def process_one(doc, fab_idx, ink_idx, mark_idx):
    tol = doc.ModelAbsoluteTolerance

    go = GetObject()
    go.SetCommandPrompt("Select face of closed solid")
    go.GeometryFilter = ObjectType.Surface  # meshes, SubD, blocks filtered out
    go.SubObjectSelect = True
    go.EnablePreSelect(False, True)
    go.DeselectAllBeforePostSelect = True
    if go.Get() != GetResult.Object:
        return CANCEL
    objref = go.Object(0)
    doc.Objects.UnselectAll()

    rhobj, face, brep = objref.Object(), objref.Face(), objref.Brep()
    if rhobj is None or face is None or brep is None:
        log("Pick a face on a closed polysurface.")
        return NEXT
    if rhobj.IsReference:
        log("Worksession/reference object. Skipped.")
        return NEXT
    if not brep.IsSolid:
        log("Not a closed solid. Skipped.")
        return NEXT
    if brep.SolidOrientation != BrepSolidOrientation.Outward:
        log("Solid is inside-out (normals point in). Run Flip on the original, then retry.")
        return NEXT

    src, err = source_plane(face, tol)
    if src is None:
        log(err)
        return NEXT

    if rhobj.Attributes.DrawColor(doc).ToArgb() == RED.ToArgb():
        rc, again = RhinoGet.GetBool("Already red. Process again?", True, "No", "Yes", False)
        if rc != Result.Success:
            return CANCEL
        if not again:
            return NEXT

    to_origin = Transform.PlaneToPlane(src, Plane.WorldXY)  # face centroid -> origin, normal -> +Z
    wires = []
    for crv in brep.DuplicateEdgeCurves(False):  # edges-only preview, stays fast on big parts
        crv.Transform(to_origin)
        wires.append(crv)

    inks = ink_on_brep(doc, brep, ink_idx, tol)
    if inks:
        log("{} ink curve(s) found on part.".format(len(inks)))
    for ink in inks:  # preview marks with the part
        crv = ink.Geometry.Duplicate()
        crv.Transform(to_origin)
        wires.append(crv)

    p = locate(doc, wires)
    if p is None:
        return CANCEL  # nothing created yet, nothing to clean up

    xf = Transform.Translation(Vector3d(p)) * to_origin

    sn = doc.BeginUndoRecord("FabOrient")  # may return 0 inside a running command (see notes)
    ok = commit(doc, rhobj, objref, xf, fab_idx, inks, mark_idx)
    if sn:
        doc.EndUndoRecord(sn)
    if not ok:
        log("Failed to create copy.")
    doc.Views.Redraw()
    return NEXT


def main():
    doc = sc.doc
    fab_idx = layer_index(doc, FAB_LAYER)
    mark_idx = layer_index(doc, MARK_LAYER)
    if fab_idx < 0 or mark_idx < 0:
        return
    ink_idx = doc.Layers.FindByFullPath(INK_LAYER, -1)  # missing ink layer = no marks, not an error
    if ink_idx < 0:
        log('Layer "{}" not found; ink curves will not be copied.'.format(INK_LAYER))
    while process_one(doc, fab_idx, ink_idx, mark_idx) != CANCEL:
        pass


if __name__ == "__main__":
    main()
