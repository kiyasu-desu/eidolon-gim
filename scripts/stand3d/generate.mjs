// Regenerate authored tracks using Three.js and the actual product hand solver.
// Only derived clips cross this JS boundary; Python preserves all native IDs.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {serve, chromium} from './server.mjs';

const run = path.resolve(process.argv[2]);
const profile = JSON.parse(fs.readFileSync(path.join(run,'profile.json')));
const server = await serve(run,{generation:true});
let browser;
try {
  browser = await chromium.launch({channel:'chrome',headless:true});
  const page = await browser.newPage();
  page.setDefaultTimeout(60000);
  page.on('pageerror',error=>console.error(error));
  await page.goto(server.url);await page.waitForFunction(()=>window.ready);
  const derived = await page.evaluate(async settings=>{
    const T=await import('three'),{solveArmContact}=await import('/engine/Stand3DHandContact.js');
    const r=engine.rig,config=settings.portrait,pose=r.clips.find(c=>c.name===config.base),common=r.clips.find(c=>c.name===config.layer);
    const animated=new Set(['Spine','Spine1','Spine2','Neck','Head']);
    const base=new Map(pose.skeletal.tracks.map(t=>[t.bone,t]));
    function reset(){for(const[bone,rest]of r.rest){bone.position.copy(rest.position);bone.quaternion.copy(rest.quaternion);bone.scale.copy(rest.scale);}}
    function pinGoals(){const hips=r.bodyBones.Hips,inverse=hips.matrixWorld.clone().invert(),q=hips.getWorldQuaternion(new T.Quaternion()).invert();return ['Left','Right'].map(side=>({side,p:r.bodyBones[side+'Hand'].getWorldPosition(new T.Vector3()).applyMatrix4(inverse),q:q.clone().multiply(r.bodyBones[side+'Hand'].getWorldQuaternion(new T.Quaternion()))}));}
    function pinHands(goals){const hips=r.bodyBones.Hips;let error=0;for(const goal of goals){const hand=r.bodyBones[goal.side+'Hand'],target=goal.p.clone().applyMatrix4(hips.matrixWorld);solveArmContact(r.bodyBones[goal.side+'Arm'],r.bodyBones[goal.side+'ForeArm'],hand,target);hand.quaternion.copy(hand.parent.getWorldQuaternion(new T.Quaternion()).invert().multiply(hips.getWorldQuaternion(new T.Quaternion()).multiply(goal.q)));hand.updateWorldMatrix(false,true);error=Math.max(error,hand.getWorldPosition(new T.Vector3()).distanceTo(target));}return error;}
    const tracks=common.skeletal.tracks.map(t=>{
      const reference=base.get(t.bone),q0=new T.Quaternion().fromArray(reference.rotations[0]),inverse=new T.Quaternion().fromArray(t.rotations[0]).invert();
      const weight=['Head','Neck'].includes(r.bones[t.bone].name)?config.neckHeadWeight:config.spineWeight;
      return {bone:t.bone,positions:t.positions.map(()=>reference.positions[0]),rotations:t.rotations.map(q=>animated.has(r.bones[t.bone].name)?q0.clone().multiply(new T.Quaternion().slerp(inverse.clone().multiply(new T.Quaternion().fromArray(q)),weight)).toArray():q0.toArray())};
    });
    const setPortraitFrame=i=>{reset();for(const t of tracks){r.bones[t.bone].position.fromArray(t.positions[i]);r.bones[t.bone].quaternion.fromArray(t.rotations[i]);}r.root.updateMatrixWorld(true);};
    setPortraitFrame(0);const goals=pinGoals();let maxPortraitPinError=0;
    for(let i=0;i<tracks[0].rotations.length;i++){setPortraitFrame(i);maxPortraitPinError=Math.max(maxPortraitPinError,pinHands(goals));for(const t of tracks)t.rotations[i]=r.bones[t.bone].quaternion.toArray();}
    const portrait={name:config.name,role:'portraitIdle',duration:common.duration,sampleRate:common.sampleRate,times:common.times,sourceLoop:true,tracks:[],skeletal:{version:1,coordinates:'three-mirror-x',sampleRate:common.skeletal.sampleRate,tracks,provenance:'Authored portrait idle; Campus Avatar sources and hip-relative hand pinning; pipeline v1'},composition:{base:config.base,relativeLayer:config.layer,spineWeight:config.spineWeight,neckHeadWeight:config.neckHeadWeight,avatarVariant:'campus',handGoals:'hip-relative base-pose hand targets, offline analytic solve preserving wrist orientation'}};
    const clips=[portrait],reports=[{name:portrait.name,maxPinError:maxPortraitPinError}];
    function sample(t,time,hz){const f=T.MathUtils.clamp(time*hz,0,Math.min(t.positions.length,t.rotations.length)-1),i=Math.floor(f),j=Math.min(i+1,t.rotations.length-1);return {p:new T.Vector3().fromArray(t.positions[i]).lerp(new T.Vector3().fromArray(t.positions[j]),f-i),q:new T.Quaternion().fromArray(t.rotations[i]).normalize().slerp(new T.Quaternion().fromArray(t.rotations[j]).normalize(),f-i)};}
    for(const original of r.clips.filter(c=>c.role==='speakingGesture')){
      const h=settings.holds,count=Math.round(h.duration*h.sampleRate)+1,pinned=h.pinnedGestures.includes(original.name);
      const basePose=new Map(original.skeletal.tracks.map(t=>[t.bone,sample(t,original.duration,original.skeletal.sampleRate)]));
      const output=original.skeletal.tracks.map(t=>({bone:t.bone,positions:[],rotations:[]}));
      const setBase=()=>{reset();for(const[key,v]of basePose){r.bones[key].position.copy(v.p);r.bones[key].quaternion.copy(v.q);}r.root.updateMatrixWorld(true);};
      setBase();const handGoals=pinGoals();let maxPinError=0;
      for(let i=0;i<count;i++){
        setBase();const time=i/(count-1)*portrait.duration;
        for(const t of portrait.skeletal.tracks){const bone=r.bones[t.bone];if(!animated.has(bone.name))continue;const weight=['Neck','Head'].includes(bone.name)?h.neckHeadWeight:pinned?0:h.spineWeight;const reference=sample(t,0,portrait.skeletal.sampleRate).q,current=sample(t,i===count-1?0:time,portrait.skeletal.sampleRate).q;bone.quaternion.multiply(new T.Quaternion().slerp(reference.invert().multiply(current),weight)).normalize();}
        r.root.updateMatrixWorld(true);if(pinned)maxPinError=Math.max(maxPinError,pinHands(handGoals));
        for(const t of output){const bone=r.bones[t.bone],q=bone.quaternion.clone().normalize();if(t.rotations.length&&q.dot(new T.Quaternion().fromArray(t.rotations.at(-1)))<0)q.set(-q.x,-q.y,-q.z,-q.w);t.positions.push(bone.position.toArray().map(v=>+v.toFixed(7)));t.rotations.push(q.toArray().map(v=>+v.toFixed(7)));}
      }
      for(const t of output)if(t.positions.every(v=>v.every((n,j)=>n===t.positions[0][j]))&&t.rotations.every(v=>v.every((n,j)=>n===t.rotations[0][j]))){t.positions=[t.positions[0]];t.rotations=[t.rotations[0]];}
      const name=original.holdClipName;
      if(!name)throw Error('Gesture needs an explicit holdClipName in the input catalog: '+original.name);
      clips.push({name,role:'speakingHold',duration:h.duration,sampleRate:h.sampleRate,times:Array.from({length:count},(_,i)=>i/h.sampleRate),sourceLoop:true,tracks:[],skeletal:{version:1,coordinates:'three-mirror-x',sampleRate:h.sampleRate,tracks:output,provenance:'Authored gesture endpoint plus calibrated portrait micro-motion; pipeline v1; not an original game loop'},composition:{base:original.name,layer:portrait.name,spineWeight:pinned?0:h.spineWeight,neckHeadWeight:h.neckHeadWeight,avatarVariant:'campus',handAnchor:pinned?'hip-relative endpoints pinned offline':'authored arm pose follows chest',loop:'authored endpoints matched'}});
      reports.push({name,maxPinError,frames:count,constantTracks:output.filter(t=>t.rotations.length===1).length});
    }
    return {clips,reports};
  },profile.calibration);
  assert.equal(derived.clips.filter(c=>c.role==='portraitIdle').length,1);
  fs.writeFileSync(path.join(run,'derived.json'),JSON.stringify(derived));
  console.log(derived.reports);
} finally {
  await browser?.close();await server.close();
}
