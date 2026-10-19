#! python 3
"""
Selects all circles in the document whose radius matches TARGET within TOL.
Deselects everything first, then selects matching circles and prints the count.
"""
import rhinoscriptsyntax as rs
import scriptcontext as sc

TARGET = 0.1718 / 2  # configurable: radius to match
TOL    = 0.001       # configurable: match tolerance (model units)

rs.UnselectAllObjects()
hits = []

for oid in rs.ObjectsByType(4):          # 4 = curves
    crv = rs.coercecurve(oid)
    if crv is None:
        continue
    ok, circ = crv.TryGetCircle(sc.doc.ModelAbsoluteTolerance)
    if ok and abs(circ.Radius - TARGET) <= TOL:
        hits.append(oid)

rs.SelectObjects(hits)
print("{} circles selected".format(len(hits)))
