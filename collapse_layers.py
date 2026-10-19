#! python 3
"""Collapses all layers in the layer panel."""
import scriptcontext as sc


def collapse_layers():
    for layer in sc.doc.Layers:
        layer.IsExpanded = False


collapse_layers()
