# HatchSim

Preview how a hatch door swings on its arm. Drag a slider and the arm rotates about a fixed pivot line while the door rides on the end of it. You can also have the door turn gradually about its own axis as it opens. Bake a copy at any angle.

HatchSim never changes colors. In the preview, Rhino itself draws each object moved to its new position, so it looks exactly like the real object in any display mode (sublayer colors, materials and all). Baked copies keep your objects' own color and material settings, and the layers it creates get Rhino's default color.

Requires **Rhino 8** (it runs as Python 3, not IronPython). Units are inches and angles are in degrees.

## Run it

- **Script Editor:** open `hatch_sim.py` and press Run.
- **Command line:** `_-RunPythonScript "C:\Dev\rhino-scripts\hatch_sim\hatch_sim.py"`
- **Suggested alias** (Options > Aliases):

  ```
  hs ! _-RunPythonScript "C:\Dev\rhino-scripts\hatch_sim\hatch_sim.py"
  ```

If the window is already open, running it again just brings the window to the front.

## Set up the layers

The first time you run it in a file, it creates these layers, tells you what goes where, and stops:

| Layer | Put on it |
|---|---|
| `HatchSim::Door` | The door. Any number of objects. Sublayers count too. |
| `HatchSim::Arm` | The arm. Any number of objects. Sublayers count too. |
| `HatchSim::Fixed Axis` | **One** straight line: the pivot on the frame. |
| `HatchSim::Door Axis` | **One** straight line: where the door hangs on the arm. It must be parallel to the fixed axis. |
| `HatchSim::Baked` | Leave this empty. Bake puts its copies here. |

Model everything in the **closed** position. That position is 0°.

**Nesting:** the `HatchSim` layer can sit at the top level or inside other layers, at any depth (e.g. `Project::Hatch A::HatchSim`). HatchSim finds it wherever it is. If it's missing, a new one is made at the top level, and you can drag it into place afterward. You can also move it while the window is open; click Reload afterward. Keep only **one** layer named `HatchSim` per file. If there are two, HatchSim lists both and asks you to rename or delete one. (A layer named `HatchSim` inside the HatchSim layer's own sublayers doesn't count.)

Supported geometry: polysurfaces/surfaces, extrusions, meshes, SubD and curves. Anything else (block instances, text, dimensions, points) is skipped, and HatchSim lists what it skipped on the command line. Hidden objects (from the Hide command) are ignored.

## The window

- **Angle** box and **slider**: they stay in sync. The slider moves in 1° steps, and you can type an exact angle in the box.
- **Min / Max**: the slider's range (default 0 to 90).
- **Door angle at Max**: how far the door turns about the door axis by the time the arm reaches Max. The turn ramps evenly: at arm 0° the door is as modeled, at half of Max it has turned half the Door angle, and at Max it has turned the full amount. It's measured from how you modeled the door, so 0 keeps the door level. A negative value turns it the other way. The label beside it shows the door's turn at the current arm angle.
- **starts at __ % of Max**: delays the door turn. The door stays level until the arm reaches that percentage of Max, then ramps evenly to the full Door angle at Max. For example, with Max 150, Door angle 30 and starts at 40%, the door is level up to arm 60°, at 15° by arm 105°, and at 30° at arm 150°. At 0% (the default) it ramps from arm 0°. With a start above 0%, the door stays level below 0° too. The label under it shows the current door turn and the arm angle where the turn starts.
- **Flip direction**: swings the other way, for the arm and the door turn together. Use it if the door opens into the frame; which way is "positive" depends on which way you drew the fixed axis line.
- **Reload**: re-reads the layers. Use it after you edit geometry.
- **Bake**: copies the door, arm and door axis at the current angle (door turn included) onto `HatchSim::Baked`. The copies keep your objects' exact color settings, so anything set to By Layer takes the Baked layer's color. They aren't added to the originals' groups. One Undo removes the whole bake. The originals never move.
- **Reset**: goes back to 0°.
- **Close** (or the window X): ends the preview and turns your layers back on.

While the window is open, the **Door, Arm and Door Axis layers are turned off** so you only see the moving preview. To edit the real geometry while the window is open, turn the layer on in the Layers panel, make your edit, then click **Reload**. Reload turns the layers off again. Closing the window puts every layer back the way it was before you opened HatchSim.

If you save the file while the window is open, HatchSim turns the layers back on for the save, so the file is never saved with your door hidden.

Min, Max, Flip, Door angle, the start percentage and the last angle are saved inside the .3dm file, so they come back when you reopen it.

## If something looks wrong

- **The door or arm is missing after a crash:** turn `HatchSim::Door`, `HatchSim::Arm` and `HatchSim::Door Axis` back on in the Layers panel.
- **It swings the wrong way:** tick Flip direction.
- **The window is cut off at the bottom:** drag its edge to make it bigger. To change the starting size, raise `WINDOW_H` near the top of `hatch_sim.py`.
- **The preview is empty (the door and arm vanish when the window opens):** Rhino may be refusing to draw objects whose layer is off. Open `hatch_sim.py` and change `RHINO_DRAWS_PREVIEW = True` to `False` near the top. HatchSim then draws its own copies, which look close but don't follow every color rule.
- **Messages:** HatchSim writes everything to the Rhino command line, prefixed with `HatchSim:`.
