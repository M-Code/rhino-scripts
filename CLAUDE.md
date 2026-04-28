# CLAUDE.md

This repo contains Python scripts for Rhino 3D. Use this file as context when reading, editing, or writing scripts here.

## What This Repo Is

A collection of self-contained Rhino Python scripts. Each script can be run directly from the Rhino script editor or assigned to an alias/toolbar button.

## Conventions

- **Naming:** `verb_noun.py` pattern (e.g. `stamp_luid.py`, `build_cut_list.py`)
- **Docstrings:** Every script has a docstring at the top describing what it does and any configurable variables
- **Configurable values:** Layer names, keys, and constants are defined near the top of the relevant function with an inline `# configurable` comment
- **Self-contained:** No shared imports between scripts — each file runs independently

## Running Scripts

- Rhino command line: `_-RunPythonScript <filepath>`
- Rhino Python editor: open file, press Run
- Alias: point a Rhino alias to the script path

## Requirements

- Rhino 7 or later
- Some scripts require additional Rhino plugins — check the script's docstring

## When Writing New Scripts

- Follow the `verb_noun.py` naming pattern
- Add a docstring at the top — what it does, any configurable variables, any plugin dependencies
- Define all configurable values near the top of the relevant function with an inline comment
- Do not add shared utility imports — keep scripts self-contained
