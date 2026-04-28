# -*- coding: utf-8 -*-
"""
build_cut_list

Selects curves/edges, groups total lengths by parent object, reads each object's
"Location" UserText (fwd / cab / aft), converts lengths to inches, floors to the
nearest 1/16", and shows a formatted cut list in a popup window. Also places
TextDot labels in the viewport and provides a "Copy to Sheets" TSV clipboard export.
"""

import rhinoscriptsyntax as rs
import scriptcontext as sc
import Rhino
import math
import datetime
import System.Windows.Forms as WinForms
import System.Drawing as Drawing


LOCATION_KEY   = "Location"
LOCATION_ORDER = ["fwd", "cab", "aft"]

LABEL_LAYER    = "CutList_Labels"


def to_inches(value):
    meters_per_unit = Rhino.RhinoMath.UnitScale(
        sc.doc.ModelUnitSystem, Rhino.UnitSystem.Meters
    )
    inches_per_meter = 39.3701
    return value * meters_per_unit * inches_per_meter


def floor_to_sixteenth(inches):
    return math.floor(inches * 16.0) / 16.0


def _fmt(inches):
    s = '{:.4f}'.format(inches).rstrip('0').rstrip('.')
    return s + '"'


def get_location(obj_id):
    val = rs.GetUserText(obj_id, LOCATION_KEY)
    if val:
        return val.strip().lower()
    return "(no location)"


def get_lengths_grouped_by_parent():
    parent_lengths = {}
    parent_longest = {}

    go = Rhino.Input.Custom.GetObject()
    go.SetCommandPrompt("Select curves or sub-object edges")
    go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve | Rhino.DocObjects.ObjectType.EdgeFilter
    go.SubObjectSelect = True
    go.GetMultiple(1, 0)

    if go.CommandResult() != Rhino.Commands.Result.Success:
        return None, None

    for i in range(go.ObjectCount):
        obj_ref   = go.Object(i)
        parent_id = obj_ref.ObjectId

        length   = 0.0
        midpoint = None

        edge = obj_ref.Edge()
        if edge:
            length   = edge.GetLength()
            midpoint = edge.PointAtNormalizedLength(0.5)
        else:
            curve = obj_ref.Curve()
            if curve:
                length   = curve.GetLength()
                midpoint = curve.PointAtNormalizedLength(0.5)

        if length > 0 and midpoint is not None:
            parent_lengths[parent_id] = parent_lengths.get(parent_id, 0.0) + length

            if parent_id not in parent_longest or length > parent_longest[parent_id][0]:
                parent_longest[parent_id] = (length, midpoint)

    dot_candidates = []
    for parent_id, raw_length in parent_lengths.items():
        if parent_id in parent_longest:
            _, midpoint = parent_longest[parent_id]
            dot_candidates.append((midpoint, raw_length))

    return parent_lengths, dot_candidates


def build_report(data, sorted_locations, grand_total_pieces,
                 grand_total_inches, skipped):
    lines = []
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    doc_name  = sc.doc.Name if sc.doc.Name else "Unsaved Document"

    lines.append("")
    lines.append("=" * 50)
    lines.append("  CUT LIST")
    lines.append("  Floored to nearest 1/16\" | Sorted by Location > Length")
    lines.append("  Document  : {}".format(doc_name))
    lines.append("  Generated : {}".format(timestamp))
    lines.append("=" * 50)

    for location in sorted_locations:
        length_counts  = data[location]
        sorted_lengths = sorted(length_counts.keys())

        loc_pieces = sum(length_counts.values())
        loc_inches = floor_to_sixteenth(
            sum(k * v for k, v in length_counts.items())
        )

        lines.append("")
        lines.append("  LOCATION: {}".format(location.upper()))
        lines.append("  " + "-" * 46)
        lines.append("  {:<12}  {:<10}  {}".format("LOCATION", "QTY", "LENGTH"))
        lines.append("  " + "-" * 46)

        for length in sorted_lengths:
            qty = length_counts[length]
            lines.append("  {:<12}  {:<10}  {}".format(
                location, qty, _fmt(length)
            ))

        lines.append("  " + "-" * 46)
        lines.append("  Pieces: {}    Subtotal: {}".format(
            loc_pieces, _fmt(loc_inches)
        ))

    lines.append("")
    lines.append("=" * 50)
    if skipped:
        lines.append("  Skipped (no geometry / zero length) : {}".format(skipped))
    lines.append("  GRAND TOTAL PIECES                  : {}".format(grand_total_pieces))
    lines.append("  GRAND TOTAL LENGTH                  : {}".format(
        _fmt(floor_to_sixteenth(grand_total_inches))
    ))
    lines.append("=" * 50)
    lines.append("")

    return lines


def build_tsv_text(data, sorted_locations):
    rows = []
    for location in sorted_locations:
        length_counts  = data[location]
        sorted_lengths = sorted(length_counts.keys())
        for length in sorted_lengths:
            qty = length_counts[length]
            rows.append("{}\t{}\t{}".format(location, qty, _fmt(length)))
    return "\r\n".join(rows)


def ensure_label_layer():
    layer_index = sc.doc.Layers.FindByFullPath(LABEL_LAYER, -1)
    if layer_index < 0:
        layer        = Rhino.DocObjects.Layer()
        layer.Name   = LABEL_LAYER
        layer.Color  = Drawing.Color.Cyan
        layer_index  = sc.doc.Layers.Add(layer)
    return layer_index


def place_text_dots(dot_candidates):
    layer_index = ensure_label_layer()

    attr             = Rhino.DocObjects.ObjectAttributes()
    attr.LayerIndex  = layer_index

    added = 0
    for (point, raw_length) in dot_candidates:
        floored = floor_to_sixteenth(to_inches(raw_length))
        if floored <= 0:
            continue
        label = _fmt(floored)
        dot   = Rhino.Geometry.TextDot(label, point)
        sc.doc.Objects.AddTextDot(dot, attr)
        added += 1

    sc.doc.Views.Redraw()
    print("  Placed {} length label(s) on layer '{}'.".format(added, LABEL_LAYER))


def show_popup(lines, tsv_text):
    form            = WinForms.Form()
    form.Text       = "Cut List Results"
    form.Width      = 480
    form.Height     = 600
    form.MinimumSize   = Drawing.Size(360, 300)
    form.StartPosition = WinForms.FormStartPosition.CenterScreen

    textbox             = WinForms.TextBox()
    textbox.Multiline   = True
    textbox.ScrollBars  = WinForms.ScrollBars.Vertical
    textbox.ReadOnly    = True
    textbox.Font        = Drawing.Font("Courier New", 9)
    textbox.Dock        = WinForms.DockStyle.Fill
    textbox.Text        = "\r\n".join(lines)

    btn_panel        = WinForms.Panel()
    btn_panel.Dock   = WinForms.DockStyle.Bottom
    btn_panel.Height = 36

    copy_btn         = WinForms.Button()
    copy_btn.Text    = "Copy to Sheets"
    copy_btn.Width   = 130
    copy_btn.Height  = 30
    copy_btn.Left    = 4
    copy_btn.Top     = 3

    close_btn        = WinForms.Button()
    close_btn.Text   = "Close"
    close_btn.Width  = 80
    close_btn.Height = 30
    close_btn.Left   = 140
    close_btn.Top    = 3

    def on_copy(s, e):
        WinForms.Clipboard.SetText(tsv_text)
        copy_btn.Text = "Copied!"

    copy_btn.Click  += on_copy
    close_btn.Click += lambda s, e: form.Close()

    btn_panel.Controls.Add(copy_btn)
    btn_panel.Controls.Add(close_btn)

    form.Controls.Add(textbox)
    form.Controls.Add(btn_panel)

    form.ShowDialog()


def main():
    parent_lengths, dot_candidates = get_lengths_grouped_by_parent()

    if parent_lengths is None:
        print("No geometry selected.")
        return

    if not parent_lengths:
        print("No valid edges or curves selected.")
        return

    skipped = 0
    data    = {}

    for obj_id, raw_length in parent_lengths.items():
        inches  = to_inches(raw_length)
        floored = floor_to_sixteenth(inches)

        if floored <= 0:
            skipped += 1
            continue

        location = get_location(obj_id)

        if location not in data:
            data[location] = {}
        data[location][floored] = data[location].get(floored, 0) + 1

    if not data:
        print("No valid lengths found.")
        return

    known            = [l for l in LOCATION_ORDER if l in data]
    unknown          = sorted([l for l in data if l not in LOCATION_ORDER])
    sorted_locations = known + unknown

    grand_total_pieces = sum(sum(lc.values()) for lc in data.values())
    grand_total_inches = sum(k * v for lc in data.values() for k, v in lc.items())

    lines    = build_report(
        data, sorted_locations,
        grand_total_pieces, grand_total_inches, skipped
    )
    tsv_text = build_tsv_text(data, sorted_locations)

    for line in lines:
        print(line)

    place_text_dots(dot_candidates)
    show_popup(lines, tsv_text)


if __name__ == "__main__":
    main()
