#! python3
"""
select-by-user-text-with-search

Semi-modal Eto dialog for selecting objects by UserText key and value.
Pick a key from the dropdown, then check one or more values to live-highlight
matching objects in the viewport. Supports a search box to filter keys/values.
Viewport stays fully interactive (zoom/orbit/pan) while the dialog is open.
"""
import Rhino
import Rhino.UI
import rhinoscriptsyntax as rs
import scriptcontext as sc
import Eto.Forms as forms
import Eto.Drawing as drawing


def make_list_item(text, key):
    item = forms.ListItem()
    item.Text = text
    item.Key = key
    return item


class SelectByUserTextDialog(forms.Dialog[bool]):

    def __init__(self, key_val_map):
        super().__init__()
        self.key_val_map = key_val_map
        self.Title = "Select by User Text"
        self.Padding = drawing.Padding(8, 8, 8, 12)
        self.Resizable = True
        self.ClientSize = drawing.Size(360, 560)
        self.result_key = None
        self.result_vals = []
        self.original_selection = rs.SelectedObjects() or []
        self.checkboxes = []

        self.search_box = forms.SearchBox()
        self.search_box.PlaceholderText = "Filter keys and values…"
        self.search_box.Height = 28
        self.search_box.TextChanged += self.on_search_changed

        self.key_dropdown = forms.DropDown()
        self.key_dropdown.Height = 28
        self.key_dropdown.SelectedIndexChanged += self.on_key_changed

        self.select_all_cb = forms.CheckBox()
        self.select_all_cb.Text = "Select all"
        self.select_all_cb.CheckedChanged += self.on_select_all

        self.val_panel = forms.Scrollable()
        self.val_panel.ExpandContentWidth = True
        self.val_panel.Height = 340
        self.val_layout = forms.StackLayout()
        self.val_layout.Orientation = forms.Orientation.Vertical
        self.val_layout.Spacing = 4
        self.val_layout.Padding = drawing.Padding(4)
        self.val_panel.Content = self.val_layout
        self._rebuild_keys()

        ok_btn = forms.Button()
        ok_btn.Text = "OK"
        ok_btn.Click += self.on_ok
        cancel_btn = forms.Button()
        cancel_btn.Text = "Cancel"
        cancel_btn.Click += self.on_cancel
        self.DefaultButton = ok_btn
        self.AbortButton = cancel_btn

        btn_layout = forms.StackLayout()
        btn_layout.Orientation = forms.Orientation.Horizontal
        btn_layout.Spacing = 8
        btn_layout.Items.Add(forms.StackLayoutItem(None, True))
        btn_layout.Items.Add(forms.StackLayoutItem(ok_btn, False))
        btn_layout.Items.Add(forms.StackLayoutItem(cancel_btn, False))

        layout = forms.DynamicLayout()
        layout.DefaultSpacing = drawing.Size(4, 6)
        layout.Padding = drawing.Padding(4)
        layout.AddRow(self.search_box)
        key_label = forms.Label()
        key_label.Text = "Attribute key:"
        layout.AddRow(key_label)
        layout.AddRow(self.key_dropdown)
        val_label = forms.Label()
        val_label.Text = "Values:"
        layout.AddRow(val_label)
        layout.AddRow(self.select_all_cb)
        layout.AddRow(self.val_panel)
        layout.AddRow(None)
        layout.AddRow(btn_layout)
        self.Content = layout

    def _filter_term(self):
        return (self.search_box.Text or "").strip().lower()

    def _rebuild_keys(self):
        term = self._filter_term()
        prev_key = None
        if self.key_dropdown.SelectedIndex >= 0:
            prev_key = self.key_dropdown.Items[self.key_dropdown.SelectedIndex].Key

        self.key_dropdown.Items.Clear()
        restore_index = -1
        for k in sorted(self.key_val_map.keys()):
            val_map = self.key_val_map[k]
            if term:
                key_hit = term in k.lower()
                val_hit = any(term in v.lower() for v in val_map.keys())
                if not key_hit and not val_hit:
                    continue
            n = sum(len(ids) for ids in val_map.values())
            self.key_dropdown.Items.Add(make_list_item(f"{k}  ({n} objects)", k))
            if k == prev_key:
                restore_index = self.key_dropdown.Items.Count - 1

        if self.key_dropdown.Items.Count > 0:
            self.key_dropdown.SelectedIndex = restore_index if restore_index >= 0 else 0
        else:
            self._rebuild_values()  # clears value list and deselects

    def _rebuild_values(self):
        term = self._filter_term()
        self.val_layout.Items.Clear()
        self.checkboxes = []
        self.select_all_cb.Checked = False

        if self.key_dropdown.SelectedIndex < 0:
            rs.UnselectAllObjects()
            sc.doc.Views.Redraw()
            return

        key = self.key_dropdown.Items[self.key_dropdown.SelectedIndex].Key
        val_map = self.key_val_map[key]
        key_matched = not term or term in key.lower()

        for v in sorted(val_map.keys()):
            if not key_matched and term not in v.lower():
                continue
            cb = forms.CheckBox()
            cb.Text = f"{v}  ({len(val_map[v])})"
            cb.CheckedChanged += self.on_checkbox_changed
            self.checkboxes.append((cb, v))
            self.val_layout.Items.Add(forms.StackLayoutItem(cb, False))

        rs.UnselectAllObjects()
        sc.doc.Views.Redraw()

    def on_search_changed(self, sender, e):
        self._rebuild_keys()

    def on_select_all(self, sender, e):
        checked = self.select_all_cb.Checked
        for cb, val in self.checkboxes:
            cb.Checked = checked
        self.on_checkbox_changed(sender, e)

    def on_key_changed(self, sender, e):
        self._rebuild_values()

    def on_checkbox_changed(self, sender, e):
        if self.key_dropdown.SelectedIndex < 0:
            return
        key = self.key_dropdown.Items[self.key_dropdown.SelectedIndex].Key
        matches = []
        for cb, val in self.checkboxes:
            if cb.Checked:
                matches.extend(self.key_val_map[key][val])
        rs.UnselectAllObjects()
        if matches:
            rs.SelectObjects(matches)
        sc.doc.Views.Redraw()

    def on_ok(self, sender, e):
        if self.key_dropdown.SelectedIndex >= 0:
            self.result_key = self.key_dropdown.Items[self.key_dropdown.SelectedIndex].Key
            self.result_vals = [val for cb, val in self.checkboxes if cb.Checked]
        self.Close(True)

    def on_cancel(self, sender, e):
        rs.UnselectAllObjects()
        if self.original_selection:
            rs.SelectObjects(self.original_selection)
        sc.doc.Views.Redraw()
        self.Close(False)


def select_by_user_text():
    all_objects = rs.AllObjects()
    if not all_objects:
        print("No objects in document.")
        return

    key_val_map = {}
    for obj in all_objects:
        keys = rs.GetUserText(obj)
        if not keys:
            continue
        for key in keys:
            val = rs.GetUserText(obj, key)
            if key not in key_val_map:
                key_val_map[key] = {}
            if val not in key_val_map[key]:
                key_val_map[key][val] = []
            key_val_map[key][val].append(obj)

    if not key_val_map:
        print("No objects have user text attributes.")
        return

    dialog = SelectByUserTextDialog(key_val_map)
    Rhino.UI.EtoExtensions.ShowSemiModal(dialog, sc.doc, Rhino.UI.RhinoEtoApp.MainWindow)

    if dialog.result_key and dialog.result_vals:
        matches = []
        for val in dialog.result_vals:
            matches.extend(key_val_map[dialog.result_key][val])
        rs.UnselectAllObjects()
        rs.SelectObjects(matches)
        vals_str = ", ".join(dialog.result_vals)
        print(f"Selected {len(matches)} object(s) where {dialog.result_key} in [{vals_str}].")


if __name__ == "__main__":
    select_by_user_text()
