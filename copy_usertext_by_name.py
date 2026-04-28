"""
copy_usertext_by_name

Finds pairs of objects that share the same object name — one with UserText and
one without — and copies all UserText keys from the source to the target(s).
A dialog lets you review each pair, highlight objects in the viewport, and
selectively check which pairs to apply before committing any changes.
"""

import rhinoscriptsyntax as rs
import scriptcontext as sc
import Rhino
import System
import System.Windows.Forms as WinForms
import System.Drawing as Drawing


class RhinoOwner(WinForms.IWin32Window):
    def __init__(self):
        self._handle = Rhino.RhinoApp.MainWindowHandle()

    @property
    def Handle(self):
        return self._handle


def get_user_text_dict(obj_id):
    keys = rs.GetUserText(obj_id)
    if not keys:
        return {}
    return {k: rs.GetUserText(obj_id, k) for k in keys}


def build_pairs():
    all_objects = rs.AllObjects()
    if not all_objects:
        return [], []

    name_groups = {}
    for obj_id in all_objects:
        name = rs.ObjectName(obj_id)
        if name:
            if name not in name_groups:
                name_groups[name] = []
            name_groups[name].append(obj_id)

    pairs = []
    skipped = []

    for name, obj_ids in name_groups.items():
        if len(obj_ids) < 2:
            continue

        sources = []
        targets = []
        for oid in obj_ids:
            ud = get_user_text_dict(oid)
            if ud:
                sources.append((oid, ud))
            else:
                targets.append(oid)

        if not sources:
            skipped.append((name, "no user text on any object"))
            continue
        if not targets:
            skipped.append((name, "all objects already have user text"))
            continue
        if len(sources) > 1:
            skipped.append((name, "{0} objects have user text - ambiguous source".format(len(sources))))
            continue

        source_id, source_text = sources[0]
        pairs.append((name, source_id, targets, source_text))

    return pairs, skipped


class PairDialog(WinForms.Form):

    def __init__(self, pairs, skipped):
        self.pairs = pairs
        self.skipped = skipped
        self.applied = False
        self.checked_indices = []
        self._build_ui()

    def _build_ui(self):
        self.Text = "User Text Copy  -  {0} pairs ready".format(len(self.pairs))
        self.Size = Drawing.Size(780, 560)
        self.MinimumSize = Drawing.Size(600, 400)

        top = WinForms.Label()
        top.Text = "Click a row to highlight objects in viewport. Check the pairs you want to apply."
        top.Dock = WinForms.DockStyle.Top
        top.Height = 26
        top.Padding = WinForms.Padding(6, 0, 0, 0)
        top.TextAlign = Drawing.ContentAlignment.MiddleLeft
        top.BackColor = Drawing.Color.FromArgb(230, 230, 230)

        split = WinForms.SplitContainer()
        split.Dock = WinForms.DockStyle.Fill
        self._split = split

        left_lbl = WinForms.Label()
        left_lbl.Text = "Pairs  ({0} total)".format(len(self.pairs))
        left_lbl.Dock = WinForms.DockStyle.Top
        left_lbl.Height = 22
        left_lbl.Padding = WinForms.Padding(4, 0, 0, 0)
        left_lbl.Font = Drawing.Font("Segoe UI", 8, Drawing.FontStyle.Bold)

        self.pair_list = WinForms.CheckedListBox()
        self.pair_list.Dock = WinForms.DockStyle.Fill
        self.pair_list.CheckOnClick = False
        self.pair_list.Font = Drawing.Font("Consolas", 9)

        for name, src, tgts, txt in self.pairs:
            entry = "{0}   [{1} key{2}, {3} target{4}]".format(
                name,
                len(txt), "" if len(txt) == 1 else "s",
                len(tgts), "" if len(tgts) == 1 else "s"
            )
            self.pair_list.Items.Add(entry)

        for i in range(self.pair_list.Items.Count):
            self.pair_list.SetItemChecked(i, True)

        self.pair_list.SelectedIndexChanged += self._on_select
        self.pair_list.ItemCheck += self._on_item_check

        split.Panel1.Controls.Add(self.pair_list)
        split.Panel1.Controls.Add(left_lbl)

        right_lbl = WinForms.Label()
        right_lbl.Text = "Details"
        right_lbl.Dock = WinForms.DockStyle.Top
        right_lbl.Height = 22
        right_lbl.Padding = WinForms.Padding(4, 0, 0, 0)
        right_lbl.Font = Drawing.Font("Segoe UI", 8, Drawing.FontStyle.Bold)

        self.detail = WinForms.RichTextBox()
        self.detail.Dock = WinForms.DockStyle.Fill
        self.detail.ReadOnly = True
        self.detail.Font = Drawing.Font("Consolas", 9)
        self.detail.BackColor = Drawing.Color.FromArgb(250, 250, 250)
        self.detail.BorderStyle = WinForms.BorderStyle.None
        self.detail.Text = "Click a pair on the left to see details."

        split.Panel2.Controls.Add(self.detail)
        split.Panel2.Controls.Add(right_lbl)

        bottom = WinForms.Panel()
        bottom.Dock = WinForms.DockStyle.Bottom
        bottom.Height = 46
        bottom.Padding = WinForms.Padding(6, 8, 6, 0)
        bottom.BackColor = Drawing.Color.FromArgb(240, 240, 240)

        self.status_lbl = WinForms.Label()
        self.status_lbl.Dock = WinForms.DockStyle.Left
        self.status_lbl.Width = 130
        self.status_lbl.TextAlign = Drawing.ContentAlignment.MiddleLeft
        self._refresh_status(len(self.pairs))

        btn_all = WinForms.Button()
        btn_all.Text = "Check All"
        btn_all.Width = 80
        btn_all.Dock = WinForms.DockStyle.Left
        btn_all.Click += self._on_check_all

        btn_none = WinForms.Button()
        btn_none.Text = "Uncheck All"
        btn_none.Width = 85
        btn_none.Dock = WinForms.DockStyle.Left
        btn_none.Click += self._on_check_none

        btn_cancel = WinForms.Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.Width = 80
        btn_cancel.Dock = WinForms.DockStyle.Right
        btn_cancel.Click += self._on_cancel

        btn_apply = WinForms.Button()
        btn_apply.Text = "Apply Checked"
        btn_apply.Width = 110
        btn_apply.Dock = WinForms.DockStyle.Right
        btn_apply.Font = Drawing.Font(btn_apply.Font, Drawing.FontStyle.Bold)
        btn_apply.Click += self._on_apply

        bottom.Controls.Add(self.status_lbl)
        bottom.Controls.Add(btn_none)
        bottom.Controls.Add(btn_all)
        bottom.Controls.Add(btn_cancel)
        bottom.Controls.Add(btn_apply)

        self.Controls.Add(split)
        self.Controls.Add(bottom)
        self.Controls.Add(top)

        self.FormClosing += self._on_closing
        self.Load += self._on_load

    def _on_load(self, sender, e):
        self._split.SplitterDistance = self._split.Width / 2

    def _refresh_status(self, count):
        self.status_lbl.Text = "{0} / {1} checked".format(count, len(self.pairs))

    def _on_select(self, sender, e):
        idx = self.pair_list.SelectedIndex
        if idx < 0 or idx >= len(self.pairs):
            return

        name, source_id, targets, source_text = self.pairs[idx]

        rs.UnselectAllObjects()
        rs.SelectObjects([source_id] + targets)
        sc.doc.Views.Redraw()

        lines = []
        lines.append("Name:    {0}".format(name))
        lines.append("")
        lines.append("Source:  {0}".format(source_id))
        lines.append("")
        lines.append("Target{0} ({1}):".format("s" if len(targets) != 1 else "", len(targets)))
        for t in targets:
            lines.append("  {0}".format(t))
        lines.append("")
        lines.append("Keys to copy ({0}):".format(len(source_text)))
        lines.append("-" * 34)
        for k, v in source_text.items():
            lines.append("  {0}".format(k))
            lines.append("    = {0}".format(v))

        self.detail.Text = "\n".join(lines)

    def _on_item_check(self, sender, e):
        current = sum(1 for i in range(self.pair_list.Items.Count)
                      if self.pair_list.GetItemChecked(i))
        if e.NewValue == WinForms.CheckState.Checked:
            current += 1
        elif e.NewValue == WinForms.CheckState.Unchecked:
            current -= 1
        self._refresh_status(current)

    def _on_check_all(self, sender, e):
        for i in range(self.pair_list.Items.Count):
            self.pair_list.SetItemChecked(i, True)
        self._refresh_status(len(self.pairs))

    def _on_check_none(self, sender, e):
        for i in range(self.pair_list.Items.Count):
            self.pair_list.SetItemChecked(i, False)
        self._refresh_status(0)

    def _on_apply(self, sender, e):
        indices = [i for i in range(self.pair_list.Items.Count)
                   if self.pair_list.GetItemChecked(i)]
        if not indices:
            WinForms.MessageBox.Show("No pairs are checked.", "Nothing to Apply",
                                     WinForms.MessageBoxButtons.OK,
                                     WinForms.MessageBoxIcon.Warning)
            return
        self.checked_indices = indices
        self.applied = True
        self.Close()

    def _on_cancel(self, sender, e):
        self.applied = False
        self.Close()

    def _on_closing(self, sender, e):
        rs.UnselectAllObjects()
        sc.doc.Views.Redraw()


def main():
    pairs, skipped = build_pairs()

    if not pairs:
        WinForms.MessageBox.Show(
            "No valid pairs found.\n\nMake sure objects sharing a name have exactly one with user text.",
            "No Pairs Found",
            WinForms.MessageBoxButtons.OK,
            WinForms.MessageBoxIcon.Information
        )
        if skipped:
            print("Skipped:")
            for name, reason in skipped:
                print("  {0} - {1}".format(name, reason))
        return

    if skipped:
        print("Skipped groups (shown in command history):")
        for name, reason in skipped:
            print("  {0} - {1}".format(name, reason))

    form = PairDialog(pairs, skipped)
    form.Show(RhinoOwner())

    while form.Visible:
        Rhino.RhinoApp.Wait()

    if not form.applied:
        print("Cancelled - no changes made.")
        return

    updated = 0
    for i in form.checked_indices:
        name, source_id, targets, source_text = pairs[i]
        for target_id in targets:
            for k, v in source_text.items():
                rs.SetUserText(target_id, k, v)
            updated += 1

    print("Done - user text copied to {0} object(s).".format(updated))
    WinForms.MessageBox.Show(
        "Done!\n\nUser text copied to {0} object(s).".format(updated),
        "Complete",
        WinForms.MessageBoxButtons.OK,
        WinForms.MessageBoxIcon.Information
    )


main()
