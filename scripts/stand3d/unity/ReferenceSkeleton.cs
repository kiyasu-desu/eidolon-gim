using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public static class ReferenceSkeleton
{
    [Serializable] public class ArrayData { public int dimension; public float[] values; }
    [Serializable] public class BoneData { public string key, name, part, parent; public Vector3 position, scale; public Quaternion rotation; }
    [Serializable] public class GroupData { public int start, count; public string material; }
    [Serializable] public class ShapeVertex { public int vertIndex; public Vector3 position; }
    [Serializable] public class ShapeData { public string blendShapeName; public ShapeVertex[] blendShapeVertices; }
    [Serializable] public class MeshData
    {
        public string name, part;
        public float[] vertices, normals, colors, tangents, boneWeights;
        public int[] indices, boneIndices;
        public string[] bones;
        public ArrayData[] bindposes, uvChannels;
        public GroupData[] groups;
        public ShapeData[] shapes;
    }
    [Serializable] public class SourceData { public string name, sha256; }
    [Serializable] public class TextureData { public string key, path; public bool srgb; public int filter, aniso, wrapU, wrapV; }
    [Serializable] public class FloatData { public string name; public float value; }
    [Serializable] public class ColorData { public string name; public Color value; }
    [Serializable] public class MapData { public string name, texture; public Vector2 scale, offset; }
    [Serializable] public class MaterialData { public string key, name; public int queue; public string[] keywords; public FloatData[] floats; public ColorData[] colors; public MapData[] maps; }
    [Serializable] public class Data { public BoneData[] bones; public MeshData[] meshes; public SourceData[] sources; public TextureData[] textures; public MaterialData[] materials; }
    static readonly Dictionary<string, Transform> bones = new Dictionary<string, Transform>();
    public static GameObject BuildSkeleton(Data data)
    {
        bones.Clear();
        var actor = new GameObject("Temari-NativeReference");
        foreach (var b in data.bones) bones.Add(b.key, new GameObject(b.name).transform);
        foreach (var b in data.bones)
        {
            var t = bones[b.key];
            t.SetParent(bones.TryGetValue(b.parent, out var parent) ? parent : actor.transform, false);
            t.localPosition = b.position; t.localRotation = b.rotation; t.localScale = b.scale;
        }
        var head = data.bones.First(b => b.part == "body" && b.name == "Head");
        foreach (var b in data.bones.Where(b => b.name == "Head_Face" || b.name == "Head_Hair")) bones[b.key].SetParent(bones[head.key], false);
        var targets = new Dictionary<Transform, Matrix4x4>();
        foreach (var m in data.meshes)
            for (int i = 0; i < m.bones.Length; i++) targets[bones[m.bones[i]]] = Matrix(m.bindposes[i].values).inverse;
        RestoreBind(actor.transform, targets);
        return actor;
    }

    static void RestoreBind(Transform transform, Dictionary<Transform, Matrix4x4> targets)
    {
        if (targets.TryGetValue(transform, out var world))
        {
            var local = transform.parent ? transform.parent.worldToLocalMatrix * world : world;
            transform.localPosition = local.GetColumn(3); transform.localRotation = local.rotation; transform.localScale = local.lossyScale;
        }
        foreach (Transform child in transform) RestoreBind(child, targets);
    }
    static Matrix4x4 Matrix(float[] entries)
    {
        var m = new Matrix4x4();
        for (int r = 0; r < 4; r++) for (int c = 0; c < 4; c++) m[r, c] = entries[r*4+c];
        return m;
    }
}
