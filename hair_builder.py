"""
Hair Curves builder.

Creates a native Blender Hair Curves object from the data exported
from Unreal Engine Groom.

Responsibilities
----------------
* Create Hair Curves
* Copy point positions
* Create curve attributes
* Apply transforms
* Disable Hair Dynamics
"""

from __future__ import annotations

import math
from statistics import median
from os import name

import bpy

from .curve_selection import select_group_curves
from .json_parser import curve_point_starts


# ----------------------------------------------------------
# Constants
# ----------------------------------------------------------

OBJECT_NAME = "UE Groom"

ROOT_UV_ATTRIBUTE = "surface_uv_coordinate"
COLOR_ATTRIBUTE = "ue_groom_color"
GROUP_ATTRIBUTE = "group"
CHILD_ATTRIBUTE = "is_child"
CURVE_ID_ATTRIBUTE = "id"
GUIDE_INDEX_ATTRIBUTE = "guide_curve_index"


# ----------------------------------------------------------
# Public API
# ----------------------------------------------------------

def build_hair(
    vertices: list[float],
    curves: list[dict],
    name="Hair",
    surface=None,
    context=None,
    point_radii: list[float] | None = None,
    point_colors: list[tuple[float, float, float]] | None = None,
    allow_unbound: bool = False,
) -> bpy.types.Object:
    """
    Create a Blender Hair Curves object.

    Parameters
    ----------
    vertices
        Flat XYZ vertex array.

    curves
        JSON curve metadata.

    Returns
    -------
    bpy.types.Object
    """

    if len(vertices) % 3:
        raise ValueError("The OBJ vertex array must contain complete XYZ points.")
    if point_radii is not None:
        point_count = len(vertices) // 3
        if len(point_radii) != point_count:
            raise ValueError(
                f"Hair radius count ({len(point_radii)}) does not match "
                f"point count ({point_count})."
            )
        for index, radius in enumerate(point_radii):
            if (
                not isinstance(radius, (int, float))
                or isinstance(radius, bool)
                or not math.isfinite(radius)
                or radius < 0.0
            ):
                raise ValueError(
                    f"Hair radius at point {index} must be finite and "
                    f"non-negative; got {radius!r}."
                )
    if point_colors is not None:
        point_count = len(vertices) // 3
        if len(point_colors) != point_count:
            raise ValueError(
                f"Hair color count ({len(point_colors)}) does not match "
                f"point count ({point_count})."
            )
        for index, color in enumerate(point_colors):
            if (
                not isinstance(color, (list, tuple))
                or len(color) != 3
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0.0
                    for value in color
                )
            ):
                raise ValueError(
                    f"Hair color at point {index} must contain three finite, "
                    "non-negative values."
                )
    point_starts = curve_point_starts(
        curves,
        len(vertices) // 3,
    )
    if context is None:
        context = bpy.context

    obj = _create_empty_hair(
        name,
        surface=surface,
        context=context,
        allow_unbound=allow_unbound,
    )

    hair = obj.data

    _create_curves(hair, curves)

    _write_positions(hair, vertices, curves, point_starts)
    if point_radii is not None:
        _write_radii(hair, point_radii)
    if point_colors is not None:
        _write_colors(hair, point_colors)

    _create_root_uv_attribute(hair, curves)

    _create_group_attribute(hair, curves)
    _create_child_attribute(hair, curves)
    _create_curve_id_attribute(hair, curves)
    _create_guide_index_attribute(hair, curves)

    _disable_hair_dynamics(obj)

    return obj


def build_grouped_hair(
    vertices: list[float],
    curves: list[dict],
    name: str = "Hair",
    guide_limit: int = 100000,
    children_per_guide: int = 0,
    surface=None,
    context=None,
    point_radii: list[float] | None = None,
    point_colors: list[tuple[float, float, float]] | None = None,
) -> tuple[bpy.types.Object, int, int]:
    """Build a parent controller with one native Hair Curves object per group."""
    if context is None:
        context = bpy.context
    if isinstance(children_per_guide, bool) or not isinstance(
        children_per_guide,
        int,
    ):
        raise ValueError("Hair Curves children per guide must be an integer.")
    if not 0 <= children_per_guide <= 20:
        raise ValueError("Hair Curves children per guide must be between 0 and 20.")
    if len(vertices) % 3:
        raise ValueError("The OBJ vertex array must contain complete XYZ points.")

    total_points = len(vertices) // 3
    point_starts = curve_point_starts(curves, total_points)
    for attribute_name, values in (
        ("radius", point_radii),
        ("color", point_colors),
    ):
        if values is not None and len(values) != total_points:
            raise ValueError(
                f"Hair {attribute_name} count ({len(values)}) does not match "
                f"point count ({total_points})."
            )
    guide_indices = select_group_curves(
        curves,
        guide_limit,
        guide_label="Hair Curves guide",
    )
    grouped_guides = {}
    for curve_index in guide_indices:
        curve = curves[curve_index]
        first = point_starts[curve_index]
        count = curve["count"]
        if count < 2 or first < 0 or first + count > len(vertices) // 3:
            raise ValueError(f"Curve {curve_index} has an invalid OBJ point range.")
        uv = curve["uv"]
        if (
            not isinstance(uv, (list, tuple))
            or len(uv) != 2
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in uv
            )
        ):
            raise ValueError(f"Curve {curve_index} has an invalid root UV.")
        points = [
            tuple(
                vertices[(first + point_index) * 3:
                         (first + point_index + 1) * 3]
            )
            for point_index in range(count)
        ]
        if any(not math.isfinite(value) for point in points for value in point):
            raise ValueError(f"Curve {curve_index} contains a non-finite point.")
        radii = (
            point_radii[first:first + count]
            if point_radii is not None
            else None
        )
        colors = (
            point_colors[first:first + count]
            if point_colors is not None
            else None
        )
        grouped_guides.setdefault(curve["group"], []).append(
            (curve_index, points, curve, radii, colors)
        )

    group_ids = sorted(grouped_guides)
    if surface is None:
        surface = next(
            (obj for obj in context.selected_objects if obj.type == "MESH"),
            None,
        )
    if surface is None:
        raise RuntimeError(
            "No mesh object selected.\n\n"
            "Select the character mesh before importing the Unreal Groom."
        )

    previous_active = context.view_layer.objects.active
    previous_selected = list(context.selected_objects)
    root = None
    group_objects = []
    try:
        root = bpy.data.objects.new(name, None)
        root.empty_display_type = "PLAIN_AXES"
        root["_ue_groom_group_ids"] = group_ids
        root["_ue_groom_guide_count"] = len(guide_indices)
        root["_ue_groom_children_per_guide"] = children_per_guide
        context.collection.objects.link(root)

        child_count = 0
        for group_id in group_ids:
            group_guides = grouped_guides[group_id]
            (
                group_vertices,
                group_curves,
                generated_children,
                group_radii,
                group_colors,
            ) = (
                _pack_group_curves(group_guides, children_per_guide)
            )
            child_count += generated_children
            group_obj = build_hair(
                group_vertices,
                group_curves,
                name=f"{name} Group {group_id}",
                surface=surface,
                context=context,
                point_radii=group_radii,
                point_colors=group_colors,
            )
            group_obj["_ue_groom_group_id"] = group_id
            group_obj["_ue_groom_guide_count"] = len(group_guides)
            group_obj["_ue_groom_child_count"] = generated_children
            group_obj.parent = root
            group_objects.append(group_obj)

        for selected_obj in context.selected_objects:
            selected_obj.select_set(False)
        root.select_set(True)
        context.view_layer.objects.active = root
        context.view_layer.update()
    except Exception:
        for group_obj in group_objects:
            data = group_obj.data
            bpy.data.objects.remove(group_obj, do_unlink=True)
            if data.users == 0:
                bpy.data.hair_curves.remove(data)
        if root is not None:
            bpy.data.objects.remove(root, do_unlink=True)
        _restore_selection(context, previous_active, previous_selected)
        raise

    return root, len(guide_indices), child_count


def build_grouped_hair_from_curves(
    vertices: list[float],
    curves: list[dict],
    point_radii: list[float],
    name: str = "Hair",
    context=None,
    point_colors: list[tuple[float, float, float]] | None = None,
) -> tuple[bpy.types.Object, int, int]:
    """Rebuild grouped Hair Curves without resampling or generating children."""
    if context is None:
        context = bpy.context
    if len(vertices) % 3:
        raise ValueError("Hair vertices must contain complete XYZ points.")
    point_starts = curve_point_starts(curves, len(vertices) // 3)
    if len(point_radii) != len(vertices) // 3:
        raise ValueError("Hair point radii do not match the point count.")
    if point_colors is not None and len(point_colors) != len(vertices) // 3:
        raise ValueError("Hair point colors do not match the point count.")

    grouped_indices = {}
    for curve_index, curve in enumerate(curves):
        count = curve["count"]
        if count < 2:
            raise ValueError(
                f"Curve {curve_index} has fewer than two points."
            )
        uv = curve["uv"]
        if (
            not isinstance(uv, (list, tuple))
            or len(uv) != 2
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in uv
            )
        ):
            raise ValueError(f"Curve {curve_index} has an invalid root UV.")
        is_child = curve.get(CHILD_ATTRIBUTE, 0)
        if is_child not in (0, 1, False, True):
            raise ValueError(f"Curve {curve_index} has an invalid child flag.")
        grouped_indices.setdefault(curve["group"], []).append(curve_index)

    if any(not math.isfinite(value) for value in vertices):
        raise ValueError("Hair vertices must be finite.")
    if any(
        isinstance(radius, bool)
        or not isinstance(radius, (int, float))
        or not math.isfinite(radius)
        or radius < 0.0
        for radius in point_radii
    ):
        raise ValueError("Hair point radii must be finite and non-negative.")

    group_ids = sorted(grouped_indices)
    previous_active = context.view_layer.objects.active
    previous_selected = list(context.selected_objects)
    root = None
    group_objects = []
    try:
        root = bpy.data.objects.new(name, None)
        root.empty_display_type = "PLAIN_AXES"
        root["_ue_groom_group_ids"] = group_ids
        root["_ue_groom_guide_count"] = sum(
            not curve.get(CHILD_ATTRIBUTE, 0)
            for curve in curves
        )
        root["_ue_groom_children_per_guide"] = 0
        context.collection.objects.link(root)

        child_count = 0
        for group_id in group_ids:
            group_vertices = []
            group_radii = []
            group_colors = []
            group_curves = []
            for curve_index in grouped_indices[group_id]:
                source_curve = curves[curve_index]
                first = point_starts[curve_index]
                count = source_curve["count"]
                curve = dict(source_curve)
                curve["first"] = len(group_vertices)
                group_curves.append(curve)
                group_vertices.extend(
                    vertices[point_index * 3:(point_index + 1) * 3]
                    for point_index in range(first, first + count)
                )
                group_radii.extend(point_radii[first:first + count])
                if point_colors is not None:
                    group_colors.extend(point_colors[first:first + count])

            group_vertices = [
                value
                for point in group_vertices
                for value in point
            ]
            guides = sum(
                not curve.get(CHILD_ATTRIBUTE, 0)
                for curve in group_curves
            )
            children = len(group_curves) - guides
            group_obj = build_hair(
                group_vertices,
                group_curves,
                name=f"{name} Group {group_id}",
                context=context,
                point_radii=group_radii,
                point_colors=group_colors if point_colors is not None else None,
                allow_unbound=True,
            )
            group_obj["_ue_groom_group_id"] = group_id
            group_obj["_ue_groom_guide_count"] = guides
            group_obj["_ue_groom_child_count"] = children
            group_obj.parent = root
            group_objects.append(group_obj)
            child_count += children

        for selected_obj in context.selected_objects:
            selected_obj.select_set(False)
        root.select_set(True)
        context.view_layer.objects.active = root
        context.view_layer.update()
    except Exception:
        for group_obj in group_objects:
            data = group_obj.data
            bpy.data.objects.remove(group_obj, do_unlink=True)
            if data.users == 0:
                bpy.data.hair_curves.remove(data)
        if root is not None:
            bpy.data.objects.remove(root, do_unlink=True)
        _restore_selection(context, previous_active, previous_selected)
        raise

    return root, root["_ue_groom_guide_count"], child_count


# ----------------------------------------------------------
# Hair Object
# ----------------------------------------------------------

def _create_empty_hair(
    name,
    surface=None,
    context=None,
    allow_unbound=False,
):
    if context is None:
        context = bpy.context

    if surface is None and allow_unbound:
        hair = bpy.data.hair_curves.new(name)
        obj = bpy.data.objects.new(name, hair)
        context.collection.objects.link(obj)
        return obj

    if surface is None:
        surface = next(
            (obj for obj in context.selected_objects if obj.type == "MESH"),
            None,
        )

    if surface is None:
        raise RuntimeError(
            "No mesh object selected.\n\n"
            "Select the character mesh before importing the Unreal Groom."
        )

    for selected_obj in context.selected_objects:
        selected_obj.select_set(False)
    surface.select_set(True)
    context.view_layer.objects.active = surface

    bpy.ops.object.curves_empty_hair_add()

    obj = context.active_object

    obj.name = name
    obj.data.name = name

    return obj


# ----------------------------------------------------------
# Curves
# ----------------------------------------------------------

def _create_curves(hair, curves):

    sizes = [curve["count"] for curve in curves]

    hair.add_curves(sizes)


# ----------------------------------------------------------
# Positions
# ----------------------------------------------------------

def _write_positions(hair, vertices, curves, point_starts):
    ordered_vertices = []

    for curve, first in zip(curves, point_starts):
        start = first * 3
        end = start + curve["count"] * 3
        ordered_vertices.extend(vertices[start:end])

    hair.position_data.foreach_set(
        "vector",
        ordered_vertices,
    )

    hair.update_tag()


def _write_radii(hair, radii):
    attribute = hair.attributes.get("radius")
    if attribute is None:
        attribute = hair.attributes.new(
            "radius",
            type="FLOAT",
            domain="POINT",
        )
    if attribute.domain != "POINT" or attribute.data_type != "FLOAT":
        raise RuntimeError("Hair radius must be a point float attribute.")
    attribute.data.foreach_set("value", radii)


def _write_colors(hair, colors):
    attribute = hair.attributes.get(COLOR_ATTRIBUTE)
    if attribute is None:
        attribute = hair.attributes.new(
            COLOR_ATTRIBUTE,
            type="FLOAT_COLOR",
            domain="POINT",
        )
    if attribute.domain != "POINT" or attribute.data_type != "FLOAT_COLOR":
        raise RuntimeError("Hair color must be a point float color attribute.")
    rgba_values = []
    for red, green, blue in colors:
        rgba_values.extend((red, green, blue, 1.0))
    attribute.data.foreach_set("color", rgba_values)


# ----------------------------------------------------------
# Attributes
# ----------------------------------------------------------

def _create_root_uv_attribute(hair, curves):

    attribute = hair.attributes.new(
        ROOT_UV_ATTRIBUTE,
        type='FLOAT2',
        domain='CURVE',
    )

    values = []

    for curve in curves:

        values.extend(curve["uv"])

    attribute.data.foreach_set(
        "vector",
        values,
    )


def _create_group_attribute(hair, curves):

    attribute = hair.attributes.new(
        GROUP_ATTRIBUTE,
        type='INT',
        domain='CURVE',
    )

    values = [
        curve["group"]
        for curve in curves
    ]

    attribute.data.foreach_set(
        "value",
        values,
    )


def _create_child_attribute(hair, curves):
    attribute = hair.attributes.new(
        CHILD_ATTRIBUTE,
        type="INT",
        domain="CURVE",
    )
    attribute.data.foreach_set(
        "value",
        [int(curve.get(CHILD_ATTRIBUTE, False)) for curve in curves],
    )


def _create_curve_id_attribute(hair, curves):
    attribute = hair.attributes.new(
        CURVE_ID_ATTRIBUTE,
        type="INT",
        domain="CURVE",
    )
    attribute.data.foreach_set(
        "value",
        [curve.get(CURVE_ID_ATTRIBUTE, index)
         for index, curve in enumerate(curves)],
    )


def _create_guide_index_attribute(hair, curves):
    attribute = hair.attributes.new(
        GUIDE_INDEX_ATTRIBUTE,
        type="INT",
        domain="CURVE",
    )
    attribute.data.foreach_set(
        "value",
        [
            curve.get(GUIDE_INDEX_ATTRIBUTE, index)
            for index, curve in enumerate(curves)
        ],
    )


# ----------------------------------------------------------
# Hair Dynamics
# ----------------------------------------------------------

def _disable_hair_dynamics(obj):

    modifier = obj.modifiers.get(
        "Hair Dynamics"
    )

    if modifier is None:
        return

    modifier.show_viewport = False
    modifier.show_render = False


def _pack_group_curves(group_guides, children_per_guide):
    lengths = [
        sum(math.dist(start, end) for start, end in zip(points, points[1:]))
        for _, points, *_ in group_guides
    ]
    spread = median(lengths) * 0.02 if lengths else 0.0
    guide_vertices = []
    guide_curves = []
    guide_radii = []
    guide_colors = []
    child_vertices = []
    child_curves = []
    child_radii = []
    child_colors = []
    generated_children = 0

    for guide_index, (
        curve_index,
        points,
        curve,
        curve_radii,
        curve_colors,
    ) in enumerate(group_guides):
        guide_curve = dict(curve)
        guide_curve["first"] = len(guide_vertices) // 3
        guide_curve["count"] = len(points)
        guide_curve[CHILD_ATTRIBUTE] = 0
        guide_curve[CURVE_ID_ATTRIBUTE] = curve_index * 21
        guide_curve[GUIDE_INDEX_ATTRIBUTE] = guide_index
        guide_curves.append(guide_curve)
        guide_vertices.extend(
            component
            for point in points
            for component in point
        )
        if curve_radii is not None:
            guide_radii.extend(curve_radii)
        if curve_colors is not None:
            guide_colors.extend(curve_colors)

        for child_index in range(children_per_guide):
            child = _make_child_curve(
                points,
                spread,
                curve_index,
                child_index,
                children_per_guide,
            )
            child_curve = dict(curve)
            child_curve["first"] = len(child_vertices) // 3
            child_curve["count"] = len(child)
            child_curve[CHILD_ATTRIBUTE] = 1
            child_curve[CURVE_ID_ATTRIBUTE] = (
                curve_index * 21 + child_index + 1
            )
            child_curve[GUIDE_INDEX_ATTRIBUTE] = guide_index
            child_curves.append(child_curve)
            child_vertices.extend(
                component
                for point in child
                for component in point
            )
            if curve_radii is not None:
                child_radii.extend(curve_radii)
            if curve_colors is not None:
                child_colors.extend(curve_colors)
            generated_children += 1

    guide_point_count = len(guide_vertices) // 3
    for curve in child_curves:
        curve["first"] += guide_point_count

    return (
        guide_vertices + child_vertices,
        guide_curves + child_curves,
        generated_children,
        guide_radii + child_radii if guide_radii else None,
        guide_colors + child_colors if guide_colors else None,
    )


def _make_child_curve(
    points,
    spread,
    curve_index,
    child_index,
    children_per_guide,
):
    tangent = _first_tangent(points)
    reference = (0.0, 0.0, 1.0)
    if abs(_dot(tangent, reference)) > 0.9:
        reference = (1.0, 0.0, 0.0)
    axis_x = _normalize(_cross(tangent, reference))
    axis_y = _cross(tangent, axis_x)
    phase = (
        curve_index * 2.399963229728653
        + child_index * 2.399963229728653
    )
    radial = tuple(
        axis_x[index] * math.cos(phase)
        + axis_y[index] * math.sin(phase)
        for index in range(3)
    )
    radius = spread * math.sqrt(
        (child_index + 0.5) / children_per_guide
    )

    segment_lengths = [
        math.dist(start, end)
        for start, end in zip(points, points[1:])
    ]
    total_length = sum(segment_lengths)
    elapsed = 0.0
    child_points = []
    for point_index, point in enumerate(points):
        if point_index:
            elapsed += segment_lengths[point_index - 1]
        factor = (
            elapsed / total_length
            if total_length
            else point_index / max(1, len(points) - 1)
        )
        child_points.append(
            tuple(
                point[axis] + radial[axis] * radius * factor
                for axis in range(3)
            )
        )
    return child_points


def _first_tangent(points):
    for start, end in zip(points, points[1:]):
        tangent = tuple(end[axis] - start[axis] for axis in range(3))
        if any(tangent):
            return _normalize(tangent)
    return (0.0, 0.0, 1.0)


def _normalize(vector):
    length = math.sqrt(_dot(vector, vector))
    return tuple(value / length for value in vector) if length else vector


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def _cross(left, right):
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _restore_selection(context, previous_active, previous_selected):
    for selected_obj in context.selected_objects:
        selected_obj.select_set(False)
    for selected_obj in previous_selected:
        if selected_obj.name in bpy.data.objects:
            selected_obj.select_set(True)
    context.view_layer.objects.active = (
        previous_active
        if previous_active is not None and previous_active.name in bpy.data.objects
        else None
    )