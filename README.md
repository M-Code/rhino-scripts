# RhinoScripts

A collection of Python scripts for Rhino 3D. Each script is self-contained and can be run directly from the Rhino script editor or assigned to an alias/toolbar button.

## Usage

Run any script via:
- **Rhino command line:** `_-RunPythonScript` followed by the file path
- **Script editor:** Open the file in Rhino's Python editor and press Run
- **Alias:** Assign a short alias in Rhino's alias settings pointing to the script path

## Conventions

- Each script has a docstring at the top describing what it does and any configurable variables
- Configurable values (layer names, keys, constants) are defined near the top of the relevant function and noted with an inline comment
- Scripts follow a `verb_noun` naming pattern

## Requirements

- Rhino 7 or later
- Some scripts require additional Rhino plugins (noted in their docstrings)
