#! python3
"""
measure_tank_volume

Modeless dialog for measuring fuel tank capacity. Add closed polysurfaces
representing tank geometry to see their combined volume in US gallons. Enter
a ullage percentage to calculate net usable capacity.

Dialog stays open while navigating the Rhino viewport and does not interfere
with running other Rhino commands. Volume updates live when tracked geometry
is modified. Objects are highlighted in red via a display conduit — no object
properties are changed. Requires Rhino 7+.

Configurable:
    CUBIC_INCHES_PER_GALLON  volume conversion factor (231.0 for US gallons,
                             277.42 for Imperial gallons)
"""
import ctypes
import Rhino
import Rhino.UI
import rhinoscriptsyntax as rs
import scriptcontext as sc
import Eto.Forms as forms
import Eto.Drawing as drawing
import System.Drawing


CUBIC_INCHES_PER_GALLON = 231.0  # configurable — use 277.42 for Imperial gallons


def compute_volume_gallons(brep):
    vmp = Rhino.Geometry.VolumeMassProperties.Compute(brep)
    if vmp is None:
        return None
    scale = Rhino.RhinoMath.UnitScale(sc.doc.ModelUnitSystem, Rhino.UnitSystem.Inches)
    return vmp.Volume * (scale ** 3) / CUBIC_INCHES_PER_GALLON


def _hide_close_button():
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.GetActiveWindow.restype = ctypes.c_void_p
    user32.GetSystemMenu.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, "Tank Volume") or user32.GetActiveWindow()
    if hwnd:
        hmenu = user32.GetSystemMenu(hwnd, False)
        if hmenu:
            user32.DeleteMenu(hmenu, 0xF060, 0)
            user32.DrawMenuBar(hwnd)


class TankHighlightConduit(Rhino.Display.DisplayConduit):

    def __init__(self):
        super().__init__()
        self.tracked_guids = set()
        self._mat = Rhino.Display.DisplayMaterial()
        self._mat.Diffuse = System.Drawing.Color.FromArgb(200, 50, 50)
        self._mat.Transparency = 0.5
        self._wire_color = System.Drawing.Color.Red

    def CalculateBoundingBox(self, e):
        for guid in self.tracked_guids:
            obj = sc.doc.Objects.FindId(guid)
            if obj is not None and isinstance(obj.Geometry, Rhino.Geometry.Brep):
                e.IncludeBoundingBox(obj.Geometry.GetBoundingBox(False))

    def PostDrawObjects(self, e):
        for guid in self.tracked_guids:
            obj = sc.doc.Objects.FindId(guid)
            if obj is not None and isinstance(obj.Geometry, Rhino.Geometry.Brep):
                e.Display.DrawBrepShaded(obj.Geometry, self._mat)
                e.Display.DrawBrepWires(obj.Geometry, self._wire_color, -1)


class TankVolumeDialog(forms.Form):

    def __init__(self):
        super().__init__()
        self._objects = []
        self._volumes = {}
        self._allow_close = False

        self.Title = "Tank Volume"
        self.Padding = drawing.Padding(12)
        self.Resizable = False
        self.ClientSize = drawing.Size(240, 290)
        self.Closing += self.on_window_closing
        self.Closed += self.on_window_closed

        if "tank_volume_conduit" not in sc.sticky:
            sc.sticky["tank_volume_conduit"] = TankHighlightConduit()
        self._conduit = sc.sticky["tank_volume_conduit"]
        self._conduit.tracked_guids = set()
        self._conduit.Enabled = False

        Rhino.RhinoDoc.ReplaceRhinoObject += self._on_replace_object

        val_font = drawing.Font(drawing.SystemFont.Bold, 13)
        hdr_color = drawing.Colors.Gray

        # object count
        self._count_label = forms.Label()
        self._count_label.Text = "No objects added"

        # buttons
        add_btn = forms.Button()
        add_btn.Text = "Add Objects"
        add_btn.Click += self.on_add_clicked

        clear_btn = forms.Button()
        clear_btn.Text = "Clear All"
        clear_btn.Click += self.on_clear_clicked

        btn_row = forms.StackLayout()
        btn_row.Orientation = forms.Orientation.Horizontal
        btn_row.Spacing = 6
        btn_row.Items.Add(forms.StackLayoutItem(add_btn, False))
        btn_row.Items.Add(forms.StackLayoutItem(clear_btn, False))

        # total volume (stacked: header above large value)
        total_hdr = forms.Label()
        total_hdr.Text = "Total Volume"
        total_hdr.TextColor = hdr_color
        self._total_label = forms.Label()
        self._total_label.Text = "0.000 gal"
        self._total_label.Font = val_font

        # ullage (all on one line: label + stepper + % + spacer + result)
        ullage_lbl = forms.Label()
        ullage_lbl.Text = "Ullage"
        pct_lbl = forms.Label()
        pct_lbl.Text = "%"
        self._ullage_field = forms.NumericStepper()
        self._ullage_field.MinValue = 0
        self._ullage_field.MaxValue = 100
        self._ullage_field.DecimalPlaces = 1
        self._ullage_field.Value = 5
        self._ullage_field.Width = 58
        self._ullage_field.ValueChanged += lambda s, e: self._refresh_ullage()
        self._ullage_gal_label = forms.Label()
        self._ullage_gal_label.Text = "0.000 gal"
        self._ullage_gal_label.TextColor = hdr_color

        ullage_row = forms.StackLayout()
        ullage_row.Orientation = forms.Orientation.Horizontal
        ullage_row.Spacing = 5
        ullage_row.VerticalContentAlignment = forms.VerticalAlignment.Center
        ullage_row.Items.Add(forms.StackLayoutItem(ullage_lbl, False))
        ullage_row.Items.Add(forms.StackLayoutItem(self._ullage_field, False))
        ullage_row.Items.Add(forms.StackLayoutItem(pct_lbl, False))
        ullage_row.Items.Add(forms.StackLayoutItem(None, True))
        ullage_row.Items.Add(forms.StackLayoutItem(self._ullage_gal_label, False))

        # net volume (stacked: header above large value)
        net_hdr = forms.Label()
        net_hdr.Text = "Net Volume"
        net_hdr.TextColor = hdr_color
        self._net_label = forms.Label()
        self._net_label.Text = "0.000 gal"
        self._net_label.Font = val_font

        # close button
        close_btn = forms.Button()
        close_btn.Text = "Close"
        close_btn.Click += self.on_close_clicked

        close_row = forms.StackLayout()
        close_row.Orientation = forms.Orientation.Horizontal
        close_row.Items.Add(forms.StackLayoutItem(None, True))
        close_row.Items.Add(forms.StackLayoutItem(close_btn, False))

        layout = forms.DynamicLayout()
        layout.DefaultSpacing = drawing.Size(6, 6)
        layout.AddRow(self._count_label)
        layout.AddRow(btn_row)
        layout.AddRow(None)
        layout.AddRow(total_hdr)
        layout.AddRow(self._total_label)
        layout.AddRow(None)
        layout.AddRow(ullage_row)
        layout.AddRow(None)
        layout.AddRow(net_hdr)
        layout.AddRow(self._net_label)
        layout.AddRow(None)
        layout.AddRow(close_row)
        self.Content = layout

        preselected = rs.SelectedObjects() or []
        if preselected:
            self._add_guids(preselected)
            self.update_display()

    def _add_guids(self, guids):
        invalid = 0
        for guid in guids:
            if guid in self._volumes:
                continue
            brep = rs.coercebrep(guid)
            if brep is None or not brep.IsSolid:
                invalid += 1
                continue
            vol = compute_volume_gallons(brep)
            if vol is not None:
                self._objects.append(guid)
                self._volumes[guid] = vol
        self._conduit.tracked_guids = set(self._objects)
        self._conduit.Enabled = bool(self._objects)
        return invalid

    def _on_replace_object(self, sender, e):
        guid = e.ObjectId
        if guid not in self._volumes:
            return
        new_obj = e.NewRhinoObject
        if new_obj is None:
            return
        brep = new_obj.Geometry
        if isinstance(brep, Rhino.Geometry.Brep) and brep.IsSolid:
            vol = compute_volume_gallons(brep)
            if vol is not None:
                self._volumes[guid] = vol
                self.update_display()

    def on_add_clicked(self, sender, e):
        self.Visible = False

        go = Rhino.Input.Custom.GetObject()
        go.SetCommandPrompt("Select closed polysurfaces (Enter when done)")
        go.GeometryFilter = Rhino.DocObjects.ObjectType.Brep
        go.EnablePreSelect(False, True)
        go.SubObjectSelect = False
        res = go.GetMultiple(1, 0)

        invalid = 0
        if res == Rhino.Input.GetResult.Object:
            guids = [go.Object(i).ObjectId for i in range(go.ObjectCount)]
            invalid = self._add_guids(guids)

        self.Visible = True
        self.BringToFront()

        if invalid:
            rs.MessageBox(
                "{} object(s) skipped — only closed polysurfaces are supported.".format(invalid),
                0,
                "Tank Volume"
            )
        self.update_display()

    def on_window_closing(self, sender, e):
        if not self._allow_close:
            e.Cancel = True

    def on_window_closed(self, sender, e):
        Rhino.RhinoDoc.ReplaceRhinoObject -= self._on_replace_object
        self._conduit.tracked_guids.clear()
        self._conduit.Enabled = False
        sc.doc.Views.Redraw()
        if "tank_volume_dialog" in sc.sticky:
            del sc.sticky["tank_volume_dialog"]

    def on_clear_clicked(self, sender, e):
        self._objects = []
        self._volumes = {}
        self._conduit.tracked_guids.clear()
        self._conduit.Enabled = False
        self.update_display()

    def on_close_clicked(self, sender, e):
        self._allow_close = True
        self.Close()

    def update_display(self):
        n = len(self._objects)
        if n == 0:
            self._count_label.Text = "No objects added"
        elif n == 1:
            self._count_label.Text = "1 polysurface added"
        else:
            self._count_label.Text = "{} polysurfaces added".format(n)
        self._total_label.Text = "{:.3f} gal".format(sum(self._volumes.values()))
        self._refresh_ullage()
        sc.doc.Views.Redraw()

    def _refresh_ullage(self):
        total = sum(self._volumes.values())
        pct = max(0.0, min(100.0, float(self._ullage_field.Value)))
        ullage_gal = total * (pct / 100.0)
        self._ullage_gal_label.Text = "{:.3f} gal".format(ullage_gal)
        self._net_label.Text = "{:.3f} gal".format(total - ullage_gal)


def main():
    if "tank_volume_dialog" in sc.sticky:
        dlg = sc.sticky["tank_volume_dialog"]
        if not dlg.IsDisposed:
            dlg.BringToFront()
            return
        del sc.sticky["tank_volume_dialog"]

    go = Rhino.Input.Custom.GetObject()
    go.SetCommandPrompt("Select closed polysurfaces for tank volume (Enter to open empty)")
    go.GeometryFilter = Rhino.DocObjects.ObjectType.Brep
    go.EnablePreSelect(True, True)
    go.SubObjectSelect = False
    go.GetMultiple(0, 0)

    dlg = TankVolumeDialog()
    dlg.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    dlg.Show()
    sc.sticky["tank_volume_dialog"] = dlg
    _hide_close_button()


if __name__ == "__main__":
    main()
