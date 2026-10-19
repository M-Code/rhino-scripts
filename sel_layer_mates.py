#! python3
"""SelLayerMates: pick an object, select everything on its layer,
then optionally add everything on its sublayers (all depths).
Prints one final report log at the end of the command.
IronPython-2.7-compatible (no f-strings) so it runs in either engine."""
import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc

TAG = "SelLayerMates"
Mode = Rhino.DocObjects.ObjectMode
FIELDS = ("selected", "hidden", "locked", "failed", "blocked")


def descendant_layers(layer):
    """All sublayers, any depth. GetChildren() only returns direct children."""
    out = []
    for k in (layer.GetChildren() or []):   # None when no children
        if k.IsDeleted:
            continue
        out.append(k)
        out.extend(descendant_layers(k))
    return out


def select_on_layer(doc, layer):
    """Select normal objects on one layer. Returns dict of counts keyed by FIELDS."""
    s = Rhino.DocObjects.ObjectEnumeratorSettings()
    s.LayerIndexFilter = layer.Index
    s.NormalObjects = True
    s.HiddenObjects = True
    s.LockedObjects = True
    s.ReferenceObjects = True
    s.IncludeLights = True
    s.IncludeGrips = False
    s.DeletedObjects = False

    # Off/locked layer: objects unselectable regardless of object mode.
    layer_ok = layer.IsVisible and not layer.IsLocked

    c = dict.fromkeys(FIELDS, 0)
    for o in doc.Objects.GetObjectList(s):
        m = o.Attributes.Mode
        if m == Mode.Hidden:
            c["hidden"] += 1
        elif m == Mode.Locked:
            c["locked"] += 1
        elif m == Mode.Normal:
            if not layer_ok:
                c["blocked"] += 1
            elif o.IsSelectable() and o.Select(True) > 0:
                c["selected"] += 1
            else:
                c["failed"] += 1            # other space / detail visibility, etc.
    return c


def add_counts(a, b):
    return dict((k, a[k] + b[k]) for k in FIELDS)


def ask_sublayers(n_selected, n_subs):
    """Y + Enter (or click Yes) = True. Enter/Space/Esc = False."""
    go = Rhino.Input.Custom.GetOption()
    go.SetCommandPrompt(
        "{} selected. Also select objects on {} sublayer(s)? Enter/Space = No".format(n_selected, n_subs))
    go.AcceptNothing(True)
    go.AddOption("Yes")
    return go.Get() == Rhino.Input.GetResult.Option   # Esc -> Cancel -> No


def print_report(layer, subs, included, parent, sub):
    total = add_counts(parent, sub)
    if not subs:
        sub_line = "none"
    elif included:
        sub_line = "{} found, included".format(len(subs))
    else:
        sub_line = "{} found, not included".format(len(subs))

    lines = [
        "---- {} report ----".format(TAG),
        "Layer:      {}".format(layer.FullPath),
        "Sublayers:  {}".format(sub_line),
    ]
    if included:
        lines.append("Selected:   {} (layer {}, sublayers {})".format(
            total["selected"], parent["selected"], sub["selected"]))
    else:
        lines.append("Selected:   {}".format(total["selected"]))
    # Hidden/locked always shown so "0" is an explicit answer, not an omission.
    lines.append("Hidden:     {} (not selected)".format(total["hidden"]))
    lines.append("Locked:     {} (not selected)".format(total["locked"]))
    if total["blocked"]:
        lines.append("Skipped:    {} on off/locked sublayers".format(total["blocked"]))
    if total["failed"]:
        lines.append("Failed:     {} couldn't be selected (other space/viewport?)".format(total["failed"]))
    lines.append("-" * len(lines[0]))
    print("\n".join(lines))


def main():
    doc = sc.doc
    obj_id = rs.GetObject("Pick object to match layer", preselect=True)
    if obj_id is None:
        return

    rh_obj = doc.Objects.FindId(obj_id)
    if rh_obj is None:
        print("{}: couldn't resolve picked object.".format(TAG))
        return

    layer = doc.Layers.FindIndex(rh_obj.Attributes.LayerIndex)
    if layer is None or layer.IsDeleted:
        print("{}: layer not found.".format(TAG))
        return

    rs.UnselectAllObjects()
    parent = select_on_layer(doc, layer)
    doc.Views.Redraw()                      # show parent selection before prompting

    subs = descendant_layers(layer)
    sub = dict.fromkeys(FIELDS, 0)
    included = False
    if subs and ask_sublayers(parent["selected"], len(subs)):
        included = True
        for sl in subs:
            sub = add_counts(sub, select_on_layer(doc, sl))
        doc.Views.Redraw()

    # Hidden/locked on sublayers only counted if included; otherwise sub stays zero.
    print_report(layer, subs, included, parent, sub)


if __name__ == "__main__":
    main()
