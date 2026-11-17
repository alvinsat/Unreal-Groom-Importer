bl_info = {
    "name": "Unreal Groom Importer",
    "author": "Vignesh Narayan S",
    "version": (1, 0, 0),
    "blender": (5, 2, 0),
    "location": "File > Import",
    "description": "Import Unreal Engine Grooms as Blender Hair Curves or particle hair",
    "category": "Import-Export",
}

import bpy

from .importer import IMPORT_OT_unreal_groom
from .alembic_io import (
    EXPORT_OT_unreal_groom_alembic,
    IMPORT_OT_unreal_groom_alembic,
)
from .group_visibility import VIEW3D_PT_unreal_groom_group_visibility


# ----------------------------------------------------------
# File > Import Menu
# ----------------------------------------------------------

def menu_import(self, context):
    self.layout.operator(
        IMPORT_OT_unreal_groom.bl_idname,
        text="Unreal Groom (.obj)"
    )
    self.layout.operator(
        IMPORT_OT_unreal_groom_alembic.bl_idname,
        text="Unreal Groom Alembic (.abc)"
    )


def menu_export(self, context):
    self.layout.operator(
        EXPORT_OT_unreal_groom_alembic.bl_idname,
        text="Unreal Groom Alembic (.abc)"
    )


# ----------------------------------------------------------
# Registration
# ----------------------------------------------------------

classes = (
    IMPORT_OT_unreal_groom,
    IMPORT_OT_unreal_groom_alembic,
    EXPORT_OT_unreal_groom_alembic,
    VIEW3D_PT_unreal_groom_group_visibility,
)


def register():

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():

    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()