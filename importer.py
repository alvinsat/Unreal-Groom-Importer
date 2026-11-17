from pathlib import Path

import bpy

from bpy.types import Operator
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from .obj_parser import SCALE, read_obj
from .json_parser import (
    curve_point_attribute,
    json_from_obj,
    read_json,
    validate,
)
from .hair_builder import build_grouped_hair, build_hair
from .particle_builder import build_particle_hair
from .asset_loader import (
    assign_hair_shape_modifiers,
    assign_particle_material,
    setup_hair,
)
from .group_visualizer import (
    add_curve_group_visualization,
    add_group_visualization,
)


def _selected_surface(context):
    return next(
        (obj for obj in context.selected_objects if obj.type == "MESH"),
        None,
    )


def _surface_uv_map(surface: bpy.types.Object) -> str:
    uv_layers = surface.data.uv_layers
    if not uv_layers:
        raise RuntimeError(
            f"Selected surface '{surface.name}' has no UV map for groom binding."
        )
    if uv_layers.active is not None:
        return uv_layers.active.name
    for name in ("DiffuseUV", "UVMap"):
        if name in uv_layers:
            return name
    return uv_layers[0].name


def _particle_source_from_curves(
    vertices: list[float],
    curves: list[dict],
    name: str,
    surface: bpy.types.Object,
    context: bpy.types.Context,
) -> tuple[list[float], list[dict]]:
    previous_active = context.view_layer.objects.active
    previous_selected = list(context.selected_objects)
    source_object = None
    source_data = None
    try:
        source_object = build_hair(
            vertices,
            curves,
            name=f"{name} Curve Source",
            surface=surface,
            context=context,
        )
        source_data = source_object.data
        setup_hair(
            source_object,
            surface=surface,
            uv_map=_surface_uv_map(surface),
        )
        context.view_layer.update()

        evaluated_data = source_object.evaluated_get(
            context.evaluated_depsgraph_get()
        ).data
        expected_offsets = [0]
        for curve in curves:
            expected_offsets.append(expected_offsets[-1] + curve["count"])

        actual_offsets = [0] * len(evaluated_data.curve_offset_data)
        evaluated_data.curve_offset_data.foreach_get("value", actual_offsets)
        if (
            len(evaluated_data.curves) != len(curves)
            or actual_offsets != expected_offsets
        ):
            raise RuntimeError(
                "The Hair Curves modifier changed the source strand topology; "
                "particle import cannot preserve strand correspondence."
            )

        evaluated_vertices = [0.0] * (len(evaluated_data.points) * 3)
        evaluated_data.position_data.foreach_get(
            "vector",
            evaluated_vertices,
        )
        sequential_curves = []
        point_start = 0
        for curve in curves:
            sequential_curve = dict(curve)
            sequential_curve["first"] = point_start
            sequential_curves.append(sequential_curve)
            point_start += curve["count"]

        return evaluated_vertices, sequential_curves
    finally:
        if source_object is not None:
            bpy.data.objects.remove(source_object, do_unlink=True)
        if source_data is not None and source_data.users == 0:
            bpy.data.hair_curves.remove(source_data)

        for selected_obj in context.selected_objects:
            selected_obj.select_set(False)
        for selected_obj in previous_selected:
            if selected_obj.name in bpy.data.objects:
                selected_obj.select_set(True)
        context.view_layer.objects.active = (
            previous_active
            if previous_active is not None
            and previous_active.name in bpy.data.objects
            else None
        )


class IMPORT_OT_unreal_groom(
    Operator,
    ImportHelper,
):
    """Import Unreal Groom"""

    bl_idname = "import_scene.unreal_groom"
    bl_label = "Import Unreal Groom"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".obj"

    filter_glob: StringProperty(
        default="*.obj",
        options={"HIDDEN"},
    )

    import_mode: EnumProperty(
        name="Import As",
        items=(
            ("CURVES", "Hair Curves", "Import native Blender Hair Curves"),
            ("PARTICLE", "Particle Hair", "Import combable particle hair"),
        ),
        default="CURVES",
    )

    particle_guide_limit: IntProperty(
        name="Maximum Guide Hairs",
        description=(
            "Reduce source strands to this many guides; use the full curve "
            "count for one guide per strand"
        ),
        default=100000,
        min=1,
        max=100000,
    )

    particle_hair_step: IntProperty(
        name="Hair Segments",
        description="Segments per guide; higher values preserve more bends but use more memory",
        default=20,
        min=2,
        max=20,
    )

    particle_children: IntProperty(
        name="Simple Children per Guide",
        description=(
            "Procedural children add density but do not reproduce omitted "
            "source strands"
        ),
        default=0,
        min=0,
        max=20,
    )

    particle_visualize_groups: BoolProperty(
        name="Visualize Groom Groups",
        description=(
            "Add colored Geometry Nodes markers at guide roots, one color "
            "per group"
        ),
        default=False,
    )

    hair_curve_guide_limit: IntProperty(
        name="Maximum Guide Hairs",
        description=(
            "Reduce source strands to this many guides; children add "
            "additional strands"
        ),
        default=100000,
        min=1,
        max=1000000,
    )

    hair_curve_children: IntProperty(
        name="Children per Guide",
        description=(
            "Generate this many additional native Hair Curves per guide; "
            "high counts use more memory"
        ),
        default=0,
        min=0,
        max=20,
    )

    hair_curve_visualize_groups: BoolProperty(
        name="Visualize Groom Groups",
        description="Show colored markers at the source guide roots",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "import_mode")
        if self.import_mode == "PARTICLE":
            layout.prop(self, "particle_guide_limit")
            layout.prop(self, "particle_hair_step")
            layout.prop(self, "particle_children")
            layout.prop(self, "particle_visualize_groups")
            layout.label(
                text="Defaults preserve source strands; lower guides/steps for speed."
            )
        else:
            layout.prop(self, "hair_curve_guide_limit")
            layout.prop(self, "hair_curve_children")
            layout.prop(self, "hair_curve_visualize_groups")
            layout.label(
                text="Children add strands; lower the guide limit to reduce count."
            )

    # ----------------------------------------------------------
    # Execute
    # ----------------------------------------------------------

    def execute(self, context):

        try:

            obj_path = Path(self.filepath)

            if not obj_path.exists():
                self.report(
                    {"ERROR"},
                    "OBJ file not found."
                )
                return {"CANCELLED"}

            json_path = json_from_obj(obj_path)

            if not json_path.exists():
                self.report(
                    {"ERROR"},
                    f"Missing JSON:\n{json_path.name}"
                )
                return {"CANCELLED"}

            #
            # Read files
            #

            vertices = read_obj(obj_path)

            curves = read_json(json_path)

            validate(curves)

            name = obj_path.stem

            #
            # Build hair
            #
            surface = _selected_surface(context)

            if self.import_mode == "PARTICLE":
                particle_vertices = vertices
                particle_curves = curves
                if surface is not None:
                    particle_vertices, particle_curves = (
                        _particle_source_from_curves(
                            vertices,
                            curves,
                            name,
                            surface,
                            context,
                        )
                    )

                hair_object, imported_guides = build_particle_hair(
                    particle_vertices,
                    particle_curves,
                    name=name,
                    guide_limit=self.particle_guide_limit,
                    hair_step=self.particle_hair_step,
                    children_per_guide=self.particle_children,
                    context=context,
                )
                assign_particle_material(hair_object)
                if self.particle_visualize_groups:
                    add_group_visualization(hair_object)
                self.report(
                    {"INFO"},
                    f"Imported {imported_guides:,} of {len(curves):,} "
                    f"particle guides ({self.particle_hair_step} segments, "
                    f"{self.particle_children} simple children each)",
                )
                return {"FINISHED"}

            point_count = len(vertices) // 3
            point_radii = curve_point_attribute(
                curves,
                point_count,
                "radius",
            )
            if point_radii is not None:
                point_radii = [radius * SCALE for radius in point_radii]
            point_colors = curve_point_attribute(
                curves,
                point_count,
                "color",
            )
            hair_object, guide_count, child_count = build_grouped_hair(
                vertices,
                curves,
                name=name,
                guide_limit=self.hair_curve_guide_limit,
                children_per_guide=self.hair_curve_children,
                surface=surface,
                context=context,
                point_radii=point_radii,
                point_colors=point_colors,
            )

            uv_map = _surface_uv_map(surface) if surface is not None else "UVMap"
            for group_object in hair_object.children:
                setup_hair(
                    group_object,
                    surface=surface,
                    uv_map=uv_map,
                )
                assign_hair_shape_modifiers(group_object)
                if self.hair_curve_visualize_groups:
                    add_curve_group_visualization(group_object)

            self.report(
                {"INFO"},
                f"Imported {guide_count:,} guide curves and "
                f"{child_count:,} child curves in "
                f"{len(hair_object.children)} groups"
            )

            return {"FINISHED"}

        except Exception as e:

            self.report(
                {"ERROR"},
                str(e),
            )

            import traceback

            traceback.print_exc()

            return {"CANCELLED"}