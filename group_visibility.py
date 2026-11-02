"""Viewport controls for particle groom group visibility."""

from bpy.types import Panel


class VIEW3D_PT_unreal_groom_group_visibility(Panel):
    """Show or hide particle hair by imported groom group."""

    bl_label = "Groom Group Visibility"
    bl_idname = "VIEW3D_PT_unreal_groom_group_visibility"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Groom"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (
            obj is not None
            and obj.type == "MESH"
            and "_ue_groom_group_ids" in obj
        )

    def draw(self, context):
        layout = self.layout
        obj = context.object

        for group_id in obj["_ue_groom_group_ids"]:
            group_obj = next(
                (
                    child
                    for child in obj.children
                    if child.get("_ue_groom_group_id") == group_id
                ),
                None,
            )
            if group_obj is None:
                layout.label(
                    text=f"Group {group_id}: emitter missing",
                    icon="ERROR",
                )
                continue

            modifier = next(
                (
                    item
                    for item in group_obj.modifiers
                    if item.type == "PARTICLE_SYSTEM"
                ),
                None,
            )
            if modifier is None:
                layout.label(
                    text=f"Group {group_id}: modifier missing",
                    icon="ERROR",
                )
                continue

            row = layout.row(align=True)
            row.label(text=f"Group {group_id}")
            row.prop(modifier, "show_viewport", text="Viewport")
            row.prop(modifier, "show_render", text="Render")
