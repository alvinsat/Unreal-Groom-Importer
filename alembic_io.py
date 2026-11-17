"""Alembic export and grouped groom round-trip support."""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from pathlib import Path

import bpy
from bpy.props import FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Euler, Matrix, Vector

from .asset_loader import assign_material
from .group_visualizer import PREVIEW_MODIFIER_NAME
from .hair_builder import (
    CHILD_ATTRIBUTE,
    COLOR_ATTRIBUTE,
    CURVE_ID_ATTRIBUTE,
    GROUP_ATTRIBUTE,
    GUIDE_INDEX_ATTRIBUTE,
    ROOT_UV_ATTRIBUTE,
    build_grouped_hair_from_curves,
    build_hair,
)
from .json_parser import curve_point_attribute, curve_point_starts, validate


MANIFEST_FORMAT = "UE Groom Alembic"
MANIFEST_VERSION = 1
MAX_ALEMBIC_CONTROL_POINTS = 255
DEFAULT_EXPORT_SCALE = (100.0, -100.0, 100.0)
DEFAULT_EXPORT_ROTATION_X = math.radians(90.0)


class EXPORT_OT_unreal_groom_alembic(Operator, ExportHelper):
    """Export the selected groom controller as one Alembic hair object."""

    bl_idname = "export_scene.unreal_groom_alembic"
    bl_label = "Export Unreal Groom Alembic"
    bl_options = {"REGISTER"}

    filename_ext = ".abc"
    filter_glob: StringProperty(default="*.abc", options={"HIDDEN"})
    max_control_points: IntProperty(
        name="Max Control Points per Curve",
        description="Resample longer strands to stay within Unreal's 255-point limit",
        default=MAX_ALEMBIC_CONTROL_POINTS,
        min=2,
        max=MAX_ALEMBIC_CONTROL_POINTS,
    )
    export_scale: FloatVectorProperty(
        name="Export Scale",
        description="Signed uniform scale applied to groom positions and radii",
        size=3,
        subtype="XYZ",
        default=DEFAULT_EXPORT_SCALE,
    )
    rotation_x: FloatProperty(
        name="Rotation X",
        description="Export rotation around the X axis",
        subtype="ANGLE",
        default=DEFAULT_EXPORT_ROTATION_X,
    )

    def draw(self, context):
        self.layout.prop(self, "max_control_points")
        self.layout.prop(self, "export_scale")
        self.layout.prop(self, "rotation_x")

    def execute(self, context):
        filepath = Path(self.filepath).with_suffix(".abc")
        temp_object = None
        previous_active = context.view_layer.objects.active
        previous_selected = list(context.selected_objects)
        try:
            root = _selected_groom_root(context)
            (
                vertices,
                point_radii,
                point_colors,
                curves,
                group_ids,
                resampled_count,
            ) = _collect_groom(
                root,
                context,
                self.max_control_points,
                self.export_scale,
                self.rotation_x,
            )
            temp_object = build_hair(
                vertices,
                curves,
                name=filepath.stem,
                context=context,
                point_radii=point_radii,
                point_colors=point_colors,
                allow_unbound=True,
            )
            temp_object["_ue_groom_group_ids"] = group_ids

            for obj in context.selected_objects:
                obj.select_set(False)
            temp_object.select_set(True)
            context.view_layer.objects.active = temp_object
            context.view_layer.update()

            result = bpy.ops.wm.alembic_export(
                filepath=str(filepath),
                selected=True,
                export_hair=True,
                export_custom_properties=True,
                as_background_job=False,
                start=context.scene.frame_current,
                end=context.scene.frame_current,
                evaluation_mode="VIEWPORT",
            )
            if "FINISHED" not in result:
                raise RuntimeError("Blender did not complete the Alembic export.")
            if not filepath.is_file() or filepath.stat().st_size == 0:
                raise RuntimeError("The Alembic export did not create a file.")

            manifest = {
                "format": MANIFEST_FORMAT,
                "version": MANIFEST_VERSION,
                "groom_name": root.name,
                "group_ids": group_ids,
                "max_control_points": self.max_control_points,
                "resampled_curves": resampled_count,
                "curves": curves,
            }
            filepath.with_suffix(".json").write_text(
                json.dumps(manifest, indent=2),
                encoding="utf-8",
            )
            self.report(
                {"INFO"},
                f"Exported {len(curves):,} curves in {len(group_ids)} groups "
                f"to {filepath.name}; resampled {resampled_count:,} curves "
                f"to at most {self.max_control_points} points",
            )
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            if temp_object is not None:
                data = temp_object.data
                bpy.data.objects.remove(temp_object, do_unlink=True)
                if data.users == 0:
                    bpy.data.hair_curves.remove(data)
            _restore_selection(context, previous_active, previous_selected)


class IMPORT_OT_unreal_groom_alembic(Operator, ImportHelper):
    """Import this add-on's Alembic export and restore its groom groups."""

    bl_idname = "import_scene.unreal_groom_alembic"
    bl_label = "Import Unreal Groom Alembic"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".abc"
    filter_glob: StringProperty(default="*.abc", options={"HIDDEN"})

    def execute(self, context):
        filepath = Path(self.filepath)
        manifest_path = filepath.with_suffix(".json")
        if not filepath.is_file():
            self.report({"ERROR"}, f"Alembic file not found: {filepath}")
            return {"CANCELLED"}
        if not manifest_path.is_file():
            self.report(
                {"ERROR"},
                f"Missing groom group manifest: {manifest_path.name}",
            )
            return {"CANCELLED"}

        imported_objects = []
        root = None
        previous_active = context.view_layer.objects.active
        previous_selected = list(context.selected_objects)
        existing_pointers = {
            obj.as_pointer()
            for obj in bpy.data.objects
        }
        try:
            manifest = _read_manifest(manifest_path)
            result = bpy.ops.wm.alembic_import(
                filepath=str(filepath),
                as_background_job=False,
            )
            if "FINISHED" not in result:
                raise RuntimeError("Blender did not complete the Alembic import.")

            imported_objects = [
                obj
                for obj in bpy.data.objects
                if obj.as_pointer() not in existing_pointers
            ]
            curves_objects = [
                obj
                for obj in imported_objects
                if obj.type == "CURVES"
            ]
            if len(curves_objects) != 1:
                raise RuntimeError(
                    "The Alembic file must contain exactly one Hair Curves "
                    f"object; found {len(curves_objects)}."
                )

            source = curves_objects[0]
            vertices, point_radii, point_colors = _read_imported_curves(
                source,
                manifest["curves"],
            )
            root, guide_count, child_count = build_grouped_hair_from_curves(
                vertices,
                manifest["curves"],
                point_radii,
                name=manifest.get("groom_name") or filepath.stem,
                context=context,
                point_colors=point_colors,
            )
            for group_object in root.children:
                assign_material(group_object)

            self.report(
                {"INFO"},
                f"Restored {guide_count:,} guides and {child_count:,} "
                f"children in {len(root.children)} groom groups",
            )
            return {"FINISHED"}
        except Exception as error:
            if root is not None:
                for child in list(root.children):
                    data = child.data
                    bpy.data.objects.remove(child, do_unlink=True)
                    if data.users == 0:
                        bpy.data.hair_curves.remove(data)
                bpy.data.objects.remove(root, do_unlink=True)
                root = None
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            for obj in imported_objects:
                if obj.name in bpy.data.objects:
                    data = obj.data
                    bpy.data.objects.remove(obj, do_unlink=True)
                    if (
                        isinstance(data, bpy.types.Curves)
                        and data.users == 0
                    ):
                        bpy.data.hair_curves.remove(data)
            if root is None:
                _restore_selection(context, previous_active, previous_selected)


def _selected_groom_root(context):
    candidates = list(context.selected_objects)
    active = context.view_layer.objects.active
    if active is not None and active not in candidates:
        candidates.append(active)
    for obj in candidates:
        if "_ue_groom_group_ids" in obj:
            root = obj
        else:
            root = obj.parent
        if root is not None and "_ue_groom_group_ids" in root:
            return root
    raise RuntimeError(
        "Select the groom controller or one of its grouped Hair Curves objects."
    )


def _collect_groom(
    root,
    context,
    max_control_points,
    export_scale=DEFAULT_EXPORT_SCALE,
    rotation_x=DEFAULT_EXPORT_ROTATION_X,
):
    if (
        isinstance(max_control_points, bool)
        or not isinstance(max_control_points, int)
        or not 2 <= max_control_points <= MAX_ALEMBIC_CONTROL_POINTS
    ):
        raise ValueError(
            "The maximum control points per curve must be between 2 and 255."
        )
    if (
        len(export_scale) != 3
        or any(
            not math.isfinite(value) or value == 0.0
            for value in export_scale
        )
        or not math.isfinite(rotation_x)
    ):
        raise ValueError("Export scale and X rotation must be finite and scale nonzero.")
    scale_magnitudes = [abs(value) for value in export_scale]
    if any(
        not math.isclose(scale_magnitudes[0], value, rel_tol=1e-6)
        for value in scale_magnitudes[1:]
    ):
        raise ValueError(
            "Hair radius requires uniform scale magnitudes on all axes."
        )
    export_transform = (
        Euler((rotation_x, 0.0, 0.0), "XYZ").to_matrix()
        @ Matrix.Diagonal(Vector(export_scale))
    )
    radius_scale = scale_magnitudes[0]
    group_ids = list(root.get("_ue_groom_group_ids", []))
    if not group_ids or any(
        isinstance(group_id, bool) or not isinstance(group_id, int)
        for group_id in group_ids
    ) or len(set(group_ids)) != len(group_ids):
        raise RuntimeError("The selected groom controller has invalid group IDs.")

    group_objects = [
        child
        for child in root.children
        if child.type == "CURVES" and "_ue_groom_group_id" in child
    ]
    object_by_group = {}
    for obj in group_objects:
        group_id = obj["_ue_groom_group_id"]
        if group_id in object_by_group:
            raise RuntimeError(f"Groom group {group_id} has multiple objects.")
        object_by_group[group_id] = obj
    if set(object_by_group) != set(group_ids):
        raise RuntimeError(
            "The groom controller's group IDs do not match its Hair Curves objects."
        )

    preview_states = []
    for obj in group_objects:
        for modifier in obj.modifiers:
            if modifier.name == PREVIEW_MODIFIER_NAME:
                preview_states.append((modifier, modifier.show_viewport))
                modifier.show_viewport = False

    vertices = []
    point_radii = []
    point_colors = []
    curves = []
    resampled_count = 0
    has_colors = None
    try:
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        for group_id in sorted(group_ids):
            obj = object_by_group[group_id]
            evaluated = obj.evaluated_get(depsgraph)
            data = evaluated.data
            offsets = [0] * len(data.curve_offset_data)
            data.curve_offset_data.foreach_get("value", offsets)
            if len(offsets) != len(data.curves) + 1:
                raise RuntimeError(
                    f"Hair Curves object '{obj.name}' has invalid curve offsets."
                )
            positions = [0.0] * (len(data.points) * 3)
            data.position_data.foreach_get("vector", positions)
            radii = _read_point_float_attribute(data, "radius")
            colors = _read_point_color_attribute(data, COLOR_ATTRIBUTE)
            if has_colors is None:
                has_colors = colors is not None
            elif has_colors != (colors is not None):
                raise RuntimeError(
                    "Hair color must be present on every groom group or none."
                )
            child_values = _read_curve_int_attribute(
                data,
                CHILD_ATTRIBUTE,
                default=0,
            )
            ids = _read_curve_int_attribute(
                data,
                CURVE_ID_ATTRIBUTE,
                default=None,
            )
            if ids is None:
                ids = list(range(len(curves), len(curves) + len(data.curves)))
            guide_indices = _read_curve_int_attribute(
                data,
                GUIDE_INDEX_ATTRIBUTE,
                default=-1,
            )
            group_values = _read_curve_int_attribute(
                data,
                GROUP_ATTRIBUTE,
                default=group_id,
            )
            uvs = _read_curve_uv_attribute(data)
            if any(value != group_id for value in group_values):
                raise RuntimeError(
                    f"Hair Curves object '{obj.name}' contains a conflicting "
                    "group attribute."
                )

            for curve_index in range(len(data.curves)):
                first = offsets[curve_index]
                end = offsets[curve_index + 1]
                curve_points = []
                for point_index in range(first, end):
                    position = Vector(positions[
                        point_index * 3:point_index * 3 + 3
                    ])
                    world_position = export_transform @ (
                        evaluated.matrix_world @ position
                    )
                    if any(not math.isfinite(value) for value in world_position):
                        raise RuntimeError(
                            f"Hair Curves object '{obj.name}' contains a "
                            "non-finite point."
                        )
                    curve_points.append(tuple(world_position))
                curve_radii = [
                    radius_scale * radius
                    for radius in radii[first:end]
                ]
                curve_colors = colors[first:end] if colors is not None else None
                if any(
                    not math.isfinite(radius)
                    for radius in curve_radii
                ):
                    raise RuntimeError(
                        f"Hair Curves object '{obj.name}' has a radius that "
                        "cannot be represented after export scaling."
                    )
                (
                    curve_points,
                    curve_radii,
                    curve_colors,
                    was_resampled,
                ) = _resample_curve(
                    curve_points,
                    curve_radii,
                    max_control_points,
                    curve_colors,
                )
                resampled_count += int(was_resampled)
                curve = {
                    "first": len(vertices) // 3,
                    "count": len(curve_points),
                    "group": group_id,
                    "uv": uvs[curve_index],
                    "is_child": child_values[curve_index],
                    "id": ids[curve_index],
                    "guide_curve_index": guide_indices[curve_index],
                    "radius": curve_radii,
                }
                if curve_colors is not None:
                    curve["color"] = [list(color) for color in curve_colors]
                curves.append(curve)
                vertices.extend(
                    value
                    for point in curve_points
                    for value in point
                )
                point_radii.extend(curve_radii)
                if curve_colors is not None:
                    point_colors.extend(curve_colors)
    finally:
        for modifier, show_viewport in preview_states:
            modifier.show_viewport = show_viewport
        context.view_layer.update()

    validate(curves)
    if not curves:
        raise RuntimeError("The selected groom contains no curves to export.")
    return (
        vertices,
        point_radii,
        point_colors if has_colors else None,
        curves,
        sorted(group_ids),
        resampled_count,
    )


def _resample_curve(points, radii, max_control_points, colors=None):
    if len(points) != len(radii):
        raise RuntimeError("Curve point positions and radii do not match.")
    if colors is not None and len(colors) != len(points):
        raise RuntimeError("Curve point colors do not match its positions.")
    if len(points) <= max_control_points:
        return points, radii, colors, False

    segment_lengths = [
        math.dist(start, end)
        for start, end in zip(points, points[1:])
    ]
    cumulative_lengths = [0.0]
    for length in segment_lengths:
        cumulative_lengths.append(cumulative_lengths[-1] + length)
    total_length = cumulative_lengths[-1]
    resampled_points = []
    resampled_radii = []
    resampled_colors = [] if colors is not None else None

    for sample_index in range(max_control_points):
        if sample_index == 0:
            resampled_points.append(points[0])
            resampled_radii.append(radii[0])
            if resampled_colors is not None:
                resampled_colors.append(colors[0])
            continue
        if sample_index == max_control_points - 1:
            resampled_points.append(points[-1])
            resampled_radii.append(radii[-1])
            if resampled_colors is not None:
                resampled_colors.append(colors[-1])
            continue

        factor = sample_index / (max_control_points - 1)
        if total_length == 0.0:
            position = factor * (len(points) - 1)
            start_index = int(position)
            end_index = min(start_index + 1, len(points) - 1)
            blend = position - start_index
        else:
            distance = factor * total_length
            start_index = min(
                bisect_right(cumulative_lengths, distance) - 1,
                len(segment_lengths) - 1,
            )
            end_index = start_index + 1
            segment_length = segment_lengths[start_index]
            blend = (
                (distance - cumulative_lengths[start_index]) / segment_length
                if segment_length > 0.0
                else 0.0
            )
        blend = max(0.0, min(1.0, blend))

        resampled_points.append(
            tuple(
                points[start_index][axis] * (1.0 - blend)
                + points[end_index][axis] * blend
                for axis in range(3)
            )
        )
        resampled_radii.append(
            radii[start_index] * (1.0 - blend)
            + radii[end_index] * blend
        )
        if resampled_colors is not None:
            resampled_colors.append(
                tuple(
                    colors[start_index][channel] * (1.0 - blend)
                    + colors[end_index][channel] * blend
                    for channel in range(3)
                )
            )
    return resampled_points, resampled_radii, resampled_colors, True


def _read_manifest(filepath):
    with filepath.open("r", encoding="utf-8") as file:
        manifest = json.load(file)
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != MANIFEST_FORMAT
        or manifest.get("version") != MANIFEST_VERSION
    ):
        raise ValueError(
            "The JSON sidecar is not a supported Unreal Groom Alembic manifest."
        )
    max_control_points = manifest.get(
        "max_control_points",
        MAX_ALEMBIC_CONTROL_POINTS,
    )
    if (
        isinstance(max_control_points, bool)
        or not isinstance(max_control_points, int)
        or not 2 <= max_control_points <= MAX_ALEMBIC_CONTROL_POINTS
    ):
        raise ValueError("The Alembic manifest has an invalid control point limit.")
    curves = manifest.get("curves")
    if not isinstance(curves, list):
        raise ValueError("The Alembic manifest must contain a curves array.")
    validate(curves)
    group_ids = manifest.get("group_ids")
    if (
        not isinstance(group_ids, list)
        or any(
            isinstance(group_id, bool) or not isinstance(group_id, int)
            for group_id in group_ids
        )
        or len(set(group_ids)) != len(group_ids)
        or sorted(set(group_ids)) != sorted(
            {curve["group"] for curve in curves}
        )
    ):
        raise ValueError("The Alembic manifest contains inconsistent group IDs.")
    return manifest


def _read_imported_curves(source, curves):
    data = source.data
    offsets = [0] * len(data.curve_offset_data)
    data.curve_offset_data.foreach_get("value", offsets)
    if len(offsets) != len(curves) + 1:
        raise ValueError(
            "Alembic curve count does not match the groom group manifest."
        )
    for index, curve in enumerate(curves):
        if (
            curve["first"] != offsets[index]
            or curve["count"] != offsets[index + 1] - offsets[index]
        ):
            raise ValueError(
                f"Alembic curve {index} does not match its manifest point range."
            )

    starts = curve_point_starts(curves, len(data.points))
    positions = [0.0] * (len(data.points) * 3)
    data.position_data.foreach_get("vector", positions)
    vertices = []
    for point_index in range(len(data.points)):
        position = Vector(positions[point_index * 3:point_index * 3 + 3])
        world_position = source.matrix_world @ position
        if any(not math.isfinite(value) for value in world_position):
            raise RuntimeError("Alembic Hair Curves contains a non-finite point.")
        vertices.extend(world_position)

    radii = curve_point_attribute(curves, len(data.points), "radius")
    if radii is None:
        radii = _read_point_float_attribute(data, "radius")
    colors = curve_point_attribute(curves, len(data.points), "color")
    if len(starts) != len(curves):
        raise RuntimeError("The Alembic manifest has invalid curve offsets.")
    return vertices, radii, colors


def _read_point_float_attribute(data, name):
    attribute = data.attributes.get(name)
    if (
        attribute is None
        or attribute.domain != "POINT"
        or attribute.data_type != "FLOAT"
    ):
        raise RuntimeError(
            f"Hair Curves data has no point float '{name}' attribute."
        )
    values = [0.0] * len(attribute.data)
    attribute.data.foreach_get("value", values)
    for index, value in enumerate(values):
        if not math.isfinite(value):
            raise RuntimeError(
                f"Hair Curves has invalid '{name}' value at point "
                f"{index}: {value!r}."
            )
    return values


def _read_point_color_attribute(data, name):
    attribute = data.attributes.get(name)
    if attribute is None:
        return None
    if (
        attribute.domain != "POINT"
        or attribute.data_type != "FLOAT_COLOR"
    ):
        raise RuntimeError(
            f"Hair Curves attribute '{name}' must be a point float color."
        )
    rgba_values = [0.0] * (len(attribute.data) * 4)
    attribute.data.foreach_get("color", rgba_values)
    colors = [
        tuple(rgba_values[index * 4:index * 4 + 3])
        for index in range(len(attribute.data))
    ]
    for index, color in enumerate(colors):
        if any(not math.isfinite(value) or value < 0.0 for value in color):
            raise RuntimeError(
                f"Hair Curves has invalid '{name}' value at point {index}."
            )
    return colors


def _read_curve_int_attribute(data, name, default):
    attribute = data.attributes.get(name)
    if attribute is None:
        return None if default is None else [default] * len(data.curves)
    if attribute.domain != "CURVE" or attribute.data_type != "INT":
        raise RuntimeError(
            f"Hair Curves attribute '{name}' must be an integer curve attribute."
        )
    values = [0] * len(data.curves)
    attribute.data.foreach_get("value", values)
    return values


def _read_curve_uv_attribute(data):
    attribute = data.attributes.get(ROOT_UV_ATTRIBUTE)
    if attribute is None:
        return [[0.0, 0.0] for _ in data.curves]
    if attribute.domain != "CURVE" or attribute.data_type != "FLOAT2":
        raise RuntimeError(
            f"Hair Curves attribute '{ROOT_UV_ATTRIBUTE}' must be a "
            "float2 curve attribute."
        )
    values = [0.0] * (len(data.curves) * 2)
    attribute.data.foreach_get("vector", values)
    uvs = [
        values[index * 2:index * 2 + 2]
        for index in range(len(data.curves))
    ]
    if any(not math.isfinite(value) for uv in uvs for value in uv):
        raise RuntimeError(f"Hair Curves has invalid '{ROOT_UV_ATTRIBUTE}' values.")
    return uvs


def _restore_selection(context, active, selected):
    for obj in context.selected_objects:
        obj.select_set(False)
    for obj in selected:
        if obj.name in bpy.data.objects:
            obj.select_set(True)
    context.view_layer.objects.active = (
        active
        if active is not None and active.name in bpy.data.objects
        else None
    )

