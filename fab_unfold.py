#! python 3
"""
Unfold an open polysurface of planar, sharp-creased faces onto its base face's plane.
Pick base face, then pick chains of faces one at a time (each unfolds immediately).
Enter with nothing picked = finish: join -> DupBorder -> outside/inside layers -> bend lines + text -> delete part.
Esc at any point = original 3D restored.
Requires Rhino 8, Python 3.
"""

import math

import System
import System.Drawing
import Rhino
import scriptcontext as sc
from Rhino import RhinoMath, UnitSystem
from Rhino.Geometry import (Point3d, Vector3d, Plane, Transform, Brep, Curve,
                            AreaMassProperties, TextEntity, PointFaceRelation)
from Rhino.Input.Custom import GetObject
from Rhino.Input import GetResult
from Rhino.Geometry import Polyline
from Rhino.DocObjects import (ObjectType, ObjectAttributes, Font, DimensionStyle,
                              TextHorizontalAlignment, TextVerticalAlignment)

BEND_LAYER     = "06 - 2D Geo::Mark"          # configurable: bend lines + UP/DW text (full layer path)
OUTSIDE_LAYER  = "06 - 2D Geo::Outside cut"   # configurable: outer profile
INSIDE_LAYER   = "06 - 2D Geo::Inside cut"    # configurable: holes / cutouts
TEXT_FONT      = "MecSoft_Font 1"             # configurable: searched in installed fonts (_/space and case ignored)
TEXT_HEIGHT_IN = 1.0                          # configurable: inches
SPLIT_OVER_IN  = 10.0                         # configurable: bend lines longer than this (in) ...
SPLIT_KEEP_IN  = 4.0                          # configurable: ... draw only this much (in) at each end
DIAMOND_LEN_IN = 1.4375                       # configurable: bend diamond length along line (1 7/16")
DIAMOND_WID_IN = 0.625                        # configurable: bend diamond width across line (5/8")
TEXT_GAP_IN    = 1.0                          # configurable: gap between diamond tip and text (in)
LUID_HEIGHT_IN = 1.0                          # configurable: part luid text height (in), placed at flat's area centroid

FINISH = "finish"
FONT_NAME = None  # resolved at startup from TEXT_FONT


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


def log(msg):
    Rhino.RhinoApp.WriteLine("FabUnfold: " + msg)


# ---------- vector helpers (explicit math; avoids pythonnet operator ambiguity) ----------
def dot(a, b):      return a.X * b.X + a.Y * b.Y + a.Z * b.Z
def scale(v, s):    return Vector3d(v.X * s, v.Y * s, v.Z * s)
def padd(p, v):     return Point3d(p.X + v.X, p.Y + v.Y, p.Z + v.Z)
def neg(v):         return Vector3d(-v.X, -v.Y, -v.Z)
def unit(v):
    L = v.Length
    return Vector3d(v.X / L, v.Y / L, v.Z / L)
def perp(v, a):     # component of v perpendicular to unit a
    d = dot(v, a)
    return Vector3d(v.X - a.X * d, v.Y - a.Y * d, v.Z - a.Z * d)


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


def outward_normal(face):
    """Face normal at centroid, respecting face orientation."""
    c = AreaMassProperties.Compute(face.DuplicateFace(False)).Centroid
    ok, u, v = face.ClosestPoint(c)
    n = face.UnderlyingSurface().NormalAt(u, v)
    if face.OrientationIsReversed:
        n = neg(n)
    return c, unit(n)


def inward_dir(face, A, B, tol):
    """Unit vector in face's plane, perpendicular to edge A-B, pointing into the face."""
    ok, pl = face.TryGetPlane(tol)
    a = unit(B - A)
    w = unit(Vector3d.CrossProduct(pl.Normal, a))
    mid = Point3d((A.X + B.X) / 2, (A.Y + B.Y) / 2, (A.Z + B.Z) / 2)
    step = max(tol * 20, A.DistanceTo(B) * 0.001)
    test = padd(mid, scale(w, step))
    ok, u, v = face.ClosestPoint(test)
    if face.IsPointOnFace(u, v) == PointFaceRelation.Interior:
        return w
    return neg(w)


def curve_samples(crv, n=20):
    """Points along a curve: n divisions incl. ends; falls back to ends + mid for short curves."""
    ts = crv.DivideByCount(n, True)
    if not ts:
        d = crv.Domain
        ts = [d.Min, d.Mid, d.Max]
    return [crv.PointAt(t) for t in ts]


def combine(face_breps):
    """Unjoined brep; face i == original face i (Append keeps order)."""
    out = Brep()
    for fb in face_breps:
        out.Append(fb)
    return out


def pick_base(doc):
    go = GetObject()
    go.SetCommandPrompt("Select base surface")
    go.GeometryFilter = ObjectType.Surface
    go.SubObjectSelect = True
    go.EnablePreSelect(False, True)
    if go.Get() != GetResult.Object:
        return None
    ref = go.Object(0)
    doc.Objects.UnselectAll()
    return ref


def pick_chain(doc, part_id):
    """Returns None (Esc), FINISH (Enter, nothing picked), or set of face indices."""
    go = GetObject()
    go.SetCommandPrompt("Select chain of surfaces to flatten (Enter = finish)")
    go.GeometryFilter = ObjectType.Surface
    go.SubObjectSelect = True
    go.EnablePreSelect(False, True)
    go.AcceptNothing(True)
    res = go.GetMultiple(1, 0)
    if res == GetResult.Nothing:
        return FINISH
    if res != GetResult.Object:
        return None
    idxs = []  # click order preserved (GetMultiple returns picks in selection order)
    for i in range(go.ObjectCount):
        r = go.Object(i)
        if r.ObjectId != part_id or r.GeometryComponentIndex.Index < 0:
            continue  # other objects / whole-object picks ignored
        fi = r.GeometryComponentIndex.Index
        if fi not in idxs:
            idxs.append(fi)
    doc.Objects.UnselectAll()
    return idxs


class Unfolder:
    def __init__(self, doc, brep, base_idx):
        self.doc = doc
        self.tol = doc.ModelAbsoluteTolerance
        self.angtol = doc.ModelAngleToleranceDegrees
        self.n = brep.Faces.Count
        self.faces = [brep.Faces[i].DuplicateFace(False) for i in range(self.n)]  # current geometry
        self.xf = [Transform.Identity for _ in range(self.n)]                      # original -> current
        self.adj = [[] for _ in range(self.n)]                                    # (nbr, P0, P1) original edge pts
        for e in brep.Edges:
            fs = list(e.AdjacentFaces())
            if len(fs) == 2 and fs[0] != fs[1]:
                self.adj[fs[0]].append((fs[1], e.PointAtStart, e.PointAtEnd))
                self.adj[fs[1]].append((fs[0], e.PointAtStart, e.PointAtEnd))
        c, N = outward_normal(brep.Faces[base_idx])
        self.N = N  # "up" = base face normal
        x = perp(Vector3d.XAxis, N)
        if x.Length < 1e-6:
            x = perp(Vector3d.YAxis, N)
        x = unit(x)
        self.plane = Plane(c, x, Vector3d.CrossProduct(N, x))  # base plane, X ~ world X for text readability
        self.base = base_idx
        self.flat = {base_idx}
        self.bends = []   # (A, B, text)
        self.luid = None  # part's "luid" UserText, set by caller
        self.marks = []   # (obj_id, face_idx, original curve) - mark curves riding on faces

    def find_marks(self, mark_idx):
        """Mark-layer curves lying on a face of the part (checked before anything moves)."""
        doc, tol = self.doc, self.tol
        for obj in doc.Objects.FindByLayer(doc.Layers[mark_idx]) or []:
            if obj.ObjectType != ObjectType.Curve or obj.IsHidden or obj.IsLocked or obj.IsReference:
                continue
            crv = obj.Geometry
            pts = curve_samples(crv)
            for i, fb in enumerate(self.faces):
                if all(fb.ClosestPoint(pt).DistanceTo(pt) <= tol * 10 for pt in pts):
                    self.marks.append((obj.Id, i, crv.DuplicateCurve()))
                    break  # first face wins (curves crossing a bend not supported)
        if self.marks:
            log("{} mark curve(s) found on part.".format(len(self.marks)))

    def unfold_chain(self, picks):
        """Unfold one chain. Click order decides hinges:
        1st pick hinges on the base surface; each later pick hinges on the most recent
        earlier pick it shares an edge with. Whole chain validated before anything moves."""
        order = [f for f in picks if f not in self.flat]
        if not order:
            log("Those surfaces are already flat.")
            return False

        plan = []  # (face, parent, P0, P1) in click order
        for i, c in enumerate(order):
            hinge = None
            if i == 0:
                for nb, P0, P1 in self.adj[c]:
                    if nb == self.base:              # root always hinges on the base surface
                        hinge = (nb, P0, P1)
                        break
                if hinge is None:
                    log("First pick must share an edge with the base surface. Chain rejected.")
                    return False
            else:
                for j in range(i - 1, -1, -1):          # most recent earlier pick first
                    for nb, P0, P1 in self.adj[c]:
                        if nb == order[j]:
                            hinge = (nb, P0, P1)
                            break
                    if hinge:
                        break
                if hinge is None:
                    log("Pick #{} doesn't share an edge with an earlier pick in this chain. Chain rejected.".format(i + 1))
                    return False
            plan.append((c,) + hinge)

        for c, p, P0, P1 in plan:
            self.unfold_face(c, p, P0, P1)
        return True

    def unfold_face(self, c, p, P0, P1):
        """Rotate face c flat about its shared edge (P0-P1, original coords) with flat parent p."""
        # Unpicked faces never move, so c may still sit where it was before its parent
        # flattened. Snap c into parent's frame first (as if it had been carried along).
        ok, inv = self.xf[c].TryGetInverse()
        pre = self.xf[p] * inv
        self.faces[c].Transform(pre)
        self.xf[c] = pre * self.xf[c]

        # Shared edge in current position (parent is flat and never moves again).
        A, B = self.xf[p] * P0, self.xf[p] * P1
        a = unit(B - A)

        uc = inward_dir(self.faces[c].Faces[0], A, B, self.tol)  # into flange
        up = inward_dir(self.faces[p].Faces[0], A, B, self.tol)  # into parent
        included = math.degrees(math.acos(max(-1.0, min(1.0, dot(uc, up)))))

        if abs(180.0 - included) > self.angtol:
            # Rotate flange so it points directly away from parent.
            ut = neg(up)
            cr = Vector3d.CrossProduct(uc, ut)
            theta = math.atan2(dot(cr, a), dot(uc, ut))
            R = Transform.Rotation(theta, a, A)
            self.faces[c].Transform(R)          # only this face moves
            self.xf[c] = R * self.xf[c]
            direction = "UP" if dot(uc, self.N) > 0 else "DW"  # flange above base top side -> UP
            self.bends.append((A, B, "{} {}".format(direction, int(math.floor(included + 0.5)))))

        self.flat.add(c)

    def on_base(self, i):
        return all(abs(self.plane.DistanceTo(v.Location)) <= self.tol * 10 for v in self.faces[i].Vertices)

    def overlaps(self):
        """Pairs of faces whose outer loops overlap by real area (touching along edges is fine)."""
        loops = [fb.Faces[0].OuterLoop.To3dCurve() for fb in self.faces]
        min_area = (self.tol * 10) ** 2
        hits = []
        for i in range(self.n):
            for j in range(i + 1, self.n):
                res = Curve.CreateBooleanIntersection(loops[i], loops[j], self.tol)
                for crv in (res or []):
                    amp = AreaMassProperties.Compute(crv)
                    if amp is not None and amp.Area > min_area:
                        hits.append((i, j))
                        break
        return hits

    def finish(self, part_id, lay):
        """Returns True if committed; False = keep picking."""
        doc, tol = self.doc, self.tol

        not_flat = [i for i in range(self.n) if i not in self.flat and not self.on_base(i)]
        if not_flat:
            log("{} surface(s) not flat yet. Keep picking.".format(len(not_flat)))
            return False

        hits = self.overlaps()
        if hits:
            log("Warning: {} overlapping surface pair(s) in the flat — can't be cut from one sheet.".format(len(hits)))

        joined = Brep.JoinBreps(self.faces, tol)
        if not joined:
            log("Join failed. Keep picking or Esc.")
            return False
        if len(joined) > 1:
            log("Warning: flat joined into {} pieces.".format(len(joined)))

        naked = []
        for b in joined:
            naked.extend(b.DuplicateNakedEdgeCurves(True, True))  # DupBorder equivalent
        loops = list(Curve.JoinCurves(naked, tol))

        # Largest closed loop = outside; everything else = inside.
        def area(crv):
            if not crv.IsClosed:
                return -1.0
            amp = AreaMassProperties.Compute(crv)
            return amp.Area if amp else -1.0
        loops.sort(key=area, reverse=True)
        if any(not c.IsClosed for c in loops):
            log("Warning: open border curve(s) found; placed on inside layer.")

        u = RhinoMath.UnitScale(UnitSystem.Inches, doc.ModelUnitSystem)
        split_over, keep, h = SPLIT_OVER_IN * u, SPLIT_KEEP_IN * u, TEXT_HEIGHT_IN * u
        dlen, dwid = DIAMOND_LEN_IN * u, DIAMOND_WID_IN * u

        def attrs(idx):
            at = ObjectAttributes()
            at.LayerIndex = idx
            return at

        # Private text style: font/height/alignment live here, used for both layout and curve output.
        def make_ds(halign, height):
            ds = DimensionStyle()
            ds.Font = Font(FONT_NAME)
            ds.TextHeight = height
            ds.TextHorizontalAlignment = halign
            ds.TextVerticalAlignment = TextVerticalAlignment.Middle
            return ds
        ds_left = make_ds(TextHorizontalAlignment.Left, h)
        ds_right = make_ds(TextHorizontalAlignment.Right, h)
        ds_luid = make_ds(TextHorizontalAlignment.Center, LUID_HEIGHT_IN * u)
        gap = TEXT_GAP_IN * u

        ids = []  # everything added -> one group

        sn = doc.BeginUndoRecord("FabUnfold")  # may return 0 inside a running command
        for k, crv in enumerate(loops):
            ids.append(doc.Objects.AddCurve(crv, attrs(lay[OUTSIDE_LAYER] if k == 0 else lay[INSIDE_LAYER])))

        mark = attrs(lay[BEND_LAYER])

        # All bends identical (same direction AND angle) -> one "ALL ..." text on the
        # longest bend line; every bend still gets its line and diamond.
        all_same = len(self.bends) > 1 and len(set(t for _, _, t in self.bends)) == 1
        text_on = None
        if all_same:
            text_on = max(range(len(self.bends)), key=lambda i: self.bends[i][0].DistanceTo(self.bends[i][1]))

        for bi, (A, B, txt) in enumerate(self.bends):
            L = A.DistanceTo(B)
            d = unit(B - A)
            w = unit(Vector3d.CrossProduct(self.N, d))  # across the line, in base plane
            if L > split_over:
                segs = [(A, padd(A, scale(d, keep))), (padd(B, scale(d, -keep)), B)]
            else:
                segs = [(A, B)]

            # Diamond on first segment at its inner end (far tip = segment end); line runs through it.
            s, e = segs[0]
            near = padd(e, scale(d, -dlen))
            tip = e  # diamond far tip; saved because the line loop below reuses s, e
            if s.DistanceTo(e) > dlen:
                mid = padd(e, scale(d, -dlen / 2))
                pl = Polyline()  # built point-by-point; avoids pythonnet list->IEnumerable conversion
                for pt in (near, padd(mid, scale(w, dwid / 2)), e, padd(mid, scale(w, -dwid / 2)), near):
                    pl.Add(pt)
                ids.append(doc.Objects.AddPolyline(pl, mark))
            else:
                log("Bend line shorter than diamond; diamond skipped.")
            for s, e in segs:
                ids.append(doc.Objects.AddLine(s, e, mark))

            if all_same:
                if bi != text_on:
                    continue                 # line + diamond only
                txt = "ALL " + txt

            # Text as curves, right next to the diamond:
            #   split line   -> past the diamond's far tip (in the gap, on the part)
            #   unsplit line -> diamond is at the far edge, so text goes before it (back into the part)
            split = len(segs) == 2
            anchor = padd(tip, scale(d, gap)) if split else padd(near, scale(d, -gap))
            t = d if split else neg(d)                      # direction text extends from anchor

            r = d                                           # reading direction, never upside down
            dx, dy = dot(r, self.plane.XAxis), dot(r, self.plane.YAxis)
            if dx < -1e-9 or (abs(dx) <= 1e-9 and dy < 0):
                r = neg(r)
            ds = ds_left if dot(r, t) > 0 else ds_right     # anchor on the diamond side of the text

            tpl = Plane(anchor, r, Vector3d.CrossProduct(self.N, r))
            te = TextEntity.Create(txt, tpl, ds, False, 0.0, 0.0)
            crvs = te.CreateCurves(ds, True, 0.0, 0.0) if te else None  # allowOpen=True: single-stroke font
            if not crvs:
                log('Could not convert "{}" to curves (font "{}" installed?).'.format(txt, TEXT_FONT))
                continue
            for c in crvs:
                ids.append(doc.Objects.AddCurve(c, mark))

        # Part luid as text curves, centered on the flat's area centroid.
        if not self.luid:
            log("Part has no luid; luid text skipped.")
        else:
            tot, cx, cy, cz = 0.0, 0.0, 0.0, 0.0
            for b in joined:
                amp = AreaMassProperties.Compute(b)
                if amp:
                    tot += amp.Area
                    cx += amp.Centroid.X * amp.Area
                    cy += amp.Centroid.Y * amp.Area
                    cz += amp.Centroid.Z * amp.Area
            if tot > 0:
                cen = Point3d(cx / tot, cy / tot, cz / tot)
                lpl = Plane(cen, self.plane.XAxis, self.plane.YAxis)
                te = TextEntity.Create(self.luid, lpl, ds_luid, False, 0.0, 0.0)
                crvs = te.CreateCurves(ds_luid, True, 0.0, 0.0) if te else None
                if crvs:
                    for c in crvs:
                        ids.append(doc.Objects.AddCurve(c, mark))
                else:
                    log("Could not convert luid to curves.")

        # Mark curves follow their face's total transform; replaced in place (attributes kept).
        for obj_id, fi, crv in self.marks:
            c = crv.DuplicateCurve()
            c.Transform(self.xf[fi])
            if doc.Objects.Replace(obj_id, c):
                ids.append(obj_id)

        ids = [i for i in ids if i != System.Guid.Empty]
        if ids:
            doc.Groups.Add(ids)

        doc.Objects.Delete(part_id, True)
        if sn:
            doc.EndUndoRecord(sn)
        return True


def main():
    global FONT_NAME
    doc = sc.doc
    tol = doc.ModelAbsoluteTolerance

    FONT_NAME = find_font(TEXT_FONT)
    if FONT_NAME is None:
        log('No MecSoft font installed ("{}"). Install RhinoCAM/VisualCAM fonts. Aborting.'.format(TEXT_FONT))
        return

    lay = {}
    for name in (BEND_LAYER, OUTSIDE_LAYER, INSIDE_LAYER):
        idx = layer_index(doc, name)
        if idx < 0:
            return
        lay[name] = idx

    # ---- base pick + part validation (re-prompt on bad pick) ----
    while True:
        ref = pick_base(doc)
        if ref is None:
            return
        rhobj, brep = ref.Object(), ref.Brep()
        if rhobj is None or brep is None or ref.GeometryComponentIndex.Index < 0:
            log("Pick a face on an open polysurface.")
            continue
        if rhobj.ObjectType != ObjectType.Brep:
            log("Expected a polysurface.")
            continue
        if rhobj.IsReference:
            log("Worksession/reference object.")
            continue
        if brep.IsSolid:
            log("That's a closed solid. Expected an open polysurface.")
            continue
        curved = [i for i in range(brep.Faces.Count) if not brep.Faces[i].TryGetPlane(tol)[0]]
        if curved:
            log("{} curved surface(s) in part. Only planar, sharp-creased parts supported.".format(len(curved)))
            continue
        break

    part_id = ref.ObjectId
    original = brep.DuplicateBrep()
    uf = Unfolder(doc, brep, ref.GeometryComponentIndex.Index)
    uf.luid = rhobj.Attributes.GetUserString("luid")  # same key stamp_luid writes
    uf.find_marks(lay[BEND_LAYER])                    # Mark layer = BEND_LAYER

    changed, done = False, False
    try:
        while True:
            picks = pick_chain(doc, part_id)
            if picks is None:
                break                          # Esc
            if picks == FINISH:
                if uf.finish(part_id, lay):
                    done = True
                    break
                continue
            if not picks:
                log("No surfaces from this part picked.")
                continue
            if uf.unfold_chain(picks):
                doc.Objects.Replace(part_id, combine(uf.faces))  # show progress; face indices preserved
                changed = True
                doc.Views.Redraw()
    finally:
        if not done and changed:
            doc.Objects.Replace(part_id, original)  # Esc / error: back to original 3D
            log("Cancelled. Part restored.")
        doc.Views.Redraw()


if __name__ == "__main__":
    main()
