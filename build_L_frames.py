"""
build_L_frames

For each selected curve lying on a chosen surface, builds a plane oriented to
the surface normal at the curve's midpoint, creates a large planar surface through
that plane, then intersects it with the original brep to produce cross-section curves.
"""

import rhinoscriptsyntax as rs
import Rhino
import scriptcontext as sc
import System

def build_and_trim_planar_surfaces():

    curve_ids = rs.GetObjects("Select curves", rs.filter.curve)
    if not curve_ids:
        return

    srf_id = rs.GetObject("Select surface the curves are on", rs.filter.surface | rs.filter.polysurface)
    if not srf_id:
        return

    height = rs.GetReal("Enter extrusion height (plane size control)", 10.0)
    if height is None:
        return

    brep = rs.coercebrep(srf_id)
    if not brep:
        print("Invalid surface.")
        return

    face = brep.Faces[0]

    created = 0

    for cid in curve_ids:

        curve = rs.coercecurve(cid)
        if not curve:
            continue

        start_pt = curve.PointAtStart
        end_pt = curve.PointAtEnd

        base_line = Rhino.Geometry.Line(start_pt, end_pt)
        line_vec = end_pt - start_pt
        line_vec.Unitize()

        t0 = curve.Domain.T0
        t1 = curve.Domain.T1
        mid_t = (t0 + t1) / 2.0
        mid_point = curve.PointAt(mid_t)

        success, u, v = face.ClosestPoint(mid_point)
        if not success:
            continue

        normal = face.NormalAt(u, v)
        normal.Unitize()

        plane = Rhino.Geometry.Plane(start_pt, line_vec, normal)

        plane_srf = Rhino.Geometry.PlaneSurface(
            plane,
            Rhino.Geometry.Interval(-height, base_line.Length + height),
            Rhino.Geometry.Interval(-height, height)
        )

        intersections = Rhino.Geometry.Intersect.Intersection.BrepBrep(
            brep,
            plane_srf.ToBrep(),
            sc.doc.ModelAbsoluteTolerance
        )

        if intersections and intersections[1]:
            for crv in intersections[1]:
                sc.doc.Objects.AddCurve(crv)

        sc.doc.Objects.AddSurface(plane_srf)
        created += 1

    sc.doc.Views.Redraw()
    print(str(created) + " plane(s) created and intersected.")

build_and_trim_planar_surfaces()