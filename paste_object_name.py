# python3
"""Pastes the clipboard text as the name of all selected objects."""
import rhinoscriptsyntax as rs
from Eto.Forms import Clipboard


def paste_object_name():
    objs = rs.GetObjects("Select object", preselect=True)
    if not objs:
        return

    name = Clipboard.Instance.Text
    if not name:
        print("Clipboard is empty.")
        return

    for obj in objs:
        rs.ObjectName(obj, name)

    print("Named: " + name)


paste_object_name()
