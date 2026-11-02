# Unreal Groom Importer Blender Extension

The Unreal Groom Importer Blender Extension imports Groom assets exported from Unreal Engine as native Blender Hair Curves or combable particle hair.

Hair Curves mode reconstructs the original strand layout. Particle Hair mode
creates combable guides from the same data and can optionally decimate them.
When a mesh is selected, both modes attach to its active UV map. Both modes
apply the Unreal-to-Blender coordinate conversion.

---

## Features

- Import Unreal Groom OBJ files
- Automatically reads the matching JSON metadata
- Imports as native Blender Hair Curves or combable particle hair
- Preserves full strand topology in Hair Curves mode
- Preserves root UV coordinates
- Creates `surface_uv_coordinate` attribute
- Creates `group` attribute
- Automatically applies scale and orientation correction
- Automatically loads the Geometry Nodes asset
- Automatically assigns the hair material
- Automatically disables the default Hair Dynamics modifier

---

## Requirements

- Blender 5.2 or later
- Unreal Groom Assets library included with the extension
- Groom exported using the Unreal Groom Exporter plugin

---

## Installation

1. Open **Edit → Preferences → Get Extensions**.

2. Install the Unreal Groom Blender Extension.

3. Ensure the included asset library remains inside the extension folder.

---

## Quick Start

1. Select the character mesh that the groom should be attached to. Particle
   Hair creates its own root emitter but uses the same surface-evaluated curve
   positions when a mesh is selected.

2. Choose **File → Import → Unreal Groom (.obj)**.

3. Select the exported OBJ file.

The importer automatically:

- Reads the accompanying JSON file
- Creates the selected hair representation (Hair Curves by default)
- Imports root UV data
- Applies coordinate conversion
- Loads the Geometry Nodes modifier and material for Hair Curves

The imported Hair Curves object is named after the imported file.

In the import file browser, choose **Import As** to select native Hair Curves
or **Particle Hair**. Particle Hair defaults to one editable guide per source
strand, up to 100,000 guides, with 20 segments and no generated children. This
preserves the source strand count and improves shape fidelity. Lower the guide
limit or segment count for faster editing. Simple children are optional
procedural hairs, not copies of omitted source strands, so they cannot provide
a one-to-one match. Their spread scales with the imported guides so adding
children increases density without using Blender's much larger default spread.
After importing, use **Particle Edit** mode and the **Comb** tool to groom the
particle guides.

### Note

The `.json` file must have the same filename as the `.obj` file and be located in the same folder.

Example:

```
Hair_S_Pixie.obj
Hair_S_Pixie.json
```
