"""Create a Geometry Nodes preview of particle groom groups."""

from __future__ import annotations

import colorsys
import math

import bpy


GROUP_ATTRIBUTE = "group"
PREVIEW_MATERIAL_PREFIX = "UE Groom Group "
PREVIEW_MODIFIER_NAME = "Groom Group Preview"


def add_group_visualization(obj: bpy.types.Object) -> bpy.types.Modifier:
    """Add colored markers at guide roots, selected by their group attribute."""
    attribute = obj.data.attributes.get(GROUP_ATTRIBUTE)
    if (
        attribute is None
        or attribute.domain != "POINT"
        or attribute.data_type != "INT"
    ):
        raise RuntimeError(
            f"Particle emitter '{obj.name}' has no point integer "
            f"'{GROUP_ATTRIBUTE}' attribute."
        )

    group_values = [0] * len(attribute.data)
    attribute.data.foreach_get("value", group_values)
    group_ids = sorted(set(group_values))
    if not group_ids:
        raise RuntimeError("Cannot visualize groom groups without guide roots.")

    materials = {
        group_id: _group_material(group_id)
        for group_id in group_ids
    }

    node_group = bpy.data.node_groups.new(
        f"{obj.name} Group Preview",
        "GeometryNodeTree",
    )
    node_group.interface.new_socket(
        name="Geometry",
        in_out="INPUT",
        socket_type="NodeSocketGeometry",
    )
    node_group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )

    nodes = node_group.nodes
    links = node_group.links
    group_input = nodes.new("NodeGroupInput")
    group_input.location = (-900, 0)
    group_output = nodes.new("NodeGroupOutput")
    group_output.location = (800, 0)
    join_geometry = nodes.new("GeometryNodeJoinGeometry")
    join_geometry.location = (560, 0)
    links.new(group_input.outputs["Geometry"], join_geometry.inputs["Geometry"])
    links.new(join_geometry.outputs["Geometry"], group_output.inputs["Geometry"])

    bounds = [vertex.co for vertex in obj.data.vertices]
    extents = [
        max(vertex[axis] for vertex in bounds)
        - min(vertex[axis] for vertex in bounds)
        for axis in range(3)
    ]
    marker_radius = max(
        math.sqrt(sum(extent * extent for extent in extents)) * 0.008,
        0.0001,
    )

    for index, group_id in enumerate(group_ids):
        y = -index * 360
        named_attribute = nodes.new("GeometryNodeInputNamedAttribute")
        named_attribute.data_type = "INT"
        named_attribute.inputs["Name"].default_value = GROUP_ATTRIBUTE
        named_attribute.location = (-900, y - 100)

        compare = nodes.new("FunctionNodeCompare")
        compare.data_type = "INT"
        compare.operation = "EQUAL"
        compare.inputs["B"].default_value = group_id
        compare.location = (-650, y - 100)
        links.new(
            named_attribute.outputs["Attribute"],
            compare.inputs["A"],
        )

        ico_sphere = nodes.new("GeometryNodeMeshIcoSphere")
        ico_sphere.inputs["Radius"].default_value = marker_radius
        ico_sphere.inputs["Subdivisions"].default_value = 1
        ico_sphere.location = (-650, y + 100)

        set_material = nodes.new("GeometryNodeSetMaterial")
        set_material.inputs["Material"].default_value = materials[group_id]
        set_material.location = (-400, y + 100)
        links.new(ico_sphere.outputs["Mesh"], set_material.inputs["Geometry"])

        instance = nodes.new("GeometryNodeInstanceOnPoints")
        instance.location = (100, y)
        links.new(group_input.outputs["Geometry"], instance.inputs["Points"])
        links.new(compare.outputs["Result"], instance.inputs["Selection"])
        links.new(set_material.outputs["Geometry"], instance.inputs["Instance"])
        links.new(instance.outputs["Instances"], join_geometry.inputs["Geometry"])

    modifier = obj.modifiers.new(PREVIEW_MODIFIER_NAME, "NODES")
    modifier.node_group = node_group
    return modifier


def _group_material(group_id: int) -> bpy.types.Material:
    name = f"{PREVIEW_MATERIAL_PREFIX}{group_id}"
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)

    hue = (group_id * 0.618033988749895 + 0.08) % 1.0
    color = (*colorsys.hsv_to_rgb(hue, 0.78, 0.95), 1.0)
    material.diffuse_color = color
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is None:
        raise RuntimeError(f"Material '{name}' has no Principled BSDF shader.")
    shader.inputs["Base Color"].default_value = color
    return material
