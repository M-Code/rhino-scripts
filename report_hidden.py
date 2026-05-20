# -*- coding: utf-8 -*-
"""
report_hidden.py

Reports all individually hidden objects in the document, grouped by layer.
Ignores objects hidden due to their layer being off — only catches objects
hidden via Hide or object-level visibility. Shows a message box with counts
per layer and a grand total.

No configurable variables.
"""
import rhinoscriptsyntax as rs
import scriptcontext as sc
import Rhino

def find_hidden_objects():
    doc = sc.doc

    settings = Rhino.DocObjects.ObjectEnumeratorSettings()
    settings.ActiveObjects = True
    settings.NormalObjects = True
    settings.HiddenObjects = True
    settings.LockedObjects = True

    results = {}

    for obj in doc.Objects.GetObjectList(settings):
        if obj.Attributes.Mode == Rhino.DocObjects.ObjectMode.Hidden:
            layer = doc.Layers[obj.Attributes.LayerIndex]
            results[layer.FullPath] = results.get(layer.FullPath, 0) + 1

    if not results:
        rs.MessageBox("No hidden objects found.", 0, "Hidden Object Report")
        return

    lines = ["Hidden objects by layer:\n"]
    total = 0
    for layer_path in sorted(results.keys()):
        count = results[layer_path]
        total += count
        lines.append("  {} - {} object(s)".format(layer_path, count))

    lines.append("\nTotal hidden objects: {}".format(total))
    rs.MessageBox("\n".join(lines), 0, "Hidden Object Report")

find_hidden_objects()