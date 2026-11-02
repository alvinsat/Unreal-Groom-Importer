"""
Asset loader for Unreal Groom Importer.

Loads bundled assets from GroomAssets.blend.

Responsibilities
----------------
* Append Geometry Node group
* Append Material
* Assign Geometry Nodes modifier
* Assign Material
"""

from __future__ import annotations

from pathlib import Path

import bpy


# ----------------------------------------------------------
# Constants
# ----------------------------------------------------------

ASSET_BLEND = "GroomAssets.blend"

NODE_GROUP_NAME = "UE_HairCurve"
MATERIAL_NAME = "UE_HairCurve"

ASSET_FOLDER = Path(__file__).parent / "assets"
ASSET_FILE = ASSET_FOLDER / ASSET_BLEND


# ----------------------------------------------------------
# Public API
# ----------------------------------------------------------

def load_assets():
    """
    Append bundled assets if they are not already loaded.
    """

    if not ASSET_FILE.exists():
        raise FileNotFoundError(
            f"Asset library not found:\n{ASSET_FILE}"
        )

    node_groups = []
    materials = []

    if NODE_GROUP_NAME not in bpy.data.node_groups:
        node_groups.append(NODE_GROUP_NAME)

    if MATERIAL_NAME not in bpy.data.materials:
        materials.append(MATERIAL_NAME)

    if not node_groups and not materials:
        return

    with bpy.data.libraries.load(
        str(ASSET_FILE),
        link=False,
    ) as (source, destination):

        destination.node_groups = node_groups
        destination.materials = materials


# ----------------------------------------------------------
# Geometry Nodes
# ----------------------------------------------------------

def assign_geometry_nodes(obj):
    """
    Add the bundled Geometry Nodes modifier.
    """

    load_assets()

    modifier = obj.modifiers.new(
        name="UE Groom",
        type='NODES',
    )

    modifier.node_group = bpy.data.node_groups[
        NODE_GROUP_NAME
    ]

    return modifier


# ----------------------------------------------------------
# Material
# ----------------------------------------------------------

def assign_material(obj):
    """
    Assign bundled material.
    """

    load_assets()

    material = bpy.data.materials[MATERIAL_NAME]

    curves = obj.data

    if len(curves.materials) == 0:
        curves.materials.append(material)
    else:
        curves.materials[0] = material


def assign_particle_material(obj):
    """Assign the bundled material to the groom and its group emitters."""
    load_assets()
    material = bpy.data.materials[MATERIAL_NAME]
    particle_objects = [
        obj,
        *(
            child
            for child in obj.children
            if "_ue_groom_group_id" in child
        ),
    ]

    for particle_obj in particle_objects:
        assign_material(particle_obj)
        material_index = next(
            (
                index
                for index, slot_material in enumerate(
                    particle_obj.data.materials
                )
                if slot_material == material
            ),
            None,
        )
        if material_index is None:
            raise RuntimeError(
                f"Material '{MATERIAL_NAME}' is missing from "
                f"'{particle_obj.name}'."
            )

        for particle_system in particle_obj.particle_systems:
            particle_system.settings.material = material_index + 1


# ----------------------------------------------------------
# Surface
# ----------------------------------------------------------

def assign_surface(
    obj,
    surface,
    uv_map="UVMap",
):
    """
    Bind curves to a surface mesh.
    """

    if surface is None:
        return

    obj.data.surface = surface
    obj.data.surface_uv_map = uv_map


# ----------------------------------------------------------
# Convenience
# ----------------------------------------------------------

def setup_hair(
    obj,
    surface=None,
    uv_map="UVMap",
):
    """
    Complete setup.

    * Append assets
    * Assign Geometry Nodes
    * Assign Material
    * Bind surface
    """

    load_assets()

    assign_geometry_nodes(obj)

    assign_material(obj)

    assign_surface(
        obj,
        surface,
        uv_map,
    )