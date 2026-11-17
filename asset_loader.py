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

import math
from pathlib import Path
from statistics import median

import bpy


# ----------------------------------------------------------
# Constants
# ----------------------------------------------------------

ASSET_BLEND = "GroomAssets.blend"

NODE_GROUP_NAME = "UE_HairCurve"
MATERIAL_NAME = "UE_HairCurve"

ASSET_FOLDER = Path(__file__).parent / "assets"
ASSET_FILE = ASSET_FOLDER / ASSET_BLEND
HAIR_MODIFIER_ASSET = "procedural_hair_node_assets.blend"
HAIR_MODIFIER_NAMES = (
    "Set Hair Curve Profile",
    "Hair Curves Noise",
    "Curl Hair Curves",
)
LOOSE_WAVE_GROUP_NAME = "UE Hair Loose Waves"


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


def assign_hair_shape_modifiers(obj):
    """Add a gentle profile/noise stack and loose waves along each strand."""
    if obj.type != "CURVES":
        raise TypeError("Hair shape modifiers require a native Hair Curves object.")

    groups = _load_hair_modifier_assets()
    wave_group = _get_loose_wave_group(groups["Curl Hair Curves"])
    median_length = _median_guide_length(obj)
    profile_radius = min(max(median_length * 0.0002, 0.00002), 0.0001)
    noise_distance = median_length * 0.015
    curl_radius = median_length * 0.1
    settings = (
        {
            "Replace Radius": True,
            "Radius": profile_radius,
            "Shape": 0.5,
            "Factor Min": 0.0,
            "Factor Max": 1.0,
        },
        {
            "Cumulative Offset": False,
            "Factor": 0.15,
            "Distance": noise_distance,
            "Shape": 0.5,
            "Scale": 1.0,
            "Scale along Curve": 1.0,
            "Offset per Curve": 0.0,
            "Seed": 0,
            "Preserve Length": True,
        },
    )

    for group_name, group_settings in zip(HAIR_MODIFIER_NAMES[:2], settings):
        group = groups[group_name]
        modifier = obj.modifiers.new(group_name, "NODES")
        modifier.node_group = group
        for socket_name, value in group_settings.items():
            socket = next(
                (
                    item
                    for item in group.interface.items_tree
                    if item.item_type == "SOCKET"
                    and item.in_out == "INPUT"
                    and item.name == socket_name
                ),
                None,
            )
            if socket is None:
                raise RuntimeError(
                    f"Hair modifier asset '{group_name}' has no "
                    f"'{socket_name}' input."
                )
            _set_modifier_input(modifier, socket, value)

    curl_modifier = obj.modifiers.new(
        "Curl Hair Curves (Loose Waves)",
        "NODES",
    )
    curl_modifier.node_group = wave_group
    _set_modifier_input(
        curl_modifier,
        _group_input(wave_group, "Wave Start"),
        0.35,
    )
    _set_modifier_input(
        curl_modifier,
        _group_input(wave_group, "Radius"),
        curl_radius,
    )
    _set_modifier_input(
        curl_modifier,
        _group_input(wave_group, "Frequency"),
        2.0,
    )
    _set_modifier_input(
        curl_modifier,
        _group_input(wave_group, "Subdivision"),
        1,
    )

    modifiers = tuple(
        modifier
        for modifier in obj.modifiers
        if modifier.node_group in groups.values()
    )
    return modifiers + (curl_modifier,)


def _set_modifier_input(modifier, socket, value) -> None:
    inputs = modifier.properties.inputs
    if socket.identifier not in inputs:
        raise RuntimeError(
            f"Blender did not expose the '{socket.name}' input on "
            f"modifier '{modifier.name}'."
        )
    inputs[socket.identifier]["value"] = value


def _group_input(node_group, name):
    socket = next(
        (
            item
            for item in node_group.interface.items_tree
            if item.item_type == "SOCKET"
            and item.in_out == "INPUT"
            and item.name == name
        ),
        None,
    )
    if socket is None:
        raise RuntimeError(
            f"Hair modifier group '{node_group.name}' has no '{name}' input."
        )
    return socket


def _get_loose_wave_group(curl_group):
    group = bpy.data.node_groups.get(LOOSE_WAVE_GROUP_NAME)
    if group is not None:
        if group.bl_idname != "GeometryNodeTree" or not group.is_modifier:
            raise RuntimeError(
                f"Node group '{LOOSE_WAVE_GROUP_NAME}' is not a Geometry Nodes "
                "modifier group."
            )
        return group

    group = bpy.data.node_groups.new(
        LOOSE_WAVE_GROUP_NAME,
        "GeometryNodeTree",
    )
    group.is_modifier = True
    group.interface.new_socket(
        name="Geometry",
        in_out="INPUT",
        socket_type="NodeSocketGeometry",
    )
    wave_start = group.interface.new_socket(
        name="Wave Start",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    wave_start.default_value = 0.35
    wave_start.min_value = 0.0
    wave_start.max_value = 1.0
    radius = group.interface.new_socket(
        name="Radius",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    radius.default_value = 0.001
    radius.min_value = 0.0
    frequency = group.interface.new_socket(
        name="Frequency",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    frequency.default_value = 1.0
    frequency.min_value = 0.0
    subdivision = group.interface.new_socket(
        name="Subdivision",
        in_out="INPUT",
        socket_type="NodeSocketInt",
    )
    subdivision.default_value = 1
    subdivision.min_value = 0
    subdivision.max_value = 6
    group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )

    nodes = group.nodes
    links = group.links
    group_input = nodes.new("NodeGroupInput")
    group_output = nodes.new("NodeGroupOutput")
    capture = nodes.new("GeometryNodeCaptureAttribute")
    capture.domain = "POINT"
    capture.capture_items.new("VECTOR", "Original Position")
    capture.capture_items.new("FLOAT", "Tip Mask")

    position = nodes.new("GeometryNodeInputPosition")
    curl = nodes.new("GeometryNodeGroup")
    curl.node_tree = curl_group
    curl.inputs["Curl Start"].default_value = 1.0
    curl.inputs["Random Offset"].default_value = 0.0
    curl.inputs["Factor Start"].default_value = 1.0
    curl.inputs["Factor End"].default_value = 1.0
    curl.inputs["Existing Guide Map"].default_value = True

    spline_parameter = nodes.new("GeometryNodeSplineParameter")
    tip_mask = nodes.new("ShaderNodeMapRange")
    tip_mask.clamp = True
    tip_mask.interpolation_type = "SMOOTHERSTEP"
    tip_mask.inputs["From Max"].default_value = 1.0
    tip_mask.inputs["To Min"].default_value = 0.0
    tip_mask.inputs["To Max"].default_value = 1.0

    inverse_mask = nodes.new("ShaderNodeMath")
    inverse_mask.operation = "SUBTRACT"
    inverse_mask.inputs[0].default_value = 1.0
    restore_delta = nodes.new("ShaderNodeVectorMath")
    restore_delta.operation = "SUBTRACT"
    restore_factor = nodes.new("ShaderNodeVectorMath")
    restore_factor.operation = "SCALE"
    set_position = nodes.new("GeometryNodeSetPosition")

    links.new(group_input.outputs["Geometry"], capture.inputs["Geometry"])
    links.new(position.outputs["Position"], capture.inputs["Original Position"])
    links.new(
        tip_mask.outputs["Result"],
        capture.inputs["Tip Mask"],
    )
    links.new(capture.outputs["Geometry"], curl.inputs["Geometry"])
    links.new(group_input.outputs["Radius"], curl.inputs["Radius"])
    links.new(group_input.outputs["Frequency"], curl.inputs["Frequency"])
    links.new(group_input.outputs["Subdivision"], curl.inputs["Subdivision"])
    links.new(
        group_input.outputs["Wave Start"],
        tip_mask.inputs["From Min"],
    )
    links.new(
        spline_parameter.outputs["Factor"],
        tip_mask.inputs["Value"],
    )
    links.new(capture.outputs["Tip Mask"], curl.inputs["Factor"])
    links.new(capture.outputs["Tip Mask"], inverse_mask.inputs[1])
    links.new(
        capture.outputs["Original Position"],
        restore_delta.inputs["Vector"],
    )
    links.new(position.outputs["Position"], restore_delta.inputs[1])
    links.new(restore_delta.outputs["Vector"], restore_factor.inputs["Vector"])
    links.new(inverse_mask.outputs[0], restore_factor.inputs["Scale"])
    links.new(curl.outputs["Geometry"], set_position.inputs["Geometry"])
    links.new(restore_factor.outputs["Vector"], set_position.inputs["Offset"])
    links.new(set_position.outputs["Geometry"], group_output.inputs["Geometry"])
    return group


def _load_hair_modifier_assets():
    asset_file = (
        Path(bpy.utils.system_resource("DATAFILES"))
        / "assets"
        / "nodes"
        / HAIR_MODIFIER_ASSET
    )
    if not asset_file.exists():
        raise FileNotFoundError(
            f"Blender's hair modifier asset file is missing:\n{asset_file}"
        )

    missing = [
        name
        for name in HAIR_MODIFIER_NAMES
        if name not in bpy.data.node_groups
    ]
    if missing:
        with bpy.data.libraries.load(str(asset_file), link=False) as (
            source,
            destination,
        ):
            unavailable = [
                name
                for name in missing
                if name not in source.node_groups
            ]
            if unavailable:
                raise RuntimeError(
                    "Blender's hair modifier assets are unavailable: "
                    + ", ".join(unavailable)
                )
            destination.node_groups = missing

    return {
        name: bpy.data.node_groups[name]
        for name in HAIR_MODIFIER_NAMES
    }


def _median_guide_length(obj) -> float:
    data = obj.data
    offsets = [0] * len(data.curve_offset_data)
    data.curve_offset_data.foreach_get("value", offsets)
    positions = [0.0] * (len(data.points) * 3)
    data.position_data.foreach_get("vector", positions)
    child_attribute = data.attributes.get("is_child")
    lengths = []

    for curve_index in range(len(data.curves)):
        if (
            child_attribute is not None
            and child_attribute.data[curve_index].value
        ):
            continue
        start = offsets[curve_index]
        end = offsets[curve_index + 1]
        points = [
            positions[index * 3:index * 3 + 3]
            for index in range(start, end)
        ]
        length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        if length > 0.0:
            lengths.append(length)

    if not lengths:
        raise ValueError(
            f"Hair group '{obj.name}' has no non-zero source guide length."
        )
    return median(lengths)