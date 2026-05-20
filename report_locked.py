# -*- coding: utf-8 -*-
"""
report_locked.py

Reports all individually locked objects in the document, grouped by layer.
Ignores objects locked due to their layer being locked — only catches objects
locked via Lock or object-level lock. Shows a message box with counts per
layer and a grand total.

No configurable variables.
"""
import rhinoscriptsyntax as rs
import scriptcontext as sc
import Rhino

def find_locked_objects():
    doc = sc.doc

    settings = Rhino.DocObjects.ObjectEnumeratorSettings()
    settings.ActiveObjects = True
    settings.NormalObjects = True
    settings.HiddenObjects = True
    settings.LockedObjects = True

    results = {}

    for obj in doc.Objects.GetObjectList(settings):
        if obj.Attributes.Mode == Rhino.DocObjects.ObjectMode.Locked:
            layer = doc.Layers[obj.Attributes.LayerIndex]
            results[layer.FullPath] = results.get(layer.FullPath, 0) + 1

    if not results:
        rs.MessageBox("No locked objects found.", 0, "Locked Object Report")
        return

    lines = ["Locked objects by layer:\n"]
    total = 0
    for layer_path in sorted(results.keys()):
        count = results[layer_path]
        total += count
        lines.append("  {} - {} object(s)".format(layer_path, count))

    lines.append("\nTotal locked objects: {}".format(total))
    rs.MessageBox("\n".join(lines), 0, "Locked Object Report")

find_locked_objects()