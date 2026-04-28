"""
group_by_boundary

Prompts for one or more closed boundary curves, then groups each boundary with
every other document curve whose sampled points all fall inside it. Open curves
in the selection are ignored. Creates one named Rhino group per boundary.
"""

import rhinoscriptsyntax as rs


def sample_curve_points(curve_id, count=7):
    domain = rs.CurveDomain(curve_id)
    if not domain:
        return []
    span = domain[1] - domain[0]
    return [
        rs.EvaluateCurve(curve_id, domain[0] + span * i / (count - 1))
        for i in range(count)
        if rs.EvaluateCurve(curve_id, domain[0] + span * i / (count - 1)) is not None
    ]


def is_curve_inside_boundary(curve_id, boundary_id):
    pts = sample_curve_points(curve_id)
    if not pts:
        return False
    for pt in pts:
        try:
            result = rs.PointInPlanarClosedCurve(pt, boundary_id)
        except Exception:
            return False
        if result != 1:
            return False
    return True


def main():
    raw_ids = rs.GetObjects(
        "Select closed boundary curves (open curves will be ignored)",
        rs.filter.curve,
        preselect=True,
    )
    if not raw_ids:
        return

    boundaries = [c for c in raw_ids if rs.IsCurveClosed(c)]
    if not boundaries:
        rs.MessageBox("No closed curves were selected. Script cancelled.")
        return

    skipped = len(raw_ids) - len(boundaries)
    if skipped:
        print("Skipped {} open curve(s).".format(skipped))

    all_doc_curves = rs.ObjectsByType(rs.filter.curve) or []
    if not all_doc_curves:
        rs.MessageBox("No curves found in the document.")
        return

    boundary_guids = set(str(b) for b in boundaries)

    rs.EnableRedraw(False)
    groups_created = 0

    for boundary_id in boundaries:
        members = [boundary_id]

        for curve_id in all_doc_curves:
            if str(curve_id) == str(boundary_id):
                continue
            try:
                if is_curve_inside_boundary(curve_id, boundary_id):
                    members.append(curve_id)
            except Exception:
                pass

        group_name = rs.AddGroup()
        rs.AddObjectsToGroup(members, group_name)
        groups_created += 1
        print(
            "Group '{}' created with {} object(s).".format(
                group_name, len(members)
            )
        )

    rs.EnableRedraw(True)
    rs.MessageBox("{} group(s) created successfully.".format(groups_created))


main()
