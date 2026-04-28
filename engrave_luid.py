# -*- coding: utf-8 -*-
"""
engrave_luid

Reads the "luid" UserText attribute from each selected object and creates engraved
text curves (using MecSoft_Font 1) centered on the object's bounding box, projected
onto the current CPlane. The text object is immediately exploded to outline curves.
"""

import rhinoscriptsyntax as rs
import Rhino.Geometry as rg
import System.Drawing as sd


def find_mecsoft_font():
    target = "mecsoft_font 1"
    fallback = None
    for f in sd.FontFamily.Families:
        name_lower = f.Name.lower()
        if name_lower == target:
            return f.Name
        if fallback is None and "mecsoft" in name_lower:
            fallback = f.Name
    return fallback


def project_onto_cplane(pt, cplane):
    n = cplane.Normal
    vec = pt - cplane.Origin
    dist = vec.X * n.X + vec.Y * n.Y + vec.Z * n.Z
    return rg.Point3d(pt.X - dist * n.X, pt.Y - dist * n.Y, pt.Z - dist * n.Z)


def create_luid_text():
    obj_ids = rs.GetObjects("Select part(s)", preselect=True)
    if not obj_ids:
        return

    font_name = find_mecsoft_font()
    if font_name is None:
        rs.MessageBox(
            "MecSoft_Font 1 is not installed on this machine.\n"
            "Install RhinoCAM/VisualCAM or manually install the MecSoft fonts.",
            title="LUID Text"
        )
        return

    text_height = rs.GetReal("Text height", 1.0, 0.001)
    if text_height is None:
        return

    cplane = rs.ViewCPlane()
    all_curves = []
    skipped = []

    for obj_id in obj_ids:
        luid_value = rs.GetUserText(obj_id, "luid")
        if luid_value is None:
            skipped.append(rs.ObjectName(obj_id) or str(obj_id))
            continue

        bbox = rs.BoundingBox([obj_id])
        if not bbox:
            continue

        cx = (bbox[0].X + bbox[6].X) / 2.0
        cy = (bbox[0].Y + bbox[6].Y) / 2.0
        cz = (bbox[0].Z + bbox[6].Z) / 2.0
        projected = project_onto_cplane(rg.Point3d(cx, cy, cz), cplane)
        text_plane = rg.Plane(projected, cplane.XAxis, cplane.YAxis)

        text_id = rs.AddText(luid_value, text_plane, text_height, font_name, 0, 65540)
        if text_id:
            curves = rs.ExplodeText(text_id, delete=True)
            if curves:
                all_curves.extend(curves)

    if all_curves:
        rs.SelectObjects(all_curves)
        print("Created curves for {} part(s).".format(len(all_curves) and len(obj_ids) - len(skipped)))

    if skipped:
        rs.MessageBox(
            "Skipped - no 'luid' key:\n" + "\n".join(skipped),
            title="LUID Text"
        )


create_luid_text()
