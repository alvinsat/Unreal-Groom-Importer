"""Build combable legacy particle hair from Unreal Groom data."""

from __future__ import annotations

import math

import bpy

from .curve_selection import select_group_curves
from .json_parser import curve_point_starts


ROOT_UV_ATTRIBUTE = "surface_uv_coordinate"
GROUP_ATTRIBUTE = "group"


def build_particle_hair(
    vertices: list[float],
    curves: list[dict],
    name: str = "Hair",
    guide_limit: int = 100000,
    hair_step: int = 20,
    children_per_guide: int = 0,
    context=None,
) -> tuple[bpy.types.Object, int]:
    """Create a particle emitter with combable guide hairs."""
    if context is None:
        context = bpy.context

    if len(vertices) % 3:
        raise ValueError("The OBJ vertex array must contain complete XYZ points.")
    if isinstance(hair_step, bool) or not isinstance(hair_step, int):
        raise ValueError("Particle hair segments must be an integer.")
    if (
        isinstance(children_per_guide, bool)
        or not isinstance(children_per_guide, int)
        or not 0 <= children_per_guide <= 20
    ):
        raise ValueError("Simple children per guide must be between 0 and 20.")
    point_starts = curve_point_starts(curves, len(vertices) // 3)
    guides = select_group_curves(
        curves,
        guide_limit,
        guide_label="particle guide",
    )
    if not 2 <= hair_step <= 20:
        raise ValueError("Particle hair segments must be between 2 and 20.")

    guide_data = []
    for curve_index in guides:
        curve = curves[curve_index]
        first = point_starts[curve_index]
        count = curve["count"]
        if (
            isinstance(first, bool)
            or not isinstance(first, int)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or first < 0
            or count < 2
            or first + count > len(vertices) // 3
        ):
            raise ValueError(
                f"Curve {curve_index} has an invalid OBJ point range."
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

        points = [
            tuple(vertices[(first + point_index) * 3:(first + point_index + 1) * 3])
            for point_index in range(count)
        ]
        if any(not math.isfinite(value) for point in points for value in point):
            raise ValueError(f"Curve {curve_index} contains a non-finite point.")
        offsets = _resample_offsets(points, hair_step)
        guide_data.append((points[0], offsets, curve))

    mesh = None
    obj = None
    group_objects = []
    group_meshes = []
    previous_active = context.view_layer.objects.active
    previous_selected = list(context.selected_objects)
    guide_groups = {}
    for guide in guide_data:
        guide_groups.setdefault(guide[2]["group"], []).append(guide)

    try:
        mesh = bpy.data.meshes.new(f"{name} Roots")
        mesh.from_pydata([item[0] for item in guide_data], [], [])
        mesh.update()
        _create_root_attributes(mesh, guide_data)

        obj = bpy.data.objects.new(name, mesh)
        obj["_ue_groom_group_ids"] = sorted(guide_groups)
        context.collection.objects.link(obj)
        for group_id, group_guides in guide_groups.items():
            group_mesh = bpy.data.meshes.new(
                f"{name} Group {group_id} Roots"
            )
            group_meshes.append(group_mesh)
            group_mesh.from_pydata(
                [guide[0] for guide in group_guides],
                [],
                [],
            )
            group_mesh.update()
            _create_root_attributes(group_mesh, group_guides)

            group_obj = bpy.data.objects.new(
                f"{name} Group {group_id}",
                group_mesh,
            )
            group_obj["_ue_groom_group_id"] = group_id
            context.collection.objects.link(group_obj)
            group_obj.parent = obj
            group_objects.append(group_obj)

            for selected_obj in context.selected_objects:
                selected_obj.select_set(False)
            group_obj.select_set(True)
            context.view_layer.objects.active = group_obj

            bpy.ops.object.particle_system_add()
            if len(group_obj.particle_systems) != 1:
                raise RuntimeError("Blender did not create a particle system.")

            particle_system = group_obj.particle_systems[-1]
            particle_system.name = f"Groom Group {group_id}"
            settings = particle_system.settings
            settings.type = "HAIR"
            settings.count = len(group_guides)
            settings.emit_from = "VERT"
            settings.use_emit_random = False
            settings.hair_step = hair_step
            path_step = max(3, math.ceil(math.log2(hair_step + 1)))
            settings.display_step = max(settings.display_step, path_step)
            settings.render_step = max(settings.render_step, path_step)
            settings.child_type = "SIMPLE" if children_per_guide else "NONE"
            settings.child_percent = children_per_guide
            settings.rendered_child_count = children_per_guide
            if children_per_guide:
                settings.child_radius = _child_radius(group_guides)
            particle_system.use_hair_dynamics = False

            context.view_layer.update()
            evaluated_obj = group_obj.evaluated_get(
                context.evaluated_depsgraph_get()
            )
            evaluated_system = evaluated_obj.particle_systems[-1]
            evaluated_particles = evaluated_system.particles
            particle_modifier = next(
                (
                    modifier
                    for modifier in evaluated_obj.modifiers
                    if modifier.type == "PARTICLE_SYSTEM"
                    and modifier.particle_system == evaluated_system
                ),
                None,
            )
            if particle_modifier is None:
                raise RuntimeError("Blender did not create a particle modifier.")
            if len(evaluated_particles) != len(group_guides):
                raise RuntimeError(
                    f"Blender generated an unexpected number of guides for "
                    f"groom group {group_id}."
                )

            for particle, (root, offsets, _) in zip(
                evaluated_particles,
                group_guides,
            ):
                if len(particle.hair_keys) != len(offsets):
                    raise RuntimeError(
                        "Blender generated an unexpected number of hair keys."
                    )
                key_lengths = [
                    math.dist(start, end)
                    for start, end in zip(offsets, offsets[1:])
                ]
                total_length = sum(key_lengths)
                elapsed = 0.0
                for key_index, (key, offset) in enumerate(
                    zip(particle.hair_keys, offsets)
                ):
                    position = tuple(
                        root_component + offset_component
                        for root_component, offset_component in zip(root, offset)
                    )
                    # This marks the system edited so Blender preserves imported keys.
                    key.co_object_set(
                        evaluated_obj,
                        particle_modifier,
                        particle,
                        position,
                    )
                    if key_index:
                        elapsed += key_lengths[key_index - 1]
                    key.time = (
                        elapsed / total_length
                        if total_length
                        else key_index / (len(offsets) - 1)
                    )

            # Rebuild this group's path and child caches from its edited keys.
            context.view_layer.update()
            bpy.ops.object.mode_set(mode="PARTICLE_EDIT")
            bpy.ops.object.mode_set(mode="OBJECT")

        for selected_obj in context.selected_objects:
            selected_obj.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        context.view_layer.update()
    except Exception:
        active_object = context.view_layer.objects.active
        if active_object is not None and active_object.mode == "PARTICLE_EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for group_obj in group_objects:
            bpy.data.objects.remove(group_obj, do_unlink=True)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        for group_mesh in group_meshes:
            if group_mesh.users == 0:
                bpy.data.meshes.remove(group_mesh)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
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
        raise

    return obj, len(guides)


def _resample_offsets(
    points: list[tuple[float, float, float]],
    segments: int,
) -> list[tuple[float, float, float]]:
    root = points[0]
    key_count = segments + 1
    if len(points) > key_count:
        selected = [0, len(points) - 1]
        while len(selected) < key_count:
            best_gain = -1.0
            best_index = None
            for start_index, end_index in zip(selected, selected[1:]):
                direct_length = math.dist(points[start_index], points[end_index])
                for candidate in range(start_index + 1, end_index):
                    gain = (
                        math.dist(points[start_index], points[candidate])
                        + math.dist(points[candidate], points[end_index])
                        - direct_length
                    )
                    if gain > best_gain:
                        best_gain = gain
                        best_index = candidate
            if best_index is None:
                break
            selected.append(best_index)
            selected.sort()
        guide_points = [points[index] for index in selected]
    else:
        guide_points = list(points)

    guide_points.extend(
        [guide_points[-1]] * (key_count - len(guide_points))
    )
    return [
        tuple(value - origin for value, origin in zip(point, root))
        for point in guide_points
    ]


def _child_radius(guide_data) -> float:
    lengths = sorted(
        sum(math.dist(start, end) for start, end in zip(offsets, offsets[1:]))
        for _, offsets, _ in guide_data
    )
    middle = len(lengths) // 2
    median_length = (
        lengths[middle]
        if len(lengths) % 2
        else (lengths[middle - 1] + lengths[middle]) / 2
    )
    return median_length * 0.02


def _create_root_attributes(mesh, guide_data) -> None:
    uv_attribute = mesh.attributes.new(
        ROOT_UV_ATTRIBUTE,
        type="FLOAT2",
        domain="POINT",
    )
    uv_values = [
        component
        for _, _, curve in guide_data
        for component in curve["uv"]
    ]
    uv_attribute.data.foreach_set("vector", uv_values)

    group_attribute = mesh.attributes.new(
        GROUP_ATTRIBUTE,
        type="INT",
        domain="POINT",
    )
    group_attribute.data.foreach_set(
        "value",
        [curve["group"] for _, _, curve in guide_data],
    )
