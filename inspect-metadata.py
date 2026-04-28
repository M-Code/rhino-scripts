#! python3
"""
inspect-metadata

Semi-modal Eto dialog that displays selected objects' Name, Layer, and all
UserText keys in a sortable, resizable grid. Toggle individual column visibility
with checkboxes; click a row to highlight the object in the viewport; copy the
visible data to clipboard as TSV for pasting directly into a spreadsheet.
"""
import Rhino
import Rhino.UI
import rhinoscriptsyntax as rs
import scriptcontext as sc
import Eto.Forms as forms
import Eto.Drawing as drawing
import System


BUILTIN_COLS = ["Name", "Layer", "ID"]


def collect_data(obj_ids):
    all_keys = set()
    for obj in obj_ids:
        keys = rs.GetUserText(obj)
        if keys:
            all_keys.update(keys)

    key_list = sorted(all_keys)
    columns = ["Name", "Layer"] + key_list + ["ID"]

    rows = []
    for obj in obj_ids:
        row = [
            rs.ObjectName(obj) or "",
            rs.ObjectLayer(obj) or "",
        ]
        for k in key_list:
            val = rs.GetUserText(obj, k)
            row.append(val if val is not None else "")
        row.append(str(obj))
        rows.append(row)

    return columns, rows


class InspectMetadataDialog(forms.Dialog[bool]):

    def __init__(self, columns, rows):
        super().__init__()
        self.columns = columns
        self.rows = rows
        self.grid_columns = []
        self.col_checkboxes = []
        self._id_col_idx = columns.index("ID")
        self._sort_col = -1
        self._sort_asc = True

        self.Title = "Object Metadata  —  {0} object(s)".format(len(rows))
        self.Resizable = True
        self.ClientSize = drawing.Size(860, 560)
        self.Padding = drawing.Padding(8)

        self._build_ui()

    def _build_ui(self):
        self.grid = forms.GridView()
        self.grid.ShowHeader = True
        self.grid.AllowMultipleSelection = True
        self.grid.AllowColumnReordering = True
        self.grid.GridLines = forms.GridLines.Both
        self.grid.GridLineColor = drawing.Color.FromArgb(180, 180, 180)

        for i, col_name in enumerate(self.columns):
            gc = forms.GridColumn()
            gc.HeaderText = col_name
            gc.DataCell = forms.TextBoxCell(i)
            gc.Editable = False
            gc.Sortable = True
            gc.Width = 260 if col_name == "ID" else 160 if col_name in BUILTIN_COLS else 130
            self.grid.Columns.Add(gc)
            self.grid_columns.append(gc)

        self.grid.DataStore = [System.Array[System.String](row) for row in self.rows]
        self.grid.SelectionChanged += self.on_selection_changed
        self.grid.ColumnHeaderClick += self.on_column_header_click

        builtin_cbs = forms.StackLayout()
        builtin_cbs.Orientation = forms.Orientation.Horizontal
        builtin_cbs.Spacing = 14
        builtin_cbs.Padding = drawing.Padding(4, 2)

        ut_cbs = forms.StackLayout()
        ut_cbs.Orientation = forms.Orientation.Horizontal
        ut_cbs.Spacing = 14
        ut_cbs.Padding = drawing.Padding(4, 2)

        for i, col_name in enumerate(self.columns):
            cb = forms.CheckBox()
            cb.Text = col_name
            cb.Checked = True
            cb.CheckedChanged += self.on_col_toggle
            self.col_checkboxes.append((cb, i))
            if col_name in BUILTIN_COLS:
                builtin_cbs.Items.Add(forms.StackLayoutItem(cb, False))
            else:
                ut_cbs.Items.Add(forms.StackLayoutItem(cb, False))

        def labeled_row(label_text, content, scrollable=False):
            lbl = forms.Label()
            lbl.Text = label_text
            lbl.Width = 72
            lbl.Font = drawing.Font("Segoe UI", 8, drawing.FontStyle.Bold)
            lbl.VerticalAlignment = forms.VerticalAlignment.Center
            if scrollable:
                scr = forms.Scrollable()
                scr.Content = content
                scr.Height = 30
                content = scr
            row = forms.TableLayout()
            row.Spacing = drawing.Size(6, 0)
            row.Rows.Add(forms.TableRow(
                forms.TableCell(lbl, False),
                forms.TableCell(content, True)
            ))
            return row

        toggle_panel = forms.StackLayout()
        toggle_panel.Orientation = forms.Orientation.Vertical
        toggle_panel.Spacing = 4
        toggle_panel.Padding = drawing.Padding(0, 2)
        toggle_panel.Items.Add(forms.StackLayoutItem(labeled_row("Built-in:", builtin_cbs), True))

        ut_col_count = sum(1 for c in self.columns if c not in BUILTIN_COLS)
        if ut_col_count > 0:
            toggle_panel.Items.Add(forms.StackLayoutItem(labeled_row("User Text:", ut_cbs, scrollable=True), True))

        self.copy_btn = forms.Button()
        self.copy_btn.Text = "Copy to Spreadsheet"
        self.copy_btn.Click += self.on_copy

        close_btn = forms.Button()
        close_btn.Text = "Close"
        close_btn.Width = 80
        close_btn.Click += lambda s, e: self.Close(True)
        self.DefaultButton = close_btn

        btn_row = forms.StackLayout()
        btn_row.Orientation = forms.Orientation.Horizontal
        btn_row.Spacing = 8
        btn_row.Items.Add(forms.StackLayoutItem(self.copy_btn, False))
        btn_row.Items.Add(forms.StackLayoutItem(None, True))
        btn_row.Items.Add(forms.StackLayoutItem(close_btn, False))

        layout = forms.TableLayout()
        layout.Spacing = drawing.Size(4, 6)
        layout.Rows.Add(forms.TableRow(forms.TableCell(toggle_panel, True)))

        grid_row = forms.TableRow()
        grid_row.ScaleHeight = True
        grid_row.Cells.Add(forms.TableCell(self.grid, True))
        layout.Rows.Add(grid_row)

        layout.Rows.Add(forms.TableRow(forms.TableCell(btn_row, True)))
        self.Content = layout

    def _visible_cols_in_display_order(self):
        col_index = {name: i for i, name in enumerate(self.columns)}
        try:
            native = self.grid.Handler.Control
            native_cols = sorted(native.Columns, key=lambda c: c.DisplayIndex)
            return [(col_index[str(c.Header)], str(c.Header))
                    for c in native_cols
                    if str(c.Header) in col_index
                    and self.grid_columns[col_index[str(c.Header)]].Visible]
        except Exception as ex:
            print("column order fallback:", ex)
            return [(i, name) for i, (name, gc) in
                    enumerate(zip(self.columns, self.grid_columns)) if gc.Visible]

    def on_copy(self, sender, e):
        visible = self._visible_cols_in_display_order()
        lines = ["\t".join(name for _, name in visible)]
        for row in self.grid.DataStore:
            lines.append("\t".join(row[i] or "" for i, _ in visible))
        forms.Clipboard.Instance.Text = "\n".join(lines)

        self.copy_btn.Text = "Copied!"
        timer = forms.UITimer()
        timer.Interval = 3
        def on_tick(s, ev):
            self.copy_btn.Text = "Copy to Spreadsheet"
            timer.Stop()
        timer.Elapsed += on_tick
        timer.Start()

    def on_selection_changed(self, sender, e):
        items = list(self.grid.SelectedItems)
        rs.UnselectAllObjects()
        if items:
            ids = [item[self._id_col_idx] for item in items]
            rs.SelectObjects(ids)
        sc.doc.Views.Redraw()

    def on_column_header_click(self, sender, e):
        col_idx = next((i for i, gc in enumerate(self.grid_columns) if gc == e.Column), None)
        if col_idx is None:
            return
        if self._sort_col == col_idx:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col_idx
            self._sort_asc = True

        def sort_key(row):
            val = (row[col_idx] or "").strip()
            try:
                return (0, float(val), "")
            except ValueError:
                return (1, 0.0, val.lower())

        data = sorted(self.grid.DataStore, key=sort_key, reverse=not self._sort_asc)
        self.grid.DataStore = data

    def on_col_toggle(self, sender, e):
        for cb, i in self.col_checkboxes:
            if cb == sender:
                self.grid_columns[i].Visible = bool(cb.Checked)
                break


def main():
    obj_ids = rs.GetObjects("Select objects to inspect", preselect=True)
    if not obj_ids:
        return

    columns, rows = collect_data(obj_ids)

    dialog = InspectMetadataDialog(columns, rows)
    Rhino.UI.EtoExtensions.ShowSemiModal(dialog, sc.doc, Rhino.UI.RhinoEtoApp.MainWindow)


if __name__ == "__main__":
    main()
