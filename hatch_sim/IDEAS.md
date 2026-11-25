# HatchSim: ideas for later

Out of scope for now. The current version previews a rigid arm, with a door that turns by a simple even ramp.

- **Free-swinging door / four-bar second link.** Right now the door turn is a simple even ramp (Door angle × arm angle ÷ Max). Next would be letting the door hang under gravity, or driving it with a real second link, so the turn comes from the mechanism instead of a typed angle.
- **Non-linear door ramp.** Ease-in/ease-out, or a start and finish arm angle for the door turn.
- **Collision / interference checking.** Flag where the door or arm hits the frame (or anything else) through the swing.
- **Image-sequence export / play animation.** A Play button, plus saving a frame per N degrees for a GIF or video.
- **Multiple hatches per file.** Several independent rigs, for example one parent layer per hatch.
- **Block instance support.** Preview and bake block instances on Door/Arm instead of skipping them.
- **Packaging as .rhp.** Ship it as a proper Rhino plug-in with a real `HatchSim` command.
