"""
set_color_red

Sets the display color of all currently selected objects to RGB red (255, 0, 0),
overriding any layer or parent color with a per-object color assignment.
"""

import rhinoscriptsyntax as rs

def turn_selected_objects_red():
    objects = rs.SelectedObjects()
    
    if not objects:
        print("No objects selected.")
        return
    
    red = (255, 0, 0)
    
    for obj in objects:
        rs.ObjectColor(obj, red)
        rs.ObjectColorSource(obj, 1)

    print("Turned {} object(s) red.".format(len(objects)))

turn_selected_objects_red()
