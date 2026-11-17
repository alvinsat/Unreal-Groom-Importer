# Unreal Groom Importer Blender Extension

The Unreal Groom Importer Blender Extension imports Groom assets exported from Unreal Engine as native Blender Hair Curves or combable particle hair.

Hair Curves mode retains native source strands up to the guide limit. Particle
Hair mode creates combable guides from the same data and can optionally decimate
them.
When a mesh is selected, both modes attach to its active UV map. Both modes
apply the Unreal-to-Blender coordinate conversion.

---

## Features

- Import Unreal Groom OBJ files
- Automatically reads the matching JSON metadata
- Imports as native Blender Hair Curves or combable particle hair
- Round-trips grouped Hair Curves through Alembic with a matching JSON manifest
- Preserves source topology for each selected Hair Curves guide
- Preserves root UV coordinates
- Preserves per-point strand radii and colors when the source JSON includes them
- Creates `surface_uv_coordinate` attribute
- Creates `group` attribute
- Provides per-group visibility controls for Hair Curves and Particle Hair
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
- Assigns the bundled material to Particle Hair

Hair Curves imports create a parent controller named after the imported file,
with one native Hair Curves child object per groom group. Select the controller
and open the 3D Viewport sidebar with **N** to toggle each group's viewport and
render visibility under **Groom → Groom Group Visibility**.

Hair Curves mode offers a maximum guide count and a children-per-guide setting.
Reducing the guide count downsamples source strands while retaining at least one
guide per group; generated children are native curves that gently fan from each
guide. These additional strands increase density but do not reconstruct omitted
source strands. High child counts use more memory because the children are
stored as actual curves. The optional **Visualize Groom Groups** setting adds
colored markers at source-guide roots.
Hair Curves keeps each selected source strand's original point topology rather
than resampling it with Particle Hair's segment setting.
Each Hair Curves group also receives a radius profile, subtle length-scaled
noise, and a loose-wave stack. Waves fade in over the final 65% of each strand
with a length-scaled radius, leaving roots smooth. The curl guide map uses
stable source-guide indices so changing the child count does not change the
imported guides. Blender's default Hair Dynamics modifier remains disabled and
is separate from this shape stack.

To export a grouped Hair Curves groom, select its controller or one of its
group objects and choose **File → Export → Unreal Groom Alembic (.abc)**. The
export combines evaluated group geometry into one Alembic Hair Curves object
and resamples any strand above Unreal's 255-control-point limit. The export
dialog defaults to scale `(100, -100, 100)` and X rotation `90°`; these
transforms are applied to the exported positions and radii, not the source
groom. Scale magnitudes must remain uniform because hair radius is scalar.
It writes a same-name `.json` manifest containing each curve's groom group ID,
guide/child flag, root UV, per-point radii, optional colors, and curve index.
Blender's Alembic format does not round-trip arbitrary Hair Curves attributes,
so keep the `.abc` and `.json` together.
The Blender-to-UE manual import action expects these transforms to already be
baked into the Alembic and uses identity conversion in Unreal. If importing
this file through Unreal's native Alembic dialog instead, use identity
conversion there too; applying another scale or rotation will compound the
export transform.
Reimport both using **File → Import → Unreal Groom Alembic (.abc)** to restore
one Hair Curves object per groom group without regenerating strands.

In the import file browser, choose **Import As** to select native Hair Curves
or **Particle Hair**. Particle Hair defaults to one editable guide per source
strand, up to 100,000 guides, with 20 segments and no generated children. This
preserves the source strand count and improves shape fidelity. Lower the guide
limit or segment count for faster editing. Simple children are optional
procedural hairs, not copies of omitted source strands, so they cannot provide
a one-to-one match. Their spread scales with the imported guides so adding
children increases density without using Blender's much larger default spread.
Particle Hair uses the same bundled `UE_HairCurve` material as Hair Curves.
After importing, select a group emitter object in the Outliner and enter
**Particle Edit** mode to groom its guides with the **Comb** tool. Enable
**Visualize Groom Groups** in the import options (off by default) to add colored
markers at guide roots, with one color per group. For Hair Curves, markers
identify source guides and omit generated children. The
**Groom Group Preview** Geometry Nodes modifier can be hidden in the modifier
stack when you no longer need the markers. Markers show imported guide groups;
they do not label procedural child hairs individually. Each imported group has
its own child emitter object so its strands can be shown or hidden independently.
Select the main Particle Hair object or Hair Curves controller, open the 3D
Viewport sidebar with **N**, and use **Groom → Groom Group Visibility** to
toggle viewport and render visibility for each group.

### Note

The `.json` file must have the same filename as the `.obj` file and be located in the same folder.

Example:

```
Hair_S_Pixie.obj
Hair_S_Pixie.json
```
