# -*- coding: utf-8 -*-
"""
split_volume

Finds the horizontal plane that divides a closed polysurface so that a
user-specified percentage of its total volume falls below the cut. Uses binary
search to converge on the correct Z height, then adds a rectangular plane
surface to the document at that level and reports the result.

Configurable:
    target_pct_tolerance  convergence threshold as a fraction of total volume
                          (0.0005 = 0.05%)
"""

import rhinoscriptsyntax as rs
import Rhino.Geometry as rg
import scriptcontext as sc

def volume_below_z(brep, z, size, tolerance):
    plane = rg.Plane(rg.Point3d(0, 0, z), rg.Vector3d.ZAxis)
    cutting_srf = rg.PlaneSurface(plane,
        rg.Interval(-size, size),
        rg.Interval(-size, size))
    cutting_brep = cutting_srf.ToBrep()

    pieces = brep.Split(cutting_brep, tolerance)

    if not pieces:
        return None

    best_piece = None
    best_max_z = float('inf')

    for piece in pieces:
        pbox = piece.GetBoundingBox(True)
        if pbox.Max.Z < best_max_z:
            best_max_z = pbox.Max.Z
            best_piece = piece

    if best_piece is None:
        return None

    capped = best_piece.CapPlanarHoles(tolerance)
    if capped is None:
        capped = best_piece

    mp = rg.VolumeMassProperties.Compute(capped)
    if mp is None:
        return None

    return mp.Volume

def split_volume():
    obj_id = rs.GetObject("Select a closed polysurface", rs.filter.polysurface)
    if not obj_id:
        return

    if not rs.IsPolysurfaceClosed(obj_id):
        rs.MessageBox("Object must be a closed polysurface.")
        return

    pct = rs.GetReal("Enter split percentage for bottom portion (e.g. 50 for 50%)", 50, 1, 99)
    if pct is None:
        return

    brep = rs.coercebrep(obj_id)
    tolerance = sc.doc.ModelAbsoluteTolerance

    total_mp = rg.VolumeMassProperties.Compute(brep)
    if total_mp is None:
        rs.MessageBox("Could not compute volume.")
        return
    total_volume = total_mp.Volume
    target = total_volume * (pct / 100.0)

    bbox = brep.GetBoundingBox(True)
    z_min = bbox.Min.Z
    z_max = bbox.Max.Z
    size = max(bbox.Max.X - bbox.Min.X, bbox.Max.Y - bbox.Min.Y) * 2 + 10

    target_pct_tolerance = 0.0005  # configurable
    z_mid = z_min
    vol_below = 0.0

    for i in range(100):
        z_mid = (z_min + z_max) / 2.0
        vol_below = volume_below_z(brep, z_mid, size, tolerance)

        if vol_below is None:
            rs.MessageBox("Split failed at Z = {:.4f}, iteration {}".format(z_mid, i))
            return

        error = abs(vol_below - target) / total_volume
        if error < target_pct_tolerance:
            break

        if vol_below < target:
            z_min = z_mid
        else:
            z_max = z_mid

    pad = 1.0
    cx = (bbox.Min.X + bbox.Max.X) / 2.0
    cy = (bbox.Min.Y + bbox.Max.Y) / 2.0
    half_x = (bbox.Max.X - bbox.Min.X) / 2.0 + pad
    half_y = (bbox.Max.Y - bbox.Min.Y) / 2.0 + pad

    origin = rg.Point3d(cx, cy, z_mid)
    plane = rg.Plane(origin, rg.Vector3d.ZAxis)
    plane_srf = rg.PlaneSurface(plane,
        rg.Interval(-half_x, half_x),
        rg.Interval(-half_y, half_y))

    sc.doc.Objects.AddSurface(plane_srf)
    sc.doc.Views.Redraw()

    rs.MessageBox("Plane at Z = {:.4f}\nVolume below: {:.2f} ({:.2f}%)\nTarget: {:.1f}%\nTotal: {:.2f}".format(
        z_mid,
        vol_below,
        (vol_below / total_volume) * 100,
        pct,
        total_volume
    ))

split_volume()
