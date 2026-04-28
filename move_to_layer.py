"""
move_to_layer

Moves all currently selected objects to a target layer, creating it if it does not
already exist. Change layer_name to move objects to a different layer.
"""

import rhinoscriptsyntax as rs

def move_selected_objects_to_test_layer():
    layer_name = "Plateee"  # change this to target a different layer
    
    if not rs.IsLayer(layer_name):
        rs.AddLayer(layer_name)

    objects = rs.SelectedObjects()

    if not objects:
        print("No objects selected.")
        return

    for obj in objects:
        rs.ObjectLayer(obj, layer_name)
    
    print("Moved {} object(s) to layer '{}'.".format(len(objects), layer_name))

move_selected_objects_to_test_layer()
