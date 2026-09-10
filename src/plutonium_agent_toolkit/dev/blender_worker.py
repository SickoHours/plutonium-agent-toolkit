"""Runs inside real Blender. Receives one validated JSON request file, never Python text.

Originally written for the author's Linux tooling (see PROVENANCE.md); unchanged in
behaviour. Bounds: 20000 objects, 5M vertices, 20000 bones/actions/images.
"""
import json
import math
from pathlib import Path
import sys
import uuid
import bpy
from mathutils import Vector, Matrix, Euler

MAX_OBJECTS = 20000
MAX_VERTICES = 5000000


def cast_register(addon):
    if addon not in sys.path:
        sys.path.insert(0, addon)
    import io_scene_cast
    if not hasattr(bpy.types.Scene, 'cast_properties'):
        io_scene_cast.register()


def import_cast_file(path):
    # Upstream captures the selected rig before importing the model. Resolve it
    # after model import for combined model/animation files without changing the
    # installed add-on. All geometry/animation decoding remains upstream.
    from types import SimpleNamespace
    from io_scene_cast import import_cast as reader
    options = SimpleNamespace(import_time=False, import_reset=True, import_skin=True,
        import_ik=True, import_constraints=True, import_blend_shapes=True,
        import_hair=False, import_merge=False,
        report=lambda levels, message: print('/'.join(levels) + ': ' + message))
    data = reader.Cast.load(str(path))
    for root in data.Roots():
        if root.ChildrenOfType(reader.Instance):
            raise ValueError('Cast world instances need a resolved scene project; use an exported model')
        for model in root.ChildrenOfType(reader.Model):
            reader.importModelNode(options, model, str(path), None)
    for root in data.Roots():
        animations = root.ChildrenOfType(reader.Animation)
        if animations:
            rigs = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
            if len(rigs) != 1:
                raise ValueError('Cast animation needs exactly one rig; provide --rig for an animation-only file')
            for animation in animations:
                bpy.context.view_layer.objects.active = rigs[0]
                rigs[0].select_set(True)
                reader.importAnimationNode(options, animation, str(path), rigs[0])
    bpy.context.view_layer.update()


def open_model(path, addon, keep=False):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == '.blend':
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
    else:
        if not keep:
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
        if suffix == '.cast':
            cast_register(addon)
            import_cast_file(path)
        elif suffix in ('.glb', '.gltf'):
            bpy.ops.import_scene.gltf(filepath=str(path), disable_bone_shape=True)
        elif suffix == '.obj':
            bpy.ops.wm.obj_import(filepath=str(path))
        elif suffix == '.fbx':
            bpy.ops.import_scene.fbx(filepath=str(path))
        else:
            raise ValueError('Unsupported model format: ' + suffix)
    if len(bpy.data.objects) > MAX_OBJECTS:
        raise ValueError('Object count exceeds bound')
    if sum(len(o.data.vertices) for o in bpy.data.objects if o.type == 'MESH') > MAX_VERTICES:
        raise ValueError('Vertex count exceeds bound')


def fcurves(action):
    seen = set()
    def unique(curves):
        for curve in curves:
            key = curve.as_pointer()
            if key not in seen:
                seen.add(key)
                yield curve
    if hasattr(action, 'fcurves'):
        yield from unique(action.fcurves)
    for layer in getattr(action, 'layers', []):
        for strip in layer.strips:
            for bag in getattr(strip, 'channelbags', []):
                yield from unique(bag.fcurves)


def inspect():
    if sum(len(o.data.bones) for o in bpy.data.objects if o.type == 'ARMATURE') > 20000:
        raise ValueError('Bone count exceeds 20000')
    if len(bpy.data.actions) > 20000 or len(bpy.data.images) > 20000:
        raise ValueError('Animation/image count exceeds 20000')
    curve_count = point_count = group_count = 0
    for o in bpy.data.objects:
        if o.type == 'MESH':
            group_count += len(o.vertex_groups) + len(o.data.materials)
    for a in bpy.data.actions:
        for c in fcurves(a):
            curve_count += 1
            point_count += len(c.keyframe_points) + len(c.sampled_points)
            if curve_count > 20000 or point_count > 1000000:
                raise ValueError('Animation exceeds 20000 curves or one million points')
    if group_count > 100000:
        raise ValueError('Mesh group/material count exceeds 100000')
    objects = []
    for o in bpy.data.objects:
        row = {'name': o.name, 'type': o.type, 'parent': o.parent.name if o.parent else None,
               'location': list(o.location), 'scale': list(o.scale),
               'matrix_world': [list(row) for row in o.matrix_world]}
        if o.type == 'MESH':
            row.update(vertices=len(o.data.vertices), polygons=len(o.data.polygons),
                       uv_layers=[x.name for x in o.data.uv_layers],
                       vertex_groups=[x.name for x in o.vertex_groups],
                       materials=[m.name if m else None for m in o.data.materials])
        elif o.type == 'ARMATURE':
            row['bones'] = [{'name': b.name, 'parent': b.parent.name if b.parent else None,
                             'head': list(b.head_local), 'tail': list(b.tail_local)} for b in o.data.bones]
        objects.append(row)
    images = []
    for im in bpy.data.images:
        if im.source not in ('FILE', 'TILED'):
            continue
        path = bpy.path.abspath(im.filepath, library=im.library)
        images.append({'name': im.name, 'path': path, 'packed': bool(im.packed_file),
                       'missing': not im.packed_file and not Path(path).is_file(),
                       'dimensions': list(im.size)})
    animations = []
    for action in bpy.data.actions:
        curves = list(fcurves(action))
        animations.append({'name': action.name, 'frame_range': list(action.frame_range),
                           'curves': len(curves), 'keyframes': sum(len(c.keyframe_points) for c in curves),
                           'sampled_points': sum(len(c.sampled_points) for c in curves)})
    return {'blender_version': bpy.app.version_string, 'objects': objects,
            'images': images, 'animations': animations,
            'fps': bpy.context.scene.render.fps / bpy.context.scene.render.fps_base,
            'totals': {'objects': len(objects),
                       'meshes': sum(o.type == 'MESH' for o in bpy.data.objects),
                       'vertices': sum(len(o.data.vertices) for o in bpy.data.objects if o.type == 'MESH'),
                       'bones': sum(len(o.data.bones) for o in bpy.data.objects if o.type == 'ARMATURE'),
                       'missing_images': sum(i['missing'] for i in images)}}


def export(path, addon):
    path = Path(path)
    ext = path.suffix.lower()
    if path.exists():
        raise ValueError('Refusing to overwrite output')
    if ext == '.blend':
        bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
    elif ext == '.cast':
        if not hasattr(bpy.types, 'EXPORT_SCENE_OT_cast'):
            try:
                cast_register(addon)
            except ValueError:
                pass
        bpy.ops.export_scene.cast(filepath=str(path), up_axis='z')
    elif ext in ('.glb', '.gltf'):
        bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB' if ext == '.glb' else 'GLTF_SEPARATE')
    elif ext == '.obj':
        bpy.ops.wm.obj_export(filepath=str(path))
    elif ext == '.fbx':
        bpy.ops.export_scene.fbx(filepath=str(path), add_leaf_bones=False)
    else:
        raise ValueError('Unsupported output format')
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError('Blender did not create the requested output')


def preview(path):
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise ValueError('No mesh to preview')
    corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    low = Vector(tuple(min(p[i] for p in corners) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in corners) for i in range(3)))
    center = (low + high) / 2
    radius = max((high - low).length, 0.1)
    bpy.ops.object.camera_add(location=center + Vector((1.2, -1.5, 1.0)) * radius)
    camera = bpy.context.object
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.clip_end = max(1000, radius * 20)
    bpy.context.scene.camera = camera
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
    scene.render.resolution_x = scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main():
    request = json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text())
    if request.get('rig'):
        open_model(request['rig'], request['cast_addon'])
    open_model(request['input'], request['cast_addon'], keep=bool(request.get('rig')))
    before = inspect()
    action = request['action']
    if action == 'transform':
        scale = request['scale']
        rotation = [math.radians(x) for x in request['rotate']]
        transform = Euler(rotation).to_matrix().to_4x4() @ Matrix.Scale(scale, 4)
        for obj in bpy.context.scene.objects:
            if obj.parent is None:
                anim = obj.animation_data
                channels = {'location', 'scale', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle',
                            'delta_location', 'delta_scale', 'delta_rotation_euler', 'delta_rotation_quaternion'}
                root_animation = anim and (anim.nla_tracks or anim.drivers or
                    (anim.action and any(fc.data_path in channels for fc in fcurves(anim.action))))
                if obj.constraints or root_animation:
                    raise ValueError('Root objects with constraints or object animation require a baked transform workflow')
                obj.matrix_world = transform @ obj.matrix_world
        bpy.context.view_layer.update()
    elif action == 'rename-bones':
        mapping = request['mapping']
        armatures = {o.data for o in bpy.data.objects if o.type == 'ARMATURE'}
        bones = [b for armature in armatures for b in armature.bones]
        names = {b.name for b in bones}
        if set(mapping) - names:
            raise ValueError('Mapping contains bone names absent from the file')
        final = [mapping.get(n, n) for n in names]
        if len(final) != len(set(final)):
            raise ValueError('Bone rename collision')
        # Two phases support swaps without Blender appending .001 suffixes.
        reserved = names | set(mapping.values())
        temp = {}
        for old in mapping:
            mid = '__pat_' + uuid.uuid4().hex
            while mid in reserved:
                mid = '__pat_' + uuid.uuid4().hex
            temp[old] = mid
            reserved.add(mid)
        for armature in armatures:
            for old, mid in temp.items():
                if old in armature.bones:
                    armature.bones[old].name = mid
            for old, mid in temp.items():
                if mid in armature.bones:
                    bone = armature.bones[mid]
                    bone.name = mapping[old]
                    if bone.name != mapping[old]:
                        raise ValueError('Blender could not preserve the requested bone name')
    elif action == 'retime':
        oldfps = before['fps']
        ratio = request['fps'] / oldfps
        # NLA strip mapping and time-dependent drivers/modifiers need baking;
        # scaling only their action keys silently changes the evaluated motion.
        for owner in bpy.data.user_map():
            animation = getattr(owner, 'animation_data', None)
            if animation and (animation.nla_tracks or animation.drivers):
                raise ValueError('Retime requires baked actions without NLA tracks or drivers')
        curves = [fc for a in bpy.data.actions for fc in fcurves(a)]
        if any(fc.modifiers or fc.sampled_points for fc in curves):
            raise ValueError('Retime requires editable keyframes without sampled curves or modifiers')
        for fc in curves:
            for k in fc.keyframe_points:
                k.co.x *= ratio
                k.handle_left.x *= ratio
                k.handle_right.x *= ratio
            fc.update()
        scene = bpy.context.scene
        scene.frame_start = round(scene.frame_start * ratio)
        scene.frame_end = round(scene.frame_end * ratio)
        scene.render.fps = request['fps']
        scene.render.fps_base = 1
    elif action == 'pack-textures':
        if before['totals']['missing_images']:
            raise ValueError('Cannot pack missing image files')
        bpy.ops.file.pack_all()
    elif action == 'preview':
        preview(request['destination'])
    if action not in ('inspect', 'preview'):
        export(request['destination'], request['cast_addon'])
    result = {'before': before, 'after': before if action == 'inspect' else inspect(), 'action': action}
    if 'destination' in request:
        result['file'] = request['destination']
    if action == 'preview':
        result['preview_context'] = 'Temporary camera and studio lighting; geometry preview, not in-game rendering'
    Path(request['result']).write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
