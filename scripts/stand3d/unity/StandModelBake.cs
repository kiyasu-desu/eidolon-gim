// Controlled rebuilt-Avatar experiment using statically recovered original profile.
// Uses the installed editor only. Never runs the original game or its DLL.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;

public static class StandModelBake
{
    [Serializable] public class Mapping { public string boneName,humanName; }
    [Serializable] public class Parameters { public float upperArmTwist,lowerArmTwist,upperLegTwist,lowerLegTwist,armStretch,legStretch,feetSpacing; public bool hasTranslationDoF; }
    [Serializable] public class Source { public string path,name,sha256; }
    [Serializable] public class Input { public string profileSHA256,referenceSHA256,resourceVersion,expectedEditor; public Mapping[] boneMap; public Parameters humanDescription; public float cmmnHipsHeight; public Source[] clips; }
    [Serializable] public class Bone { public string key; public Vector3 p,s; public Quaternion q; }
    [Serializable] public class Frame { public float time; public Bone[] bones; }
    [Serializable] public class Bake { public string name,variant; public float duration,fps=30; public bool loop; public Frame[] frames; }
    [Serializable] public class ClipResult { public string name,file; public float duration,maxActorTranslation,maxActorRotation,maxBoneLengthError,maxQuaternionNormError; public int frames,tracks; public bool finite,loop; public string[] unmappedAnimatedBones; }
    [Serializable] public class VariantResult { public string id,avatarAsset; public bool valid,human,hipNormalized; public float humanScale,hipFactor; public int mappedBones; public string[] missingBones; public Bone[] restBones; public ClipResult[] clips; }
    [Serializable] public class Report { public string editor,resourceVersion,profileSHA256,referenceSHA256,error; public string provenance="Controlled rebuilt avatars; original profile recovered statically; original runtime Avatar and same-version numerical equivalence not claimed"; public VariantResult[] variants; }
    static string Argument(string flag) { var args=Environment.GetCommandLineArgs(); int i=Array.IndexOf(args,flag); if(i<0||i+1>=args.Length)throw new Exception("Missing "+flag); return args[i+1]; }
    static string Output => Argument("-pipelineOutput");
    static bool Finite(float v) => !float.IsNaN(v)&&!float.IsInfinity(v);
    static bool Finite(Vector3 v) => Finite(v.x)&&Finite(v.y)&&Finite(v.z);
    static bool Finite(Quaternion q) => Finite(q.x)&&Finite(q.y)&&Finite(q.z)&&Finite(q.w);
    static Bone Sample(string key,Transform t) => new Bone {key=key,p=t.localPosition,q=t.localRotation,s=t.localScale};

    public static void Run()
    {
        Directory.CreateDirectory(Output);
        var report=new Report {editor=Application.unityVersion};
        try
        {
            var input=JsonUtility.FromJson<Input>(File.ReadAllText(Argument("-pipelineRequest")));
            if(Application.unityVersion!=input.expectedEditor)throw new Exception("Wrong editor: "+Application.unityVersion+" expected "+input.expectedEditor);
            report.profileSHA256=input.profileSHA256;report.referenceSHA256=input.referenceSHA256;report.resourceVersion=input.resourceVersion;
            var data=JsonUtility.FromJson<ReferenceSkeleton.Data>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath,"Reference/reference.json")));
            if(data.bones.GroupBy(b=>b.name).Any(g=>g.Count()!=1))throw new Exception("Reference names must be unique for exact key lookup");
            if(!AssetDatabase.IsValidFolder("Assets/AvatarRebuild"))AssetDatabase.CreateFolder("Assets","AvatarRebuild");
            var variants=new List<VariantResult>();
            foreach(var id in new[]{"campus"})
            {
                var variant=new VariantResult {id=id,hipNormalized=id=="campus-height",hipFactor=1};
                var folder=Path.Combine(Output,id);Directory.CreateDirectory(folder);
                var clips=new List<ClipResult>();
                foreach(var source in input.clips)
                {
                    EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
                    var actor=ReferenceSkeleton.BuildSkeleton(data);
                    var all=actor.GetComponentsInChildren<Transform>();
                    var byName=all.ToDictionary(t=>t.name,t=>t);
                    var byKey=data.bones.ToDictionary(b=>b.key,b=>byName[b.name]);
                    var body=data.bones.Where(b=>b.part=="body").ToDictionary(b=>b.name,b=>byKey[b.key]);
                    if(variant.hipNormalized)
                    {
                        var hips=body["Hips"];variant.hipFactor=input.cmmnHipsHeight/hips.localPosition.y;
                        hips.localPosition*=variant.hipFactor;hips.localScale=Vector3.one*variant.hipFactor;
                    }
                    var maps=input.boneMap.Where(m=>body.ContainsKey(m.boneName)).ToArray();
                    if(maps.Length!=52)throw new Exception("Expected 52 actual body human bones, got "+maps.Length);
                    foreach(var m in maps)if(!HumanTrait.BoneName.Contains(m.humanName))throw new Exception("Editor lacks original human name "+m.humanName);
                    var p=input.humanDescription;
                    var description=new HumanDescription {
                        human=maps.Select(m=>new HumanBone {boneName=m.boneName,humanName=m.humanName,limit=new HumanLimit {useDefaultValues=true}}).ToArray(),
                        skeleton=all.Select(t=>new SkeletonBone {name=t.name,position=t.localPosition,rotation=t.localRotation,scale=t.localScale}).ToArray(),
                        upperArmTwist=id=="legacy"?.5f:p.upperArmTwist,lowerArmTwist=id=="legacy"?.5f:p.lowerArmTwist,
                        upperLegTwist=id=="legacy"?.5f:p.upperLegTwist,lowerLegTwist=id=="legacy"?.5f:p.lowerLegTwist,
                        armStretch=p.armStretch,legStretch=p.legStretch,feetSpacing=p.feetSpacing,hasTranslationDoF=p.hasTranslationDoF
                    };
                    var avatar=AvatarBuilder.BuildHumanAvatar(actor,description);
                    if(!avatar||!avatar.isValid||!avatar.isHuman)throw new Exception("Rejected Avatar: "+id);
                    avatar.name="Temari-"+id+"-Rebuilt";
                    var animator=actor.AddComponent<Animator>();animator.avatar=avatar;animator.applyRootMotion=true;animator.cullingMode=AnimatorCullingMode.AlwaysAnimate;
                    variant.valid=avatar.isValid;variant.human=avatar.isHuman;variant.humanScale=animator.humanScale;variant.mappedBones=maps.Length;
                    variant.missingBones=input.boneMap.Where(m=>!body.ContainsKey(m.boneName)).Select(m=>m.boneName).ToArray();
                    variant.restBones=data.bones.Where(b=>b.part=="body").Select(b=>Sample(b.key,byKey[b.key])).ToArray();
                    bool persistent=clips.Count==0;
                    if(persistent)
                    {
                        variant.avatarAsset="Assets/AvatarRebuild/Temari-"+id+".asset";
                        if(AssetDatabase.LoadAssetAtPath<Avatar>(variant.avatarAsset))AssetDatabase.DeleteAsset(variant.avatarAsset);
                        AssetDatabase.CreateAsset(avatar,variant.avatarAsset);AssetDatabase.SaveAssets();
                    }
                    var bundle=AssetBundle.LoadFromFile(source.path);
                    if(!bundle)throw new Exception("Cannot load "+source.path);
                    bundle.LoadAllAssets();
                    var matches=Resources.FindObjectsOfTypeAll<AnimationClip>().Where(c=>c.name==source.name).ToArray();
                    if(matches.Length!=1)throw new Exception("Ambiguous original clip "+source.name+": "+matches.Length);
                    var clip=matches[0];if(!clip.isHumanMotion)throw new Exception("Not original Humanoid clip "+clip.name);
                    var reference=body.ToDictionary(k=>k.Key,k=>new {p=k.Value.localPosition,q=k.Value.localRotation,s=k.Value.localScale});
                    var humanKeys=new HashSet<string>(maps.Select(m=>data.bones.First(b=>b.part=="body"&&b.name==m.boneName).key));
                    var ordered=data.bones.Where(b=>humanKeys.Contains(b.key)).ToArray();
                    var result=new ClipResult {name=clip.name,duration=clip.length,frames=Mathf.CeilToInt(clip.length*30)+1,tracks=ordered.Length,loop=clip.isLooping,finite=true};
                    var graph=PlayableGraph.Create("ControlledCampusAvatar");graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
                    var playable=AnimationClipPlayable.Create(graph,clip);playable.SetApplyFootIK(true);playable.SetApplyPlayableIK(false);
                    AnimationPlayableOutput.Create(graph,"Body",animator).SetSourcePlayable(playable);graph.Play();
                    var frames=new List<Frame>();var untracked=new HashSet<string>();
                    var actorP=actor.transform.localPosition;var actorQ=actor.transform.localRotation;
                    for(int frame=0;frame<result.frames;frame++)
                    {
                        float time=Mathf.Min(frame/30f,clip.length);playable.SetTime(time);graph.Evaluate(0);
                        result.maxActorTranslation=Mathf.Max(result.maxActorTranslation,Vector3.Distance(actorP,actor.transform.localPosition));
                        result.maxActorRotation=Mathf.Max(result.maxActorRotation,Quaternion.Angle(actorQ,actor.transform.localRotation));
                        var bones=ordered.Select(b=>Sample(b.key,byKey[b.key])).ToArray();
                        foreach(var sample in bones)
                        {
                            result.finite&=Finite(sample.p)&&Finite(sample.q)&&Finite(sample.s);
                            float norm=Mathf.Sqrt(sample.q.x*sample.q.x+sample.q.y*sample.q.y+sample.q.z*sample.q.z+sample.q.w*sample.q.w);
                            result.maxQuaternionNormError=Mathf.Max(result.maxQuaternionNormError,Mathf.Abs(norm-1));
                            var name=byKey[sample.key].name;
                            if(name!="Hips")result.maxBoneLengthError=Mathf.Max(result.maxBoneLengthError,Mathf.Abs(sample.p.magnitude-reference[name].p.magnitude));
                        }
                        foreach(var bone in data.bones.Where(b=>b.part=="body"&&!humanKeys.Contains(b.key)))
                            if(Quaternion.Angle(byKey[bone.key].localRotation,reference[bone.name].q)>.05f||Vector3.Distance(byKey[bone.key].localPosition,reference[bone.name].p)>1e-5f)untracked.Add(bone.name);
                        frames.Add(new Frame {time=time,bones=bones});
                    }
                    graph.Destroy();result.unmappedAnimatedBones=untracked.OrderBy(n=>n).ToArray();
                    if(!result.finite||result.maxQuaternionNormError>1e-4f)throw new Exception("Invalid finite/norm samples "+id+" "+clip.name);
                    result.file=id+"/"+clip.name+".json";
                    File.WriteAllText(Path.Combine(Output,result.file),JsonUtility.ToJson(new Bake {name=clip.name,variant=id,duration=clip.length,loop=clip.isLooping,frames=frames.ToArray()}));
                    clips.Add(result);bundle.Unload(true);UnityEngine.Object.DestroyImmediate(actor);if(!persistent)UnityEngine.Object.DestroyImmediate(avatar);
                    Debug.Log("Avatar rebake "+id+" "+source.name+" frames="+result.frames);
                }
                variant.clips=clips.ToArray();variants.Add(variant);
            }
            report.variants=variants.ToArray();
        }
        catch(Exception error){report.error=error.ToString();Debug.LogException(error);}
        File.WriteAllText(Path.Combine(Output,"avatar-rebuild-report.json"),JsonUtility.ToJson(report,true));
        if(Application.isBatchMode)EditorApplication.Exit(report.error==null?0:1);
    }
}
