#! python 3
"""
hatch_sim

HatchSim: hatch/door linkage previewer. Rhino 8, Python 3 only.

A door hangs on an arm. The arm pivots about a FIXED axis line. The door is
attached to the arm at a DOOR axis line, parallel to the fixed axis. A slider
swings the arm; the door rides on the end of it.

Door angle: the door also turns about the door axis, measured from how it was
modeled (0 = stays level). "Starts at" delays the turn: the door stays level
until the arm reaches that percentage of Max, then ramps evenly:
    start     = Max * starts_at% / 100
    door turn = Door angle * (arm - start) / (Max - start),  0 before start
so the door reaches the full Door angle exactly at arm Max.

HatchSim never changes colors: Rhino draws each moved object in the preview
exactly as it would draw the real one (layer/sublayer color, material, display
mode), baked copies keep the original's attributes, and new layers get Rhino's
default color.

Geometry is assigned by layer (no picking):
    HatchSim::Door        door geometry (sublayers count too)
    HatchSim::Arm         arm geometry (sublayers count too)
    HatchSim::Fixed Axis  exactly ONE straight line (the pivot)
    HatchSim::Door Axis   exactly ONE straight line (where the door hangs)
    HatchSim::Baked       Bake output goes here

The preview is drawn by a display conduit. Real objects never move. While the
window is open, the Door, Arm and Door Axis layers are turned off so only the
moving preview shows. Closing the window (any way) turns them back on.

Settings (min, max, flip, door angle, starts at %, last angle) are saved in the
document's user strings, section "HatchSim".

Configurable (top of file):
    ROOT_LAYER        parent layer name (may be nested inside other layers)
    PARALLEL_TOL_DEG  how far from parallel the two axes may be
    DEFAULT_MIN/MAX   starting angle limits for a new file
    LIMIT_RANGE       min/max fields are clamped to +/- this many degrees
    AXIS_THICKNESS    preview line thickness for the door axis
    WINDOW_W/H        window size (raise WINDOW_H if anything is cut off)
    RHINO_DRAWS_PREVIEW  True = preview drawn by Rhino itself (exact look);
                         False = HatchSim's own mesh/edge preview

No plugins required.
"""
import math
import traceback

import System
import Rhino
import Rhino.UI
import scriptcontext as sc
import Eto.Forms as forms
import Eto.Drawing as drawing
from Rhino.Geometry import (Brep, Extrusion, Mesh, SubD, Curve, LineCurve,
                            Line, Point3d, Vector3d, Transform, BoundingBox,
                            MeshingParameters, MeshType)
from Rhino.DocObjects import Layer, ObjectEnumeratorSettings, InstanceObject


ROOT_LAYER = "HatchSim"   # configurable: name of the parent layer. It can sit
                          # at the top level or nested inside other layers.

# Sublayers under ROOT_LAYER (created with Rhino's default layer color)
SUBLAYERS = ["Door", "Arm", "Fixed Axis", "Door Axis", "Baked"]

PARALLEL_TOL_DEG = 0.5     # configurable: max angle between the two axes
DEFAULT_MIN      = 0       # configurable: degrees
DEFAULT_MAX      = 90      # configurable: degrees
LIMIT_RANGE      = 360     # configurable: min/max fields clamp to +/- this
AXIS_THICKNESS   = 3       # configurable: px, door axis preview line
WIRE_THICKNESS   = 1       # configurable: px, edge/curve preview lines
WINDOW_W         = 470     # configurable: window inner width
WINDOW_H         = 336     # configurable: window inner height
STATUS_H         = 54      # configurable: status text height (about 3 lines)
RHINO_DRAWS_PREVIEW = True # configurable: True = Rhino draws each moved object
                           # exactly as it looks in the current display mode.
                           # False = HatchSim draws its own mesh + edge copies
                           # (use this if the preview ever shows up empty).
MAX_START_PCT    = 99      # configurable: highest allowed "starts at" percentage

SETTINGS_SECTION = "HatchSim"
STICKY_KEY       = "hatch_sim_form"

SETUP_HELP = (
    "HatchSim setup. Put your geometry on these layers, then run HatchSim again:\n"
    "  HatchSim::Door        the door (any number of objects)\n"
    "  HatchSim::Arm         the arm (any number of objects)\n"
    "  HatchSim::Fixed Axis  ONE straight line: the pivot on the frame\n"
    "  HatchSim::Door Axis   ONE straight line: where the door hangs on the arm,\n"
    "                        parallel to the fixed axis\n"
    "Model everything in the CLOSED position (that is 0 degrees)."
)


# ---------------------------------------------------------------- messages

def log(msg):
    Rhino.RhinoApp.WriteLine("HatchSim: " + msg)


def tell(msg, title="HatchSim"):
    """Print to the command line and show a message box."""
    for line in msg.splitlines():
        Rhino.RhinoApp.WriteLine(line)
    try:
        Rhino.UI.Dialogs.ShowMessage(msg, title)
    except Exception:
        pass


# ---------------------------------------------------------------- small math
# Done with plain floats so nothing depends on mutating RhinoCommon structs.

def unit_dir(line):
    dx, dy, dz = line.To.X - line.From.X, line.To.Y - line.From.Y, line.To.Z - line.From.Z
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    return Vector3d(dx / L, dy / L, dz / L)


def apply_xform(xf, p):
    """Return a new Point3d = xf applied to p."""
    x = xf.M00 * p.X + xf.M01 * p.Y + xf.M02 * p.Z + xf.M03
    y = xf.M10 * p.X + xf.M11 * p.Y + xf.M12 * p.Z + xf.M13
    z = xf.M20 * p.X + xf.M21 * p.Y + xf.M22 * p.Z + xf.M23
    w = xf.M30 * p.X + xf.M31 * p.Y + xf.M32 * p.Z + xf.M33
    if abs(w) < 1e-12:
        w = 1.0
    return Point3d(x / w, y / w, z / w)


def distance_to_infinite_line(p, line):
    d = unit_dir(line)
    vx, vy, vz = p.X - line.From.X, p.Y - line.From.Y, p.Z - line.From.Z
    cx = vy * d.Z - vz * d.Y
    cy = vz * d.X - vx * d.Z
    cz = vx * d.Y - vy * d.X
    return math.sqrt(cx * cx + cy * cy + cz * cz)


def union_box(a, b):
    if not b.IsValid:
        return a
    if not a.IsValid:
        return b
    return BoundingBox.Union(a, b)


def door_turn(arm_deg, door_deg, max_deg, start_pct=0.0):
    """How far the door has turned at this arm angle.
    0 until the arm reaches start_pct % of Max, then scales evenly up to the
    full door angle at arm Max."""
    if abs(max_deg) < 1e-9:
        return 0.0
    start = max_deg * start_pct / 100.0
    if start_pct <= 0.0:
        frac = arm_deg / max_deg      # no delay: ramps from arm 0 (reverses below 0)
    else:
        frac = max(0.0, (arm_deg - start) / (max_deg - start))
    return door_deg * frac


def compute_transforms(rig, arm_deg, turn_deg):
    """Arm rotates arm_deg about the fixed axis.
    Door first turns turn_deg about its own axis (as modeled), then moves by
    however far the door axis point travelled with the arm.
    Both angles are already signed (Flip applied)."""
    axis_pt = rig.fixed_line.From
    axis_dir = unit_dir(rig.fixed_line)
    arm_xf = Transform.Rotation(math.radians(arm_deg), axis_dir, axis_pt)
    p = rig.door_line.From
    q = apply_xform(arm_xf, p)
    # Turn uses the fixed axis direction so a door axis drawn the "other way"
    # still turns the same way as the arm for a positive angle.
    turn_xf = Transform.Rotation(math.radians(turn_deg), axis_dir, p)
    move_xf = Transform.Translation(q.X - p.X, q.Y - p.Y, q.Z - p.Z)
    door_xf = Transform.Multiply(move_xf, turn_xf)   # turn first, then move
    return arm_xf, door_xf


# ---------------------------------------------------------------- layers

def find_layer(doc, path):
    idx = doc.Layers.FindByFullPath(path, -1)
    if idx < 0:
        return None
    lyr = doc.Layers[idx]
    if lyr is None or lyr.IsDeleted:
        return None
    return lyr


class Paths(object):
    """Full layer paths, worked out from wherever the HatchSim layer lives
    (e.g. "Project::Hatch::HatchSim::Door")."""

    def __init__(self, root_path):
        self.root = root_path
        self.door = root_path + "::Door"
        self.arm = root_path + "::Arm"
        self.fixed_axis = root_path + "::Fixed Axis"
        self.door_axis = root_path + "::Door Axis"
        self.baked = root_path + "::Baked"


def find_roots(doc):
    """Every layer named ROOT_LAYER, at any depth. A HatchSim layer sitting
    inside another HatchSim layer doesn't count as a second one."""
    roots = []
    for lyr in doc.Layers:
        if lyr is None or lyr.IsDeleted or lyr.Name != ROOT_LAYER:
            continue
        ancestors = lyr.FullPath.split("::")[:-1]
        if ROOT_LAYER not in ancestors:
            roots.append(lyr)
    return roots


def ensure_layers(doc):
    """Find the HatchSim layer (top level or nested) and create any missing
    layers. Returns (Paths or None, created paths, error or None)."""
    created = []
    roots = find_roots(doc)
    if len(roots) > 1:
        names = "\n".join("  " + r.FullPath for r in roots)
        return None, created, ("Found {} layers named '{}':\n{}\n"
                               "HatchSim handles one hatch per file. Rename or delete "
                               "the extras.".format(len(roots), ROOT_LAYER, names))
    if roots:
        root = roots[0]
    else:
        new = Layer()
        new.Name = ROOT_LAYER
        doc.Layers.Add(new)
        created.append(ROOT_LAYER)
        root = find_layer(doc, ROOT_LAYER)
    paths = Paths(root.FullPath)
    for name in SUBLAYERS:
        path = paths.root + "::" + name
        if find_layer(doc, path) is not None:
            continue
        new = Layer()
        new.Name = name
        new.ParentLayerId = root.Id
        doc.Layers.Add(new)
        created.append(path)
    return paths, created, None


def layers_under(doc, path, include_sublayers):
    """Layer objects at `path` (and below it, if include_sublayers)."""
    out = []
    for lyr in doc.Layers:
        if lyr is None or lyr.IsDeleted:
            continue
        fp = lyr.FullPath
        if fp == path or (include_sublayers and fp.startswith(path + "::")):
            out.append(lyr)
    return out


def objects_on(doc, path, include_sublayers):
    """Normal + locked objects on the layer (hidden objects are ignored).
    Objects on layers that are turned off ARE included."""
    indices = set(l.Index for l in layers_under(doc, path, include_sublayers))
    if not indices:
        return []
    settings = ObjectEnumeratorSettings()
    settings.NormalObjects = True
    settings.LockedObjects = True
    settings.HiddenObjects = False
    settings.DeletedObjects = False
    settings.IncludeLights = False
    settings.IncludeGrips = False
    out = []
    for obj in doc.Objects.GetObjectList(settings):
        if obj.IsInstanceDefinitionGeometry:
            continue
        if obj.Attributes.LayerIndex in indices:
            out.append(obj)
    return out


# ---------------------------------------------------------------- geometry

def describe(obj):
    if isinstance(obj, InstanceObject):
        try:
            what = "block instance '{}'".format(obj.InstanceDefinition.Name)
        except Exception:
            what = "block instance"
    else:
        what = str(obj.ObjectType)
    if obj.Attributes.Name:
        what += " named '{}'".format(obj.Attributes.Name)
    return what


def join_meshes(meshes):
    if not meshes:
        return None
    out = Mesh()
    for m in meshes:
        if m is not None:
            out.Append(m)
    if out.Vertices.Count == 0:
        return None
    if out.Normals.Count == 0:
        out.Normals.ComputeNormals()
    return out


def shading_material(rh_obj):
    """Shade the preview with the object's own render material (what Rhino
    itself uses for shaded faces). The display color is only for wires."""
    try:
        mat = rh_obj.GetMaterial(True)
        if mat is not None:
            return Rhino.Display.DisplayMaterial(mat)
    except Exception:
        pass
    return Rhino.Display.DisplayMaterial()   # Rhino's default (light gray)


class Item(object):
    """One door/arm object: an untouched copy for Bake, plus a display mesh
    and wire curves for the preview, plus their transformed (cached) copies."""

    def __init__(self, rh_obj, doc, source, mesh, wires):
        self.rh_obj = rh_obj      # the real object (Rhino draws it moved by xf)
        self.xf = Transform.Identity
        self.attrs = rh_obj.Attributes.Duplicate()
        self.color = rh_obj.Attributes.DrawColor(doc)
        self.material = shading_material(rh_obj)
        self.source = source      # geometry for Bake (never drawn, never moved)
        self.mesh = mesh          # None for curves
        self.wires = wires        # list of Curve
        self.t_mesh = None
        self.t_wires = []

    def update(self, xf):
        """Rebuild the transformed copies. Returns their bounding box."""
        self.xf = xf
        if RHINO_DRAWS_PREVIEW:
            return self.source.GetBoundingBox(xf)   # no copies needed
        box = BoundingBox.Empty
        if self.mesh is not None:
            m = self.mesh.DuplicateMesh()
            m.Transform(xf)
            self.t_mesh = m
            box = union_box(box, m.GetBoundingBox(False))
        wires = []
        for c in self.wires:
            d = c.DuplicateCurve()
            d.Transform(xf)
            wires.append(d)
            box = union_box(box, d.GetBoundingBox(False))
        self.t_wires = wires
        return box


def make_item(rh_obj, doc):
    """Build an Item, or return None if the geometry type isn't supported."""
    g = rh_obj.Geometry
    if isinstance(g, Curve):
        return Item(rh_obj, doc, g.DuplicateCurve(), None, [g.DuplicateCurve()])

    if isinstance(g, (Brep, Extrusion, SubD, Mesh)):
        # Prefer the render mesh Rhino already made (matches what you see).
        mesh = None
        try:
            mesh = join_meshes(list(rh_obj.GetMeshes(MeshType.Render)))
        except Exception:
            mesh = None

        wires = []
        if isinstance(g, (Brep, Extrusion)):
            brep = g if isinstance(g, Brep) else g.ToBrep()
            if mesh is None and brep is not None:
                mesh = join_meshes(list(Mesh.CreateFromBrep(brep, MeshingParameters.Default) or []))
            if brep is not None:
                wires = list(brep.DuplicateEdgeCurves(False) or [])
        elif isinstance(g, SubD):
            if mesh is None:
                try:
                    mesh = Mesh.CreateFromSubD(g, 3)
                except Exception:
                    mesh = None
            try:
                wires = list(g.DuplicateEdgeCurves() or [])
            except Exception:
                wires = []   # falls back to mesh wires when drawing
        else:  # Mesh
            mesh = join_meshes([g.DuplicateMesh()])

        if mesh is None and not wires:
            return None
        return Item(rh_obj, doc, g.Duplicate(), mesh, wires)

    return None


class Rig(object):
    """Everything HatchSim read from the document."""

    def __init__(self):
        self.fixed_line = None
        self.door_line = None
        self.door_axis_curve = None
        self.door_axis_attrs = None
        self.door_axis_color = None
        self.door_items = []
        self.arm_items = []
        self.arm_length = 0.0


def read_axis(doc, path, tol):
    """Returns (Line, RhinoObject, error_or_None). Empty layer -> (None, None, None)."""
    objs = objects_on(doc, path, False)
    if not objs:
        return None, None, None
    if len(objs) > 1:
        return None, None, "{} has {} objects. It must hold exactly ONE straight line.".format(path, len(objs))
    obj = objs[0]
    crv = obj.Geometry
    if not isinstance(crv, Curve):
        return None, None, "{} holds a {}, not a line.".format(path, describe(obj))
    if not (isinstance(crv, LineCurve) or crv.IsLinear(tol)):
        return None, None, "{}: the curve is not straight. Use a Line.".format(path)
    line = Line(crv.PointAtStart, crv.PointAtEnd)
    if line.Length <= tol:
        return None, None, "{}: the line has zero length.".format(path)
    return line, obj, None


def read_setup(doc, paths):
    """Read and validate everything.
    Returns (rig, empty_layers, errors, warnings). rig is None if anything failed."""
    tol = doc.ModelAbsoluteTolerance
    rig = Rig()
    empty, errors, warnings = [], [], []

    for path, target in ((paths.door, rig.door_items), (paths.arm, rig.arm_items)):
        objs = objects_on(doc, path, True)
        skipped = []
        for obj in objs:
            item = make_item(obj, doc)
            if item is None:
                skipped.append(describe(obj))
            else:
                target.append(item)
        if skipped:
            warnings.append("Skipped {} unsupported object(s) on {}:".format(len(skipped), path))
            for s in skipped[:10]:
                warnings.append("    " + s)
            if len(skipped) > 10:
                warnings.append("    ... and {} more".format(len(skipped) - 10))
        if not target:
            empty.append(path)

    rig.fixed_line, _, err = read_axis(doc, paths.fixed_axis, tol)
    if err:
        errors.append(err)
    elif rig.fixed_line is None:
        empty.append(paths.fixed_axis)

    rig.door_line, door_axis_obj, err = read_axis(doc, paths.door_axis, tol)
    if err:
        errors.append(err)
    elif rig.door_line is None:
        empty.append(paths.door_axis)

    if rig.fixed_line is not None and rig.door_line is not None:
        d1, d2 = unit_dir(rig.fixed_line), unit_dir(rig.door_line)
        c = min(1.0, abs(d1.X * d2.X + d1.Y * d2.Y + d1.Z * d2.Z))
        off = math.degrees(math.acos(c))
        if off > PARALLEL_TOL_DEG:
            errors.append("The two axes are not parallel: {:.2f} degrees apart "
                          "(limit {} degrees).".format(off, PARALLEL_TOL_DEG))
        rig.arm_length = distance_to_infinite_line(rig.door_line.From, rig.fixed_line)
        if rig.arm_length <= tol:
            errors.append("The door axis lies on the fixed axis (arm length is zero). "
                          "Move it to where the door hangs on the arm.")
        rig.door_axis_curve = LineCurve(rig.door_line)
        rig.door_axis_attrs = door_axis_obj.Attributes.Duplicate()
        rig.door_axis_color = door_axis_obj.Attributes.DrawColor(doc)

    if empty or errors:
        return None, empty, errors, warnings
    return rig, empty, errors, warnings


# ---------------------------------------------------------------- settings

def load_settings(doc):
    def get(key, default, conv):
        try:
            v = doc.Strings.GetValue(SETTINGS_SECTION, key)
            return conv(v) if v else default
        except Exception:
            return default
    s = {
        "min": get("min", DEFAULT_MIN, lambda v: int(round(float(v)))),
        "max": get("max", DEFAULT_MAX, lambda v: int(round(float(v)))),
        "flip": get("flip", False, lambda v: v == "1"),
        "angle": get("angle", 0.0, float),
        "door": get("door", 0.0, float),
        "start": get("start", 0.0, float),
    }
    s["start"] = max(0.0, min(MAX_START_PCT, s["start"]))
    if s["min"] >= s["max"]:
        s["min"], s["max"] = DEFAULT_MIN, DEFAULT_MAX
    s["angle"] = max(s["min"], min(s["max"], s["angle"]))
    return s


def save_settings(doc, lo, hi, flip, angle, door, start):
    doc.Strings.SetString(SETTINGS_SECTION, "min", str(int(lo)))
    doc.Strings.SetString(SETTINGS_SECTION, "max", str(int(hi)))
    doc.Strings.SetString(SETTINGS_SECTION, "flip", "1" if flip else "0")
    doc.Strings.SetString(SETTINGS_SECTION, "angle", "{:.4f}".format(angle))
    doc.Strings.SetString(SETTINGS_SECTION, "door", "{:.4f}".format(door))
    doc.Strings.SetString(SETTINGS_SECTION, "start", "{:.4f}".format(start))


# ---------------------------------------------------------------- preview

class HatchConduit(Rhino.Display.DisplayConduit):

    def __init__(self):
        super().__init__()
        self.items = []
        self.door_axis = None
        self.door_axis_color = System.Drawing.Color.Black
        self.bbox = BoundingBox.Empty
        self.on_error = None      # set by the form: called once if drawing fails
        self._failed = False

    def _draw_axis(self, d):
        if self.door_axis is not None:
            d.DrawCurve(self.door_axis, self.door_axis_color, AXIS_THICKNESS)

    def CalculateBoundingBox(self, e):
        if self.bbox.IsValid:
            e.IncludeBoundingBox(self.bbox)

    def PostDrawObjects(self, e):
        if self._failed:
            return
        try:
            d = e.Display
            if RHINO_DRAWS_PREVIEW:
                for it in self.items:
                    d.DrawObject(it.rh_obj, it.xf)
                self._draw_axis(d)
                return
            shaded = d.DisplayPipelineAttributes.ShadingEnabled
            for it in self.items:
                if it.t_mesh is not None and shaded:
                    d.DrawMeshShaded(it.t_mesh, it.material)
                if it.t_wires:
                    for c in it.t_wires:
                        d.DrawCurve(c, it.color, WIRE_THICKNESS)
                elif it.t_mesh is not None:
                    d.DrawMeshWires(it.t_mesh, it.color)
            self._draw_axis(d)
        except Exception:
            self._failed = True
            log("Preview drawing failed:\n" + traceback.format_exc())
            if self.on_error:
                self.on_error()


# ---------------------------------------------------------------- UI helpers

def label(text):
    l = forms.Label()
    l.Text = text
    l.VerticalAlignment = forms.VerticalAlignment.Center
    return l


def button(text, handler):
    b = forms.Button()
    b.Text = text
    b.Click += handler
    return b


def stepper(lo, hi, decimals, value):
    s = forms.NumericStepper()
    s.MinValue = lo
    s.MaxValue = hi
    s.DecimalPlaces = decimals
    s.Increment = 1
    s.Value = value
    s.Width = 70
    return s


def set_range(ctrl, lo, hi):
    """Set MinValue/MaxValue in an order that never makes min > max."""
    if lo > ctrl.MaxValue:
        ctrl.MaxValue = hi
        ctrl.MinValue = lo
    else:
        ctrl.MinValue = lo
        ctrl.MaxValue = hi


def hrow(*controls):
    """Horizontal row. None = stretchy spacer."""
    row = forms.StackLayout()
    row.Orientation = forms.Orientation.Horizontal
    row.Spacing = 6
    row.VerticalContentAlignment = forms.VerticalAlignment.Center
    for c in controls:
        row.Items.Add(forms.StackLayoutItem(c, c is None))
    return row


def guarded(fn):
    """Wrap a UI handler: on any error, report it and close the window
    (closing always restores the layers)."""
    def wrapper(self, *args):
        try:
            fn(self, *args)
        except Exception:
            log("Error:\n" + traceback.format_exc())
            tell("HatchSim hit an error and will close. Details are on the command line.")
            try:
                self.Close()
            except Exception:
                self.cleanup()
    return wrapper


# ---------------------------------------------------------------- the window

class HatchSimForm(forms.Form):

    def __init__(self, doc, paths, rig, settings):
        super().__init__()
        self.doc = doc
        self.paths = paths
        self.rig = rig
        self.lo = settings["min"]
        self.hi = settings["max"]
        self.flip = settings["flip"]
        self.angle = settings["angle"]
        self.door_angle = settings["door"]
        self.start_pct = settings["start"]
        self._syncing = False
        self._cleaned = False
        self._saved_vis = None        # {layer id: was visible} snapshot from open
        self._saved_current = None    # current layer id, if we had to change it

        self.conduit = HatchConduit()
        self.conduit.on_error = self._on_conduit_error

        self.Title = "HatchSim"
        # Fixed size: letting Eto size the window from the wrapping status
        # text cut off the bottom row. Resizable in case your screen scaling
        # needs more room.
        self.ClientSize = drawing.Size(WINDOW_W, WINDOW_H)
        self.MinimumSize = drawing.Size(WINDOW_W, WINDOW_H)
        self.Resizable = True

        # controls
        self.angle_box = stepper(self.lo, self.hi, 2, self.angle)
        self.angle_box.ValueChanged += self.on_angle_box

        self.flip_check = forms.CheckBox()
        self.flip_check.Text = "Flip direction"
        self.flip_check.Checked = self.flip
        self.flip_check.CheckedChanged += self.on_flip

        self.slider = forms.Slider()
        set_range(self.slider, self.lo, self.hi)
        self.slider.Value = int(round(self.angle))
        self.slider.TickFrequency = 10
        self.slider.ValueChanged += self.on_slider

        self.min_box = stepper(-LIMIT_RANGE, LIMIT_RANGE, 0, self.lo)
        self.max_box = stepper(-LIMIT_RANGE, LIMIT_RANGE, 0, self.hi)
        self.min_box.ValueChanged += self.on_limits
        self.max_box.ValueChanged += self.on_limits

        # Door angle: full door turn reached at arm Max (0 = door stays level)
        self.door_box = stepper(-LIMIT_RANGE, LIMIT_RANGE, 2, self.door_angle)
        self.door_box.ValueChanged += self.on_door_angle
        # Door stays level until the arm reaches this % of Max
        self.start_box = stepper(0, MAX_START_PCT, 0, self.start_pct)
        self.start_box.Width = 60
        self.start_box.ValueChanged += self.on_start_pct
        self.turn_label = label("")
        self.turn_label.Width = 300   # fixed so the row doesn't jiggle while scrubbing

        self.status = forms.Label()
        self.status.Wrap = forms.WrapMode.Word
        self.status.Height = STATUS_H   # room for 3 lines, so messages never push the buttons off

        self.bake_btn = button("Bake", self.on_bake)

        col = forms.StackLayout()
        col.Orientation = forms.Orientation.Vertical
        col.Spacing = 8
        col.Padding = drawing.Padding(12)
        col.HorizontalContentAlignment = forms.HorizontalAlignment.Stretch
        for c in (
            hrow(label("Angle"), self.angle_box, label("deg"), None, self.flip_check),
            self.slider,
            hrow(label("Min"), self.min_box, label("Max"), self.max_box, label("deg")),
            hrow(label("Door angle at Max"), self.door_box, label("deg"),
                 label("   starts at"), self.start_box, label("% of Max")),
            hrow(self.turn_label),
            self.status,
            hrow(button("Reload", self.on_reload), self.bake_btn,
                 button("Reset", self.on_reset), None, button("Close", self.on_close_btn)),
        ):
            col.Items.Add(forms.StackLayoutItem(c, False))
        self.Content = col

        self.Closed += self.on_closed
        self._h_close_doc = self.on_doc_closing
        self._h_begin_save = self.on_begin_save
        self._h_end_save = self.on_end_save
        Rhino.RhinoDoc.CloseDocument += self._h_close_doc
        Rhino.RhinoDoc.BeginSaveDocument += self._h_begin_save
        Rhino.RhinoDoc.EndSaveDocument += self._h_end_save

    # ---- lifecycle

    def start(self):
        self.update_status()
        self.update_preview()
        self.conduit.Enabled = True
        self.hide_layers()
        self.doc.Views.Redraw()

    def cleanup(self):
        """Runs once, however the window closes."""
        if self._cleaned:
            return
        self._cleaned = True
        # Each step on its own, so one failure can't skip the rest.
        steps = (
            self._disable_conduit,
            self.restore_layers,
            self.save,
            self._unhook_events,
        )
        for step in steps:
            try:
                step()
            except Exception:
                log("Cleanup step failed:\n" + traceback.format_exc())
        try:
            self.doc.Views.Redraw()
        except Exception:
            pass
        if sc.sticky.get(STICKY_KEY) is self:
            del sc.sticky[STICKY_KEY]
        log("closed at {:.2f} deg.".format(self.angle))

    def _disable_conduit(self):
        self.conduit.Enabled = False

    def _unhook_events(self):
        Rhino.RhinoDoc.CloseDocument -= self._h_close_doc
        Rhino.RhinoDoc.BeginSaveDocument -= self._h_begin_save
        Rhino.RhinoDoc.EndSaveDocument -= self._h_end_save

    def on_closed(self, sender, e):
        self.cleanup()

    def on_close_btn(self, sender, e):
        self.Close()

    def on_doc_closing(self, sender, e):
        if e.Document.RuntimeSerialNumber == self.doc.RuntimeSerialNumber:
            self.Close()

    def _on_conduit_error(self):
        # Called from inside a redraw: close on the next UI tick, not right now.
        Rhino.RhinoApp.InvokeOnUiThread(System.Action(lambda: self.Close()))

    # ---- saving the file while open: don't save it with the layers turned off

    def on_begin_save(self, sender, e):
        if e.Document.RuntimeSerialNumber != self.doc.RuntimeSerialNumber:
            return
        try:
            self.save()
            self._set_vis_from_snapshot()
        except Exception:
            log("Could not prepare layers for save:\n" + traceback.format_exc())

    def on_end_save(self, sender, e):
        if e.Document.RuntimeSerialNumber != self.doc.RuntimeSerialNumber:
            return
        if self.rig is not None and not self._cleaned:
            self.hide_layers()
            self.doc.Views.Redraw()

    # ---- layer visibility

    def _hidden_layers(self):
        roots = find_roots(self.doc)     # follow the HatchSim layer if it was moved
        if len(roots) == 1:
            self.paths = Paths(roots[0].FullPath)
        return (layers_under(self.doc, self.paths.door, True)
                + layers_under(self.doc, self.paths.arm, True)
                + layers_under(self.doc, self.paths.door_axis, False))

    def hide_layers(self):
        layers = self._hidden_layers()
        if self._saved_vis is None:
            self._saved_vis = dict((l.Id, l.IsVisible) for l in layers)
        # Rhino can't turn off the current layer, so step off it if needed.
        hidden_ids = set(l.Id for l in layers)
        current = self.doc.Layers.CurrentLayer
        if current.Id in hidden_ids:
            if self._saved_current is None:
                self._saved_current = current.Id
            root = find_layer(self.doc, self.paths.root)
            if root is not None:
                self.doc.Layers.SetCurrentLayerIndex(root.Index, True)
        for l in layers:
            if l.IsVisible:
                l.IsVisible = False

    def _set_vis_from_snapshot(self):
        if not self._saved_vis:
            return
        layers = [self.doc.Layers.FindId(i) for i in self._saved_vis]
        layers = [l for l in layers if l is not None and not l.IsDeleted]
        layers.sort(key=lambda l: l.FullPath.count("::"))   # parents first
        for l in layers:
            l.IsVisible = self._saved_vis[l.Id]

    def restore_layers(self):
        self._set_vis_from_snapshot()
        self._saved_vis = None
        if self._saved_current is not None:
            lyr = self.doc.Layers.FindId(self._saved_current)
            if lyr is not None and not lyr.IsDeleted:
                self.doc.Layers.SetCurrentLayerIndex(lyr.Index, True)
            self._saved_current = None

    # ---- preview

    @property
    def sign(self):
        return -1.0 if self.flip else 1.0

    def current_turn(self):
        """Door turn at the current arm angle (before Flip)."""
        return door_turn(self.angle, self.door_angle, self.hi, self.start_pct)

    def transforms(self):
        """(arm_xf, door_xf) at the current settings. Flip reverses both."""
        return compute_transforms(self.rig, self.angle * self.sign,
                                  self.current_turn() * self.sign)

    def save(self):
        save_settings(self.doc, self.lo, self.hi, self.flip, self.angle,
                      self.door_angle, self.start_pct)

    def update_preview(self):
        if self.rig is None:
            self.conduit.items = []
            self.conduit.door_axis = None
            self.conduit.bbox = BoundingBox.Empty
            self.doc.Views.Redraw()
            return
        arm_xf, door_xf = self.transforms()
        if abs(self.hi) < 1e-9:
            self.turn_label.Text = "Max is 0: door can't turn"
        else:
            start = self.hi * self.start_pct / 100.0
            text = "Door turn now {:.2f} deg".format(self.current_turn())
            if self.start_pct > 0:
                text += "   (starts at arm {:.1f} deg)".format(start)
            self.turn_label.Text = text
        box = BoundingBox.Empty
        for it in self.rig.arm_items:
            box = union_box(box, it.update(arm_xf))
        for it in self.rig.door_items:
            box = union_box(box, it.update(door_xf))
        axis = self.rig.door_axis_curve.DuplicateCurve()
        axis.Transform(door_xf)
        box = union_box(box, axis.GetBoundingBox(False))
        self.conduit.items = self.rig.arm_items + self.rig.door_items
        self.conduit.door_axis = axis
        self.conduit.door_axis_color = self.rig.door_axis_color
        self.conduit.bbox = box
        self.doc.Views.Redraw()

    def update_status(self, extra=None):
        if self.rig is None:
            text = "Not loaded. Fix the setup and click Reload."
        else:
            units = "in" if self.doc.ModelUnitSystem == Rhino.UnitSystem.Inches else str(self.doc.ModelUnitSystem)
            text = "Arm length {:.3f} {}   |   Door: {} obj   Arm: {} obj".format(
                self.rig.arm_length, units, len(self.rig.door_items), len(self.rig.arm_items))
        if extra:
            text += "\n" + extra
        self.status.Text = text
        enabled = self.rig is not None
        for c in (self.slider, self.angle_box, self.bake_btn):
            c.Enabled = enabled

    # ---- angle

    def set_angle(self, value, from_box=False):
        value = max(self.lo, min(self.hi, float(value)))
        self.angle = value
        self._syncing = True
        try:
            self.slider.Value = int(round(value))
            if not from_box or abs(self.angle_box.Value - value) > 1e-9:
                self.angle_box.Value = value
        finally:
            self._syncing = False
        self.update_preview()

    @guarded
    def on_slider(self, sender, e):
        if not self._syncing:
            self.set_angle(self.slider.Value)

    @guarded
    def on_angle_box(self, sender, e):
        if not self._syncing:
            self.set_angle(self.angle_box.Value, from_box=True)

    @guarded
    def on_flip(self, sender, e):
        self.flip = bool(self.flip_check.Checked)
        self.save()
        self.update_preview()

    @guarded
    def on_start_pct(self, sender, e):
        self.start_pct = max(0.0, min(MAX_START_PCT, float(self.start_box.Value)))
        self.save()
        self.update_preview()

    @guarded
    def on_door_angle(self, sender, e):
        self.door_angle = float(self.door_box.Value)
        self.save()
        self.update_preview()

    @guarded
    def on_limits(self, sender, e):
        if self._syncing:
            return
        lo, hi = int(round(self.min_box.Value)), int(round(self.max_box.Value))
        if lo >= hi:
            self.update_status("Min must be less than Max.")
            return
        self.lo, self.hi = lo, hi
        self._syncing = True
        try:
            set_range(self.slider, lo, hi)
            set_range(self.angle_box, lo, hi)
        finally:
            self._syncing = False
        self.set_angle(self.angle)
        self.save()
        self.update_status()

    # ---- buttons

    @guarded
    def on_reset(self, sender, e):
        self.set_angle(0.0)
        if self.angle != 0.0:
            log("0 deg is outside Min/Max; reset to {:.2f} deg instead.".format(self.angle))
        self.save()

    @guarded
    def on_reload(self, sender, e):
        paths, _, err = ensure_layers(self.doc)
        if err:
            rig, empty, errors, warnings = None, [], [err], []
        else:
            self.paths = paths     # picks up the layer being moved/re-nested
            rig, empty, errors, warnings = read_setup(self.doc, paths)
        for w in warnings:
            log(w)
        if rig is None:
            self.rig = None
            self.conduit.Enabled = False
            self.update_preview()
            self.restore_layers()       # show the real objects so they can be fixed
            self.doc.Views.Redraw()
            self.update_status()
            tell(problem_text(empty, errors))
            return
        self.rig = rig
        self.update_status("Reloaded." + ("  (Some objects skipped, see command line.)" if warnings else ""))
        self.update_preview()
        self.conduit.Enabled = True
        self.hide_layers()
        self.doc.Views.Redraw()
        log("reloaded.")

    @guarded
    def on_bake(self, sender, e):
        if self.rig is None:
            return
        paths, _, err = ensure_layers(self.doc)
        if err:
            tell(err)
            return
        self.paths = paths
        baked = find_layer(self.doc, paths.baked)
        arm_xf, door_xf = self.transforms()

        def attrs_for(src_attrs):
            # Exact copy of the original's attributes (color settings included).
            # Only the layer changes, and the copy leaves the original's groups.
            a = src_attrs.Duplicate()
            a.LayerIndex = baked.Index
            a.RemoveFromAllGroups()
            return a

        def add(geom, attrs):
            gid = self.doc.Objects.Add(geom, attrs)
            return 0 if gid.Equals(System.Guid.Empty) else 1

        count = 0
        sn = self.doc.BeginUndoRecord("HatchSim Bake")   # one undo for the whole bake
        try:
            for items, xf in ((self.rig.arm_items, arm_xf), (self.rig.door_items, door_xf)):
                for it in items:
                    g = it.source.Duplicate()
                    g.Transform(xf)
                    count += add(g, attrs_for(it.attrs))
            axis = self.rig.door_axis_curve.DuplicateCurve()
            axis.Transform(door_xf)
            count += add(axis, attrs_for(self.rig.door_axis_attrs))
        finally:
            if sn:
                self.doc.EndUndoRecord(sn)
        self.save()
        self.doc.Views.Redraw()
        msg = "Baked {} object(s) at arm {:.2f} deg, door turn {:.2f} deg, to {}.".format(
            count, self.angle, self.current_turn(), self.paths.baked)
        if not baked.IsVisible:
            msg += " (That layer is turned off.)"
        log(msg)
        self.update_status(msg)


# ---------------------------------------------------------------- run

def problem_text(empty, errors):
    lines = []
    if errors:
        lines.append("HatchSim can't run. Fix these:")
        lines += ["  - " + e for e in errors]
    if empty:
        if lines:
            lines.append("")
        lines.append("These layers are empty (or have nothing supported on them):")
        lines += ["  - " + p for p in empty]
        lines.append("")
        lines.append(SETUP_HELP)
    return "\n".join(lines)


def main():
    old = sc.sticky.get(STICKY_KEY)
    if old is not None:
        try:
            if not old.IsDisposed and old.Visible:
                old.BringToFront()
                log("already open.")
                return
        except Exception:
            pass
        sc.sticky.pop(STICKY_KEY, None)

    doc = sc.doc
    paths, created, err = ensure_layers(doc)
    if err:
        tell(err)
        return
    if created:
        log("created layers: " + ", ".join(created))

    rig, empty, errors, warnings = read_setup(doc, paths)
    for w in warnings:
        log(w)
    if rig is None:
        msg = problem_text(empty, errors)
        if created:
            msg = "Created layers:\n" + "\n".join("  " + p for p in created) + "\n\n" + msg
        tell(msg)
        return

    form = HatchSimForm(doc, paths, rig, load_settings(doc))
    try:
        form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
        form.Show()
        sc.sticky[STICKY_KEY] = form   # keeps the window alive after the script returns
        form.start()
        if warnings:
            form.update_status("Some objects were skipped, see command line.")
        log("open. Arm length {:.3f}.".format(rig.arm_length))
    except Exception:
        log("Failed to open:\n" + traceback.format_exc())
        form.cleanup()
        try:
            form.Close()
        except Exception:
            pass
        tell("HatchSim failed to open. Details are on the command line.")


if __name__ == "__main__":
    main()
