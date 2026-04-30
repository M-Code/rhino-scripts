#! python3
"""
measure_tank_volume

Semi-modal dialog for measuring fuel tank capacity. Add closed polysurfaces
representing tank geometry to see their combined volume in US gallons. Enter
a ullage percentage to calculate net usable capacity.

Dialog stays open while navigating the Rhino viewport. Requires Rhino 7+.

Configurable:
    CUBIC_INCHES_PER_GALLON  volume conversion factor (231.0 for US gallons,
                             277.42 for Imperial gallons)
"""
import Rhino
import Rhino.UI
import rhinoscriptsyntax as rs
import scriptcontext as sc
import Eto.Forms as forms
import Eto.Drawing as drawing


CUBIC_INCHES_PER_GALLON = 231.0  # configurable — use 277.42 for Imperial gallons


def compute_volume_gallons(brep):
    vmp = Rhino.Geometry.VolumeMassProperties.Compute(brep)
    if vmp is None:
        return None
    scale = Rhino.RhinoMath.UnitScale(sc.doc.ModelUnitSystem, Rhino.UnitSystem.Inches)
    return vmp.Volume * (scale ** 3) / CUBIC_INCHES_PER_GALLON


class TankVolumeDialog(forms.Dialog[bool]):

    def __init__(self):
        super().__init__()
        self._objects = []
        self._volumes = {}
        self._orig_colors = {}  # GUID -> (color, color_source) for restore on close/clear
        self._allow_close = False

        self.Title = "Tank Volume"
        self.Padding = drawing.Padding(12)
        self.Resizable = False
        self.ClientSize = drawing.Size(290, 250)
        self.Closing += self.on_window_closing

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

        # volume readouts
        total_lbl = forms.Label()
        total_lbl.Text = "Total Volume:"
        self._total_label = forms.Label()
        self._total_label.Text = "0.000 gal"

        ullage_lbl = forms.Label()
        ullage_lbl.Text = "Ullage (%):"
        self._ullage_field = forms.NumericStepper()
        self._ullage_field.MinValue = 0
        self._ullage_field.MaxValue = 100
        self._ullage_field.DecimalPlaces = 1
        self._ullage_field.Value = 5
        self._ullage_field.Width = 70
        self._ullage_field.ValueChanged += self.on_ullage_changed

        self._ullage_gal_label = forms.Label()
        self._ullage_gal_label.Text = "= 0.000 gal"

        net_lbl = forms.Label()
        net_lbl.Text = "Net Volume:"
        self._net_label = forms.Label()
        self._net_label.Text = "0.000 gal"

        # close button
        close_btn = forms.Button()
        close_btn.Text = "Close"
        close_btn.Click += self.on_close_clicked
        self.AbortButton = close_btn

        close_row = forms.StackLayout()
        close_row.Orientation = forms.Orientation.Horizontal
        close_row.Items.Add(forms.StackLayoutItem(None, True))
        close_row.Items.Add(forms.StackLayoutItem(close_btn, False))

        layout = forms.DynamicLayout()
        layout.DefaultSpacing = drawing.Size(8, 6)
        layout.AddRow(self._count_label)
        layout.AddRow(btn_row)
        layout.AddRow(None)
        layout.AddRow(total_lbl, self._total_label)
        layout.AddRow(ullage_lbl, self._ullage_field)
        layout.AddRow(None, self._ullage_gal_label)
        layout.AddRow(net_lbl, self._net_label)
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
                self._orig_colors[guid] = (rs.ObjectColor(guid), rs.ObjectColorSource(guid))
                rs.ObjectColorSource(guid, 1)
                rs.ObjectColor(guid, (255, 0, 0))
        return invalid

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

    def on_clear_clicked(self, sender, e):
        self._restore_colors()
        self._objects = []
        self._volumes = {}
        self.update_display()

    def on_ullage_changed(self, sender, e):
        self._refresh_ullage()

    def on_close_clicked(self, sender, e):
        self._restore_colors()
        self._allow_close = True
        self.Close(True)

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

    def _restore_colors(self):
        for guid, (col, src) in self._orig_colors.items():
            if rs.IsObject(guid):
                rs.ObjectColor(guid, col)
                rs.ObjectColorSource(guid, src)
        self._orig_colors = {}
        sc.doc.Views.Redraw()

    def _refresh_ullage(self):
        total = sum(self._volumes.values())
        pct = max(0.0, min(100.0, float(self._ullage_field.Value)))
        ullage_gal = total * (pct / 100.0)
        self._ullage_gal_label.Text = "= {:.3f} gal".format(ullage_gal)
        self._net_label.Text = "{:.3f} gal".format(total - ullage_gal)


def main():
    dialog = TankVolumeDialog()
    Rhino.UI.EtoExtensions.ShowSemiModal(dialog, sc.doc, Rhino.UI.RhinoEtoApp.MainWindow)


if __name__ == "__main__":
    main()
