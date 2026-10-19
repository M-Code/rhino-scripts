# python3
"""Copies the name of the first selected object to the clipboard."""
import rhinoscriptsyntax as rs
from Eto.Forms import Clipboard


def copy_object_name():
    objs = rs.GetObjects("Select object", preselect=True)
    if not objs:
        return

    name = rs.ObjectName(objs[0])
    if not name:
        print("Object has no name.")
        return

    Clipboard.Instance.Text = name
    print("Copied: " + name)


copy_object_name()
