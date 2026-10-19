# -*- coding: utf-8 -*-
"""
ComparePartsIdentical  -  Rhino 8 / IronPython 2.7      [ v2.2 ]

Reports a fab PASS / FAIL headline plus an exact IDENTICAL / NOT IDENTICAL
verdict for two selected objects (surface, polysurface, or extrusion),
independent of POSITION and ORIENTATION, and independent of CONSTRUCTION
(how the boundary is split into faces / edges / vertices). No alignment, no
meshing, no baked geometry -- the document is never modified.

v2.2 CHANGES:
  1. UNITS -> INCHES. Every linear quantity (reach, vertex/edge, edge-length,
     the model tolerance) is auto-converted from the document's unit system and
     shown in INCHES, to the NEAREST 1/32 as a reduced fraction, WITH the exact
     decimal alongside so a sub-1/32 difference cannot hide behind rounding.
     The detected model unit system is printed so the conversion is transparent.
  2. LINEAR ACCEPT TOLERANCE = 1/32 in (PASS_LINEAR_TOL_IN). Set from the shop
     floor number; change the one constant to retune (e.g. 1.0/16.0).
  3. PER-LINE PASS/FAIL is explicit: a value at or under its tolerance reads
     clean; only a value OVER its tolerance is flagged and can trip FAIL. A
     line under tolerance can NEVER fail the part.
  4. MASS BANDS LOOSENED off the noise floor. The old 0.5% area/volume/inertia
     band sat BELOW the repeatability of Rhino's mass-property math on thin
     parts and false-failed identical rails earlier in this project. The fab
     bands are now 1.5% area/volume, 2.5% inertia -- above the noise, still
     catching real differences (a genuinely different part reads several % and
     still FAILs).

TWO QUESTIONS, TWO TOLERANCES:
  IDENTICAL / NOT IDENTICAL  -> "is this literally the SAME part?" (tight:
                                model tolerance on positions, IDENT_* on mass)
  PASS / FAIL                -> "is this CLOSE ENOUGH to fabricate?" (loose:
                                1/32 in on linear, FAB_* on mass)
  Reachable states:
    exact copy            -> IDENTICAL + PASS
    near-copy in tol      -> NOT IDENTICAL + PASS
    out of tolerance      -> NOT IDENTICAL + FAIL

THE ROBUST IDENTITY SIGNATURE (invariant to rigid motion AND re-construction):
  total surface area, solid volume (if solid), and the sorted PRINCIPAL MOMENTS
  OF INERTIA (eigenvalues of the centroid inertia tensor). These depend only on
  the actual mass/area distribution, never on how faces are split; a rotation
  maps I -> R*I*R^T (same eigenvalues). Topology counts are informational, never
  a reject. When counts DO match, a strict per-feature refinement (sorted edge
  lengths, sorted per-face areas, centroid-distances to vertices and edge
  arc-length points) also runs to keep the exact-copy path tight.

THE FAB ACCEPTANCE BAND (PASS / FAIL):
  Linear knob is PASS_LINEAR_TOL_IN (inches), checked against:
    - Reach dev: |max centroid-to-vertex distance A - B|. Pose-invariant
      overall envelope. ALWAYS available.
    - Vertex/edge dev and Edge-length dev. True per-point linear check. Only
      available when construction matches (counts pair 1:1).
  Backed by FAB_* percent bands on area / volume / inertia so a part with the
  right envelope but the wrong shape or mass distribution still FAILs.
  PASS = IDENTICAL, or every applicable line within its tolerance.

APPROACHES DELIBERATELY NOT USED (proven dead ends):
  - Alignment (PCA / ICP then measure deviation): residual rotation amplifies
    at far edges and trips tolerance on true copies. No tolerance fixes it.
  - Face UV-grid interior sampling: a rotated/rebuilt face re-parameterizes, so
    samples land on different surface points -> phantom deviation.

EIGENVALUES:
  Closed-form symmetric-3x3 solver (trigonometric method). No numpy.

MIRROR NOTE:
  Mirror-blind: area, volume, and principal moments are unchanged by reflection,
  so a mirror image reads IDENTICAL / PASS. Ask for a chirality term if
  opposite-hand (left/right) parts must be distinguished.

The document is never modified. Alias friendly: pre-select the two objects, or
pick them when prompted. Viewport redraw is never disabled.
"""

import Rhino
import scriptcontext as sc
import rhinoscriptsyntax as rs
import math

VERSION              = "v2.2"
TOLERANCE            = None       # configurable: None uses document absolute tolerance
PASS_LINEAR_TOL_IN   = 1.0 / 32.0  # configurable
FAB_AREA_REL_TOL     = 1.5e-2     # configurable
FAB_VOL_REL_TOL      = 1.5e-2     # configurable
FAB_MOMENT_REL_TOL   = 2.5e-2     # configurable
IDENT_AREA_REL_TOL   = 1.0e-3     # configurable
IDENT_VOL_REL_TOL    = 1.0e-3     # configurable
IDENT_MOMENT_REL_TOL = 1.0e-3     # configurable
EDGE_SAMPLES         = 24         # configurable
TITLE                = "Part Comparison " + VERSION


def _tol():
    # positional identity tolerance, in MODEL units
    if TOLERANCE is not None:
        return float(TOLERANCE)
    return sc.doc.ModelAbsoluteTolerance


def _unit_scales():
    # (model->inches, inches->model). Robust to unitless documents.
    u2i = 0.0
    try:
        us = sc.doc.ModelUnitSystem
        u2i = Rhino.RhinoMath.UnitScale(us, Rhino.UnitSystem.Inches)
    except Exception:
        u2i = 0.0
    if not u2i or u2i <= 0.0:
        u2i = 1.0   # unitless / unknown: treat model units as inches
    return u2i, (1.0 / u2i)


def _unit_name():
    try:
        return str(sc.doc.ModelUnitSystem)
    except Exception:
        return "unknown"


def _gcd(a, b):
    a = abs(int(a))
    b = abs(int(b))
    while b:
        a, b = b, a % b
    return a if a else 1


def _frac32(inches):
    # nearest 1/32 inch as a reduced fraction string (e.g. "1/4", "1-1/16", "0")
    sign = "-" if inches < 0.0 else ""
    a = abs(inches)
    n = int(round(a * 32.0))
    if n == 0:
        return "0"
    whole = n // 32
    rem = n % 32
    if rem == 0:
        return sign + "{0}".format(whole)
    g = _gcd(rem, 32)
    num = rem // g
    den = 32 // g
    if whole == 0:
        return sign + "{0}/{1}".format(num, den)
    return sign + "{0}-{1}/{2}".format(whole, num, den)


# --------------------------- geometry / mass -----------------------------

def _exact_centroid(brep):
    # True geometric centroid: analytic, identical under any rigid motion.
    if brep.IsSolid:
        vmp = Rhino.Geometry.VolumeMassProperties.Compute(brep)
        if vmp:
            return vmp.Centroid
    amp = Rhino.Geometry.AreaMassProperties.Compute(brep)
    if amp:
        return amp.Centroid
    n = brep.Vertices.Count
    if n == 0:
        return None
    cx = cy = cz = 0.0
    for v in brep.Vertices:
        loc = v.Location
        cx += loc.X
        cy += loc.Y
        cz += loc.Z
    inv = 1.0 / n
    return Rhino.Geometry.Point3d(cx * inv, cy * inv, cz * inv)


def _sym3_eigenvalues(a11, a22, a33, a12, a13, a23):
    # Eigenvalues of the symmetric 3x3 matrix (trigonometric closed form).
    p1 = a12 * a12 + a13 * a13 + a23 * a23
    if p1 == 0.0:
        eigs = [a11, a22, a33]
        eigs.sort()
        return eigs

    q = (a11 + a22 + a33) / 3.0
    p2 = ((a11 - q) ** 2 + (a22 - q) ** 2 + (a33 - q) ** 2) + 2.0 * p1
    p = math.sqrt(p2 / 6.0)
    if p == 0.0:
        eigs = [a11, a22, a33]
        eigs.sort()
        return eigs

    b11 = (a11 - q) / p
    b22 = (a22 - q) / p
    b33 = (a33 - q) / p
    b12 = a12 / p
    b13 = a13 / p
    b23 = a23 / p

    detB = (b11 * (b22 * b33 - b23 * b23)
            - b12 * (b12 * b33 - b23 * b13)
            + b13 * (b12 * b23 - b22 * b13))
    r = detB / 2.0

    if r <= -1.0:
        phi = math.pi / 3.0
    elif r >= 1.0:
        phi = 0.0
    else:
        phi = math.acos(r) / 3.0

    eig_hi = q + 2.0 * p * math.cos(phi)
    eig_lo = q + 2.0 * p * math.cos(phi + (2.0 * math.pi / 3.0))
    eig_mid = 3.0 * q - eig_hi - eig_lo

    eigs = [eig_hi, eig_mid, eig_lo]
    eigs.sort()
    return eigs


def _principal_moments(mp):
    # Sorted principal moments of inertia from a (Volume or Area)MassProperties.
    try:
        diag = mp.CentroidCoordinatesMomentsOfInertia
        prod = mp.CentroidCoordinatesProductMoments
    except Exception:
        return None
    if diag is None or prod is None:
        return None
    a11 = diag.X
    a22 = diag.Y
    a33 = diag.Z
    a12 = -prod.X   # x-y coupling
    a13 = -prod.Z   # x-z coupling (prod.Z = int zx)
    a23 = -prod.Y   # y-z coupling
    return _sym3_eigenvalues(a11, a22, a33, a12, a13, a23)


def _total_area(brep):
    amp = Rhino.Geometry.AreaMassProperties.Compute(brep)
    if amp:
        return amp.Area
    return None


def _shape_signature(brep):
    # is_solid, area, volume (None if open), sorted principal moments, reach
    # (max centroid-to-vertex distance, MODEL units).
    if brep is None:
        return None
    is_solid = brep.IsSolid
    area = _total_area(brep)
    volume = None
    moments = None
    if is_solid:
        vmp = Rhino.Geometry.VolumeMassProperties.Compute(brep)
        if vmp:
            volume = vmp.Volume
            moments = _principal_moments(vmp)
    else:
        amp = Rhino.Geometry.AreaMassProperties.Compute(brep)
        if amp:
            moments = _principal_moments(amp)

    reach = None
    cen = _exact_centroid(brep)
    if cen is not None and brep.Vertices.Count > 0:
        reach = 0.0
        for v in brep.Vertices:
            d = v.Location.DistanceTo(cen)
            if d > reach:
                reach = d

    return {"is_solid": is_solid, "area": area, "volume": volume,
            "moments": moments, "reach": reach}


# --------------------- strict per-feature refinement ---------------------

def _robust_points(brep):
    # exact, rotation-stable points only: brep vertices + edge arc-length points
    pts = []
    for v in brep.Vertices:
        pts.append(v.Location)
    for edge in brep.Edges:
        params = edge.DivideByCount(EDGE_SAMPLES, True)
        if params:
            for t in params:
                pts.append(edge.PointAt(t))
    return pts


def _radial_sorted(points, centroid):
    out = []
    for p in points:
        out.append(p.DistanceTo(centroid))
    out.sort()
    return out


def _edge_lengths_sorted(brep):
    out = []
    for e in brep.Edges:
        try:
            out.append(e.GetLength())
        except Exception:
            out.append(0.0)
    out.sort()
    return out


def _face_areas_sorted(brep):
    out = []
    for f in brep.Faces:
        a = 0.0
        try:
            fb = f.DuplicateFace(False)
            amp = Rhino.Geometry.AreaMassProperties.Compute(fb)
            if amp:
                a = amp.Area
        except Exception:
            a = 0.0
        out.append(a)
    out.sort()
    return out


def _strict_match(brep_a, brep_b, tol):
    # Runs ONLY when topology counts match, so all sorted lists pair 1:1.
    # ve_dev / el_dev returned in MODEL units. strict_ok is the IDENTITY flag.
    pts_a = _robust_points(brep_a)
    pts_b = _robust_points(brep_b)
    cen_a = _exact_centroid(brep_a)
    cen_b = _exact_centroid(brep_b)

    radial_dev = 0.0
    if cen_a is not None and cen_b is not None and \
       len(pts_a) == len(pts_b) and pts_a:
        rad_a = _radial_sorted(pts_a, cen_a)
        rad_b = _radial_sorted(pts_b, cen_b)
        radial_dev = _max_paired_diff(rad_a, rad_b)

    el_a = _edge_lengths_sorted(brep_a)
    el_b = _edge_lengths_sorted(brep_b)
    edge_dev = _max_paired_diff(el_a, el_b)

    fa_a = _face_areas_sorted(brep_a)
    fa_b = _face_areas_sorted(brep_b)
    face_area_rel = _max_paired_rel(fa_a, fa_b)

    radial_ok = radial_dev <= tol
    edge_ok = edge_dev <= tol
    face_ok = face_area_rel <= IDENT_AREA_REL_TOL
    strict_ok = radial_ok and edge_ok and face_ok

    return radial_dev, edge_dev, face_area_rel, strict_ok


# ----------------------------- comparisons -------------------------------

def _max_paired_diff(la, lb):
    md = 0.0
    for x, y in zip(la, lb):
        d = abs(x - y)
        if d > md:
            md = d
    return md


def _max_paired_rel(la, lb):
    md = 0.0
    for x, y in zip(la, lb):
        m = max(abs(x), abs(y))
        d = 0.0 if m == 0.0 else abs(x - y) / m
        if d > md:
            md = d
    return md


def _rel_diff(a, b):
    m = max(abs(a), abs(b))
    if m == 0.0:
        return 0.0
    return abs(a - b) / m


# ------------------------------- report ----------------------------------

def _lin_line(label, dev_units, u2i, tol_units, tol_in):
    # dev_units in MODEL units -> shown in inches (decimal + nearest 1/32)
    if dev_units is None:
        return "{0:<17}n/a".format(label)
    inches = dev_units * u2i
    over = dev_units > tol_units
    frac = "(" + _frac32(inches) + ")"
    return "{0:<17}{1:>8.4f} in  {2:<9} tol {3}{4}".format(
        label, inches, frac, _frac32(tol_in), "   OVER" if over else "")


def _mass_line(label, pct, rel_tol):
    if pct is None:
        return "{0:<17}n/a".format(label)
    over = pct > (rel_tol * 100.0)
    return "{0:<17}{1:>8.4f}%   tol {2:.2f}%{3}".format(
        label, pct, rel_tol * 100.0, "   OVER" if over else "")


def _report(res):
    passed = res["passed"]
    identical = res["identical"]
    construction_same = res["construction_same"]
    u2i = res["u2i"]

    head = "PASS" if passed else "FAIL"
    if passed and identical:
        sub = "exact copy (identical within model tolerance)"
    elif passed and not identical:
        sub = "within fab tolerance (" + _frac32(PASS_LINEAR_TOL_IN) + " in)"
    else:
        sub = "out of tolerance"

    lines = [head, sub, ""]
    lines.append("Geometry match:  " +
                 ("IDENTICAL" if identical else "NOT IDENTICAL"))
    lines.append("Construction:    " +
                 ("same layout" if construction_same else "DIFFERENT layout"))
    lines.append("")

    lines.append("-- fab acceptance (inches) --")
    lines.append(_lin_line("Reach dev:", res["reach_dev"], u2i,
                           res["tol_units"], PASS_LINEAR_TOL_IN))
    if construction_same:
        lines.append(_lin_line("Vertex/edge dev:", res["ve_dev"], u2i,
                               res["tol_units"], PASS_LINEAR_TOL_IN))
        lines.append(_lin_line("Edge-length dev:", res["el_dev"], u2i,
                               res["tol_units"], PASS_LINEAR_TOL_IN))
    lines.append("")

    lines.append("-- shape / mass --")
    lines.append(_mass_line("Area diff:", res["area_pct"], FAB_AREA_REL_TOL))
    lines.append(_mass_line("Volume diff:", res["vol_pct"], FAB_VOL_REL_TOL))
    lines.append(_mass_line("Inertia dev:", res["moment_pct"], FAB_MOMENT_REL_TOL))
    lines.append("")

    if not construction_same:
        lines.append("(different construction: no per-point linear check;")
        lines.append(" PASS rests on Reach + shape/mass)")
        lines.append("")

    if not passed and res["fail_terms"]:
        lines.append("FAIL on: " + ", ".join(res["fail_terms"]))
        lines.append("")

    lines.append("Model tol:       {0:.4f} in".format(_tol() * u2i))
    lines.append("Model units:     " + res["unit_name"])
    lines.append("Engine:  invariant + fab-accept " + VERSION)

    rs.MessageBox("\n".join(lines), 0, TITLE)


# ------------------------------- driver ----------------------------------

def compare_parts():
    ids = rs.GetObjects("Select exactly two objects to compare",
                        rs.filter.surface + rs.filter.polysurface + rs.filter.extrusion,
                        group=False, preselect=True,
                        minimum_count=2, maximum_count=2)
    if not ids or len(ids) != 2:
        return

    brep_a = rs.coercebrep(ids[0])
    brep_b = rs.coercebrep(ids[1])
    if brep_a is None or brep_b is None:
        rs.MessageBox("Both selections must be surfaces, polysurfaces, or "
                      "extrusions.\n(Meshes / SubD are not supported.)",
                      0, TITLE)
        return

    u2i, i2u = _unit_scales()
    unit_name = _unit_name()
    tol = _tol()                                  # positional identity, model units
    tol_units = PASS_LINEAR_TOL_IN * i2u          # fab linear accept, model units

    sig_a = _shape_signature(brep_a)
    sig_b = _shape_signature(brep_b)
    if sig_a is None or sig_b is None:
        rs.MessageBox("Could not compute mass properties for one or both "
                      "parts.", 0, TITLE)
        return

    # closed solid vs open surface is a real, disqualifying difference
    if sig_a["is_solid"] != sig_b["is_solid"]:
        _report({"passed": False, "identical": False,
                 "construction_same": False,
                 "reach_dev": None, "ve_dev": None, "el_dev": None,
                 "area_pct": None, "vol_pct": None, "moment_pct": None,
                 "fail_terms": ["solid vs open surface"],
                 "tol_units": tol_units, "u2i": u2i, "unit_name": unit_name})
        return

    # ---- relative differences (drive identity and fab bands) ----
    area_rel = None
    area_pct = None
    if sig_a["area"] is not None and sig_b["area"] is not None:
        area_rel = _rel_diff(sig_a["area"], sig_b["area"])
        area_pct = area_rel * 100.0

    vol_rel = None
    vol_pct = None
    if sig_a["volume"] is not None and sig_b["volume"] is not None:
        vol_rel = _rel_diff(sig_a["volume"], sig_b["volume"])
        vol_pct = vol_rel * 100.0

    moment_rel = None
    moment_pct = None
    if sig_a["moments"] is not None and sig_b["moments"] is not None:
        moment_rel = _max_paired_rel(sig_a["moments"], sig_b["moments"])
        moment_pct = moment_rel * 100.0

    # reach: absolute linear envelope, always available
    reach_dev = None
    if sig_a["reach"] is not None and sig_b["reach"] is not None:
        reach_dev = abs(sig_a["reach"] - sig_b["reach"])

    # ---- identity verdict (tight) ----
    area_ident_ok = (area_rel is None) or (area_rel <= IDENT_AREA_REL_TOL)
    vol_ident_ok = (vol_rel is None) or (vol_rel <= IDENT_VOL_REL_TOL)
    moment_ident_ok = (moment_rel is None) or (moment_rel <= IDENT_MOMENT_REL_TOL)
    geom_same = area_ident_ok and vol_ident_ok and moment_ident_ok

    construction_same = (brep_a.Faces.Count == brep_b.Faces.Count and
                         brep_a.Edges.Count == brep_b.Edges.Count and
                         brep_a.Vertices.Count == brep_b.Vertices.Count)

    ve_dev = None
    el_dev = None
    if construction_same:
        ve_dev, el_dev, _face_rel, strict_ok = _strict_match(brep_a, brep_b, tol)
        identical = geom_same and strict_ok
    else:
        identical = geom_same

    # ---- fab acceptance verdict (per-line; OVER only when over) ----
    fail_terms = []
    if reach_dev is not None and reach_dev > tol_units:
        fail_terms.append("reach")
    if construction_same:
        if ve_dev is not None and ve_dev > tol_units:
            fail_terms.append("vertex/edge position")
        if el_dev is not None and el_dev > tol_units:
            fail_terms.append("edge length")
    if area_pct is not None and area_pct > (FAB_AREA_REL_TOL * 100.0):
        fail_terms.append("area")
    if vol_pct is not None and vol_pct > (FAB_VOL_REL_TOL * 100.0):
        fail_terms.append("volume")
    if moment_pct is not None and moment_pct > (FAB_MOMENT_REL_TOL * 100.0):
        fail_terms.append("inertia")

    acceptance_ok = (len(fail_terms) == 0)
    passed = identical or acceptance_ok
    if passed:
        fail_terms = []   # identical / near-copy: nothing to report as a failure

    _report({"passed": passed, "identical": identical,
             "construction_same": construction_same,
             "reach_dev": reach_dev, "ve_dev": ve_dev, "el_dev": el_dev,
             "area_pct": area_pct, "vol_pct": vol_pct, "moment_pct": moment_pct,
             "fail_terms": fail_terms,
             "tol_units": tol_units, "u2i": u2i, "unit_name": unit_name})


if __name__ == "__main__":
    try:
        compare_parts()
    except Exception as ex:
        rs.MessageBox("Error: {0}".format(ex), 0, TITLE)
