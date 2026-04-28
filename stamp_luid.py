"""
stamp_luid

Assigns unique sequential integer IDs (LUIDs — local unique identifiers) to selected objects as a "luid"
UserText attribute. Scans the whole document for existing LUIDs, fills any gaps
in the sequence first, then continues from the highest value. A preview dialog
shows which objects will be stamped vs. skipped before any changes are written.
"""

import rhinoscriptsyntax as rs
import System.Windows.Forms as Forms
import System.Drawing as Drawing
import System
import System.Threading
import Rhino


class _RhinoOwner(System.Windows.Forms.IWin32Window):
    def __init__(self):
        self._handle = Rhino.RhinoApp.MainWindowHandle()

    @property
    def Handle(self):
        return self._handle


def get_selection():
    return rs.GetObjects("Select objects to stamp")


def scan_existing_luids():
    result = {}
    all_objects = rs.AllObjects()
    if not all_objects:
        return result
    for obj_id in all_objects:
        val = rs.GetUserText(obj_id, "luid")
        if val:
            try:
                result[obj_id] = int(val)
            except (ValueError, TypeError):
                pass
    return result


def detect_gaps(existing_luids_dict):
    values = list(existing_luids_dict.values())
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    full_range = set(range(lo, hi + 1))
    return sorted(full_range - set(values))


def build_assignment_queue(existing_luids_dict):
    gaps = detect_gaps(existing_luids_dict)
    highest = max(existing_luids_dict.values()) if existing_luids_dict else 0
    continuation_start = highest + 1
    continuation_count = len(gaps) + 500
    continuation = list(range(continuation_start, continuation_start + continuation_count))
    return gaps + continuation


def preview_assignments(selection, existing_luids_dict, assignment_queue):
    queue_copy = assignment_queue[:]
    rows = []
    for obj_id in selection:
        name = rs.ObjectName(obj_id)
        if not name:
            name = str(obj_id)[:8]
        if obj_id in existing_luids_dict:
            rows.append({
                "name": name,
                "obj_id": obj_id,
                "current_luid": existing_luids_dict[obj_id],
                "assigned": None,
                "status": "skip",
            })
        else:
            next_id = queue_copy.pop(0)
            rows.append({
                "name": name,
                "obj_id": obj_id,
                "current_luid": None,
                "assigned": next_id,
                "status": "stamp",
            })
    return rows


class StamperDialog(Forms.Form):
    def __init__(self, existing_luids_dict, gaps, assignment_queue, preview_rows):
        Forms.Form.__init__(self)

        self.user_confirmed = False
        self._preview_rows = preview_rows

        self.Text = "LUID Stamper"
        self.Width = 460
        self.Height = 480
        self.FormBorderStyle = Forms.FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.StartPosition = Forms.FormStartPosition.CenterScreen
        self.TopMost = False

        tagged_count = len(existing_luids_dict)
        gaps_str = ", ".join(str(g) for g in gaps) if gaps else "None"
        queue_preview = assignment_queue[:5]
        queue_str = ", ".join(str(v) for v in queue_preview)
        if len(assignment_queue) > 5:
            queue_str += "..."

        skip_count = sum(1 for r in preview_rows if r["status"] == "skip")
        stamp_count = sum(1 for r in preview_rows if r["status"] == "stamp")

        pad = 12

        doc_box = Forms.GroupBox()
        doc_box.Text = "DOCUMENT"
        doc_box.Left = pad
        doc_box.Top = pad
        doc_box.Width = 420
        doc_box.Height = 80

        lbl_tagged = Forms.Label()
        lbl_tagged.Text = "Tagged objects: {}".format(tagged_count)
        lbl_tagged.Left = 8
        lbl_tagged.Top = 18
        lbl_tagged.Width = 400
        doc_box.Controls.Add(lbl_tagged)

        lbl_gaps = Forms.Label()
        lbl_gaps.Text = "Gaps found: {}".format(gaps_str)
        lbl_gaps.Left = 8
        lbl_gaps.Top = 36
        lbl_gaps.Width = 400
        doc_box.Controls.Add(lbl_gaps)

        lbl_next = Forms.Label()
        lbl_next.Text = "Next assignments: {}".format(queue_str)
        lbl_next.Left = 8
        lbl_next.Top = 54
        lbl_next.Width = 400
        doc_box.Controls.Add(lbl_next)

        self.Controls.Add(doc_box)

        sel_box = Forms.GroupBox()
        sel_box.Text = "YOUR SELECTION  ({} objects)".format(len(preview_rows))
        sel_box.Left = pad
        sel_box.Top = doc_box.Bottom + pad
        sel_box.Width = 420
        sel_box.Height = 290

        lv = Forms.ListView()
        lv.View = Forms.View.Details
        lv.FullRowSelect = True
        lv.GridLines = True
        lv.Left = 8
        lv.Top = 18
        lv.Width = 400
        lv.Height = 200
        lv.HideSelection = False

        lv.Columns.Add("Object", 200)
        lv.Columns.Add("luid", 70)
        lv.Columns.Add("Status", 120)

        blue = Drawing.Color.FromArgb(0, 80, 200)

        for row in preview_rows:
            luid_display = str(row["current_luid"]) if row["current_luid"] is not None else u"\u2014"
            if row["status"] == "skip":
                status_display = u"\u2713 tagged"
            else:
                status_display = u"\u2192 gets: {}".format(row["assigned"])

            item = Forms.ListViewItem(row["name"])
            item.SubItems.Add(luid_display)
            item.SubItems.Add(status_display)
            item.Tag = row["obj_id"]

            if row["status"] == "stamp":
                item.ForeColor = blue

            lv.Items.Add(item)

        lv.SelectedIndexChanged += self._on_lv_selection_changed
        self._lv = lv
        sel_box.Controls.Add(lv)

        lbl_summary_skip = Forms.Label()
        lbl_summary_skip.Text = "{} already tagged (will skip)".format(skip_count)
        lbl_summary_skip.Left = 8
        lbl_summary_skip.Top = lv.Bottom + 8
        lbl_summary_skip.Width = 400
        sel_box.Controls.Add(lbl_summary_skip)

        lbl_summary_stamp = Forms.Label()
        lbl_summary_stamp.Text = "{} untagged (will stamp)".format(stamp_count)
        lbl_summary_stamp.Left = 8
        lbl_summary_stamp.Top = lbl_summary_skip.Bottom + 2
        lbl_summary_stamp.Width = 400
        sel_box.Controls.Add(lbl_summary_stamp)

        self.Controls.Add(sel_box)

        btn_cancel = Forms.Button()
        btn_cancel.Text = "Cancel"
        btn_cancel.Width = 90
        btn_cancel.Left = pad
        btn_cancel.Top = sel_box.Bottom + pad
        btn_cancel.Click += self._on_cancel
        self.Controls.Add(btn_cancel)

        btn_stamp = Forms.Button()
        btn_stamp.Text = "Stamp"
        btn_stamp.Width = 90
        btn_stamp.Left = self.ClientSize.Width - 90 - pad
        btn_stamp.Top = sel_box.Bottom + pad
        btn_stamp.Click += self._on_stamp
        self.Controls.Add(btn_stamp)

        self.FormClosing += self._on_closing

    def _on_lv_selection_changed(self, sender, e):
        rs.UnselectAllObjects()
        if sender.SelectedItems.Count > 0:
            obj_id = sender.SelectedItems[0].Tag
            if obj_id:
                rs.SelectObject(obj_id)
                rs.Redraw()

    def _on_cancel(self, sender, e):
        self.user_confirmed = False
        self.Close()

    def _on_stamp(self, sender, e):
        self.user_confirmed = True
        self.Close()

    def _on_closing(self, sender, e):
        rs.UnselectAllObjects()
        rs.Redraw()


def stamp_objects(selection, assignment_queue):
    stamped_count = 0
    assigned_ids = []
    queue = assignment_queue[:]
    for obj_id in selection:
        existing_val = rs.GetUserText(obj_id, "luid")
        if existing_val:
            try:
                int(existing_val)
                continue
            except (ValueError, TypeError):
                pass
        next_id = queue.pop(0)
        rs.SetUserText(obj_id, "luid", str(next_id))
        stamped_count += 1
        assigned_ids.append(next_id)
    return {"stamped_count": stamped_count, "assigned_ids": assigned_ids}


def RunCommand():
    selection = get_selection()
    if selection is None:
        print("No objects selected. Exiting.")
        return

    existing = scan_existing_luids()
    queue = build_assignment_queue(existing)
    preview = preview_assignments(selection, existing, queue)

    gaps = detect_gaps(existing)
    dialog = StamperDialog(existing, gaps, queue, preview)
    dialog.Show(_RhinoOwner())
    while not dialog.IsDisposed:
        Forms.Application.DoEvents()
        System.Threading.Thread.Sleep(10)
    if not dialog.user_confirmed:
        print("LUID Stamper cancelled.")
        return

    result = stamp_objects(selection, queue)

    if result["stamped_count"] == 0:
        print("All selected objects already tagged. Nothing to do.")
    else:
        ids_str = ", ".join(str(i) for i in result["assigned_ids"])
        print("{} object(s) stamped. LUIDs assigned: {}".format(result["stamped_count"], ids_str))


RunCommand()
