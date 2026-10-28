// Serial acceptance of the generated assets against the maintained product engine.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {serve,chromium} from './server.mjs';

const run=path.resolve(process.argv[2]),profile=JSON.parse(fs.readFileSync(path.join(run,'profile.json'))),out=path.join(run,'acceptance');
fs.mkdirSync(out,{recursive:true});
const server=await serve(run);let browser;
const errors=[],rows=[],pauseRows=[],holds=[],threshold=profile.thresholds;
const write=(name,value)=>fs.writeFileSync(path.join(out,name),JSON.stringify(value,null,2));

async function page(viewport={width:720,height:960}){
  const p=await browser.newPage({viewport});p.setDefaultTimeout(60000);
  p.on('pageerror',error=>errors.push(String(error)));
  p.on('console',message=>{if(message.type()==='error'&&/Shader|WebGL|GLSL/.test(message.text()))errors.push(message.text());});
  await p.goto(server.url);await p.waitForFunction(()=>window.ready);
  assert(await p.evaluate(()=>engine.canvas.__stand3d().loaded),'candidate loads');
  await p.evaluate(async()=>{
    const T=await import('three'),{Stand3DBodyMotion}=await import('/engine/Stand3DBodyMotion.js'),{Stand3DGesture}=await import('/engine/Stand3DGesture.js'),{createStand3DPoseState}=await import('/lib/stand3d.js'),{createHandSurfaceProbe}=await import('/hand_surface_probe.mjs'),{createClothPenetrationProbe}=await import('/cloth_penetration_probe.mjs');
    const e=engine,r=e.rig,mesh=r.meshes.find(m=>m.name==='Geo_Body');
    window.probes={hand:createHandSurfaceProbe(mesh),cloth:createClothPenetrationProbe(mesh)};
    window.resetMotion=(name,phase=0,reduced=false,rotate=false)=>{
      const source=r.clips.find(c=>c.name===name),alternatives=rotate?r.clips.filter(c=>c.role==='speakingGesture'&&c!==source):[],sources=[source,...alternatives];
      r.gesture=new Stand3DGesture(source,alternatives,new Map(sources.map(c=>[c,r.clips.find(v=>v.name===c.holdClipName)])));
      r.bodyMotion=new Stand3DBodyMotion(r.bones);r.handClearance.reset();r.bodySwing.reset();r.swing.reset();r.slide.reset();
      r.blink=new r.blink.constructor(r.blink.timing);e.poseState=createStand3DPoseState();e.poseState.clipTime=phase;
      e.direct({mood:'calm',speaking:false,looking:false,nod:null},reduced);
    };
    window.checkFinite=()=>{for(const bone of Object.values(r.bones))if(![...bone.position.toArray(),...bone.quaternion.toArray(),...bone.scale.toArray(),...bone.matrixWorld.elements].every(Number.isFinite))throw Error('Non-finite bone: '+bone.name);};
    window.T=T;window.renderScene=e.presentScene.bind(e);e.presentScene=()=>{};
  });
  return p;
}

try{
  browser=await chromium.launch({channel:'chrome',headless:true});
  const p=await page(),gestures=await p.evaluate(()=>engine.rig.clips.filter(c=>c.role==='speakingGesture').map(c=>c.name));
  assert(gestures.length>0);
  const cases=[{name:'idle-loop',seconds:21,fps:30,phase:0,events:[]},{name:'short',seconds:3,fps:60,phase:0,events:[[.6,true],[.75,false]]},{name:'medium',seconds:4,fps:60,phase:4,events:[[.6,true],[1.3,false]]},{name:'long',seconds:11,fps:60,phase:10,events:[[.6,true],[8.6,false]]},{name:'late-phase',seconds:5,fps:60,phase:18,events:[[.6,true],[2.6,false]]},{name:'rapid',seconds:4,fps:60,phase:4,events:[[.6,true],[.75,false],[1,true],[1.1,false],[1.4,true],[1.6,false],[2,true],[2.2,false]]},{name:'reduced',seconds:3,fps:30,phase:0,reduced:true,events:[[.6,true],[1.3,false]]}];
  for(const name of gestures)for(const c of cases){
    // Idle has no selected gesture and only needs one full-loop replay.
    if(c.name==='idle-loop'&&name!==gestures[0])continue;
    const row=await p.evaluate(({name,c})=>{
      const e=engine,r=e.rig;resetMotion(name,c.phase,!!c.reduced);let event=0,maxHand=0,maxProxy=0,maxCloth=0;const failures=[];
      for(let f=0;f<Math.round(c.seconds*c.fps);f++){
        const time=f/c.fps;while(event<c.events.length&&time+1e-8>=c.events[event][0]){e.direct({mood:'calm',speaking:c.events[event++][1],looking:false,nod:null},!!c.reduced);}
        e.draw(r,1/c.fps);checkFinite();const h=probes.hand.measure();maxHand=Math.max(maxHand,h.edges);if(h.edges&&failures.length<12)failures.push({time,...h});maxProxy=Math.max(maxProxy,r.bodySwing.maxEdgePenetration);
        if(f%Math.round(c.fps/10)===0){probes.cloth.prepare();maxCloth=Math.max(maxCloth,probes.cloth.measure().maxDepth);}
      }
      return {gesture:name,case:c.name,fps:c.fps,frames:Math.round(c.seconds*c.fps),maxHand,maxProxyMm:maxProxy*1000,maxClothNearSurfaceMm:maxCloth*1000,failures};
    },{name,c});rows.push(row);write('motion.json',rows);console.log(row.gesture,row.case,row.maxHand,row.maxProxyMm,row.maxClothNearSurfaceMm);
    assert(row.maxHand<=threshold.handEdges&&row.maxProxyMm<=threshold.proxyMm&&row.maxClothNearSurfaceMm<=threshold.clothNearSurfaceMm,JSON.stringify(row));
  }
  for(const name of gestures){
    const result=await p.evaluate(name=>{
      const e=engine,r=e.rig,source=r.clips.find(c=>c.name===name),hold=r.clips.find(c=>c.name===source.holdClipName);resetMotion(name);
      let maxHand=0,maxProxy=0,maxCloth=0,maxSeam=0,previous=null,prior=null;const sequence=[],headMin=new T.Vector3(Infinity,Infinity,Infinity),headMax=new T.Vector3(-Infinity,-Infinity,-Infinity);
      for(let frame=0;frame<1560;frame++){
        const time=frame/60;if([0,30,1440].includes(frame))e.direct({mood:'calm',speaking:frame===30,looking:false,nod:null},false);e.draw(r,1/60);checkFinite();
        if(prior!==r.activeBodyClip){sequence.push({time,clip:r.activeBodyClip});prior=r.activeBodyClip;}
        maxHand=Math.max(maxHand,probes.hand.measure().edges);maxProxy=Math.max(maxProxy,r.bodySwing.maxEdgePenetration);
        if(frame%6===0){probes.cloth.prepare();maxCloth=Math.max(maxCloth,probes.cloth.measure().maxDepth);}
        if(time>4&&time<23){const head=r.bodyBones.Head.getWorldPosition(new T.Vector3());headMin.min(head);headMax.max(head);}
        const points=['LeftHand','RightHand'].map(n=>r.bodyBones[n].getWorldPosition(new T.Vector3()));
        if(previous&&r.gesture.elapsed!==null&&Math.abs(r.gesture.elapsed-source.duration-hold.duration)<.1)points.forEach((v,i)=>maxSeam=Math.max(maxSeam,v.distanceTo(previous[i])));previous=points;
      }
      return {name,hold:hold.name,frames:1560,maxHand,maxProxyMm:maxProxy*1000,maxClothNearSurfaceMm:maxCloth*1000,maxSeamWristMm:maxSeam*1000,headRangeMm:headMax.sub(headMin).multiplyScalar(1000).toArray(),sequence,holdCount:r.gesture.holdCount};
    },name);holds.push(result);write('holds.json',holds);console.log('hold',result);
    assert(result.maxHand<=threshold.handEdges&&result.maxProxyMm<=threshold.proxyMm&&result.maxClothNearSurfaceMm<=threshold.clothNearSurfaceMm&&result.maxSeamWristMm<threshold.holdSeamWristMm&&result.headRangeMm[1]>.05&&result.holdCount===1&&result.sequence.some(v=>v.clip===result.hold)&&result.sequence.at(-1).clip.includes('idle'),JSON.stringify(result));
  }
  const pauseCases=[{name:'idle',frames:360,gesture:gestures[0]},{name:'entry',frames:15,gesture:gestures[0],speak:true},...gestures.map(gesture=>({name:'held-'+gesture,frames:360,gesture,speak:true})),{name:'return',frames:180,gesture:gestures[0],speak:true,stop:135},{name:'reduced',frames:180,gesture:gestures[0],speak:true,reduced:true}];
  for(const c of pauseCases){
    const result=await p.evaluate(c=>{
      const e=engine,r=e.rig;
      const warm=()=>{resetMotion(c.gesture,0,!!c.reduced);for(let f=0;f<c.frames;f++){if(f===0&&c.speak)e.direct({mood:'calm',speaking:true,looking:false,nod:null},!!c.reduced);if(f===c.stop)e.direct({mood:'calm',speaking:false,looking:false,nod:null},!!c.reduced);e.draw(r,1/60);}};
      const snapshot=()=>{r.root.updateMatrixWorld(true);return {clock:e.poseState.clipTime,elapsed:r.gesture.elapsed,weight:r.bodySwing.clearanceWeight,points:r.meshes.map(m=>{m.updateMatrixWorld(true);m.skeleton.update();return Array.from({length:m.geometry.attributes.position.count},(_,i)=>m.getVertexPosition(i,new T.Vector3()).applyMatrix4(m.matrixWorld).toArray());})};};
      const compare=(a,b)=>{let max=0;for(let j=0;j<a.points.length;j++)for(let i=0;i<a.points[j].length;i++)max=Math.max(max,new T.Vector3().fromArray(a.points[j][i]).distanceTo(new T.Vector3().fromArray(b.points[j][i]))*1000);return {skinMm:max,clockDelta:b.clock-a.clock,elapsedEqual:a.elapsed===b.elapsed,weightDelta:b.weight-a.weight};};
      warm();e.draw(r,1/60);const normal=snapshot();warm();const before=snapshot();e.draw(r,0);const redraw=compare(before,snapshot());e.setPaused(true);e.setPaused(false);e.draw(r,0);const freeze=compare(before,snapshot());e.draw(r,1/60);const next=compare(normal,snapshot());return {case:c.name,redraw,freeze,next};
    },c);pauseRows.push(result);write('pause.json',pauseRows);
    assert([result.redraw,result.freeze,result.next].every(r=>r.skinMm<=threshold.pauseSkinMm&&r.clockDelta===0&&r.elapsedEqual&&Math.abs(r.weightDelta)<1e-10),JSON.stringify(result));
  }
  const gaps=await p.evaluate(name=>{
    const e=engine,r=e.rig;resetMotion(name);const events=[[0,false],[.5,true],[3,false],[3.5,true],[6,false],[6.15,true],[10,false],[10.5,true],[13,false],[15,true],[17,false],[17.5,true],[20,false],[23.2,true],[26,false]];let event=0,maxHand=0,maxProxy=0,gapIdleFrames=0,mouthInGap=null,last=null;const transitions=[];
    for(let f=0;f<1680;f++){const time=f/60;while(event<events.length&&time+1e-8>=events[event][0]){const speaking=events[event++][1];e.direct({mood:'calm',speaking,looking:!speaking,nod:null},false);}e.draw(r,1/60);checkFinite();maxHand=Math.max(maxHand,probes.hand.measure().edges);maxProxy=Math.max(maxProxy,r.bodySwing.maxEdgePenetration);if(time===3.25)mouthInGap=e.poseState.mouthOpen;if(((time>=3&&time<3.5)||(time>=6&&time<6.15)||(time>=10&&time<10.5)||(time>=17&&time<17.5))&&r.activeBodyClip.includes('idle'))gapIdleFrames++;if(last!==r.activeBodyClip){last=r.activeBodyClip;transitions.push({time,clip:last});}}
    return {frames:1680,maxHand,maxProxyMm:maxProxy*1000,gapIdleFrames,mouthInGap,finalIdle:r.activeBodyClip.includes('idle'),transitions};
  },gestures[0]);write('speech-gaps.json',gaps);assert(gaps.maxHand<=threshold.handEdges&&gaps.maxProxyMm<=threshold.proxyMm&&!gaps.gapIdleFrames&&gaps.mouthInGap===0&&gaps.finalIdle);
  const stability=await p.evaluate(name=>{
    const e=engine,r=e.rig;resetMotion(name,0,false,true);const clips=new Set(),moods=['calm','happy','shy','surprised','sad','angry','thinking'];let maxQError=0,maxSkinRadius=0;
    for(let f=0;f<2700;f++){const time=f/30;if(f%60===0)e.direct({mood:moods[Math.floor(time/12)%7],speaking:time%12>=2&&time%12<9,looking:time%12<2,nod:null},time>=70&&time<75);e.draw(r,1/30);checkFinite();clips.add(r.activeBodyClip);for(const bone of Object.values(r.bones))maxQError=Math.max(maxQError,Math.abs(bone.quaternion.length()-1));if(f%30===0)for(const mesh of r.meshes){mesh.updateMatrixWorld(true);mesh.skeleton.update();for(let i=0;i<mesh.geometry.attributes.position.count;i+=997){const v=mesh.getVertexPosition(i,new T.Vector3()).applyMatrix4(mesh.matrixWorld);if(!v.toArray().every(Number.isFinite))throw Error('Non-finite vertex');maxSkinRadius=Math.max(maxSkinRadius,v.length());}}}
    return {seconds:90,frames:2700,maxQError,maxSkinRadius,clips:[...clips]};
  },gestures[0]);write('stability.json',stability);assert(stability.maxQError<threshold.quaternionNormError&&stability.maxSkinRadius<5);for(const name of gestures)assert(stability.clips.includes(name));await p.close();

  // Real RAF lifecycle, with a fresh engine to avoid replacing draw in other cases.
  const rafPage=await page();await rafPage.evaluate(()=>{engine.setStill(false);engine.setPaused(false);window.startFrame=engine.frameCount;});await rafPage.waitForFunction(()=>engine.frameCount>window.startFrame+30);
  await rafPage.evaluate(()=>{engine.setPaused(true);window.frozenFrame=engine.frameCount;window.frozenClock=engine.poseState.clipTime;window.frozenBones=Object.values(engine.rig.bones).map(b=>b.getWorldPosition(new T.Vector3()).toArray());});await rafPage.waitForTimeout(150);
  const raf=await rafPage.evaluate(()=>new Promise(resolve=>{const e=engine,frozen=e.frameCount===window.frozenFrame,original=e.draw.bind(e);e.draw=(r,dt)=>{original(r,dt);let boneMm=0;Object.values(r.bones).forEach((b,i)=>boneMm=Math.max(boneMm,b.getWorldPosition(new T.Vector3()).distanceTo(new T.Vector3().fromArray(window.frozenBones[i]))*1000));e.setPaused(true);e.draw=original;resolve({frozen,dt,boneMm,clockDelta:e.poseState.clipTime-window.frozenClock});};e.setPaused(false);}));write('raf.json',raf);assert(raf.frozen&&raf.dt===0&&raf.boneMm<=threshold.pauseSkinMm&&raf.clockDelta===0);await rafPage.close();

  const compare=await browser.newPage({viewport:{width:1440,height:1000}});compare.on('pageerror',error=>errors.push(String(error)));
  await compare.goto(server.url);await compare.waitForFunction(()=>window.ready);await compare.evaluate(()=>engine.dispose());
  await compare.setContent(`<style>body{margin:0;background:#e3e8ef;font:16px system-ui}.labels{display:flex;height:40px;align-items:center}.labels b{width:50%;padding-left:20px}iframe{border:0;width:50%;height:960px;display:block;float:left}</style><div class="labels"><b>输入版本</b><b>流水线生成候选</b></div><iframe src="${server.url}/?baseline=1"></iframe><iframe src="${server.url}/"></iframe>`);
  for(const frame of compare.frames().filter(f=>f.parentFrame())){await frame.waitForFunction(()=>window.ready);await frame.evaluate(name=>{const e=engine,r=e.rig,clip=r.clips.find(c=>c.name===name);r.blink.step=()=>0;for(let i=0;i<300;i++)e.applyPose(r,clip,{...e.poseState,clipTime:(i+1)/60,headPitchDeg:0,headYawDeg:0,mouthOpen:0,shapeWeights:{}},1/60);e.presentScene();},profile.calibration.portrait.name);}
  await compare.screenshot({path:path.join(out,'comparison.png')});await compare.close();
  const mobile=await page({width:390,height:844});await mobile.evaluate(()=>{engine.draw(engine.rig,0);renderScene();});await mobile.screenshot({path:path.join(out,'mobile.png')});const mobileSize=await mobile.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));assert(mobileSize.scrollWidth<=mobileSize.width);await mobile.close();
  assert.deepEqual(errors,[]);
  write('results.json',{passed:true,motionCases:rows.length,motionFrames:rows.reduce((n,r)=>n+r.frames,0),holdCases:holds.length,holdFrames:holds.reduce((n,r)=>n+r.frames,0),pauseCases:pauseRows.length,maxHandEdges:Math.max(...rows.map(r=>r.maxHand),...holds.map(r=>r.maxHand)),maxProxyMm:Math.max(...rows.map(r=>r.maxProxyMm),...holds.map(r=>r.maxProxyMm)),maxClothNearSurfaceMm:Math.max(...rows.map(r=>r.maxClothNearSurfaceMm),...holds.map(r=>r.maxClothNearSurfaceMm)),stability,mobileSize,errors,scope:'Product engine with candidate file endpoints; local surface probes, not whole-mesh collision or full application/WebRTC acceptance'});
}catch(error){write('results.json',{passed:false,error:String(error),errors,completedMotionCases:rows.length,completedHoldCases:holds.length,completedPauseCases:pauseRows.length});throw error;}
finally{await browser?.close();await server.close();}
