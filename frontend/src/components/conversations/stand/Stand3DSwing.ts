import * as THREE from "three";
import { Stand3DCollision, type DynamicColliderSetting } from "./Stand3DCollision";

// Integration and angular projection adapted from Open Swing Dynamics, MIT.
// Copyright (c) 2026 Arin3000. See Stand3DSwing.LICENSE.
// Source: Arin3000/unity-hair-skirt-dynamics, 4d1fa5492961eb09d8f7c5620d9a060f6074caca.
// Bounded transform-chain approximation: no native root cancellation, wind,
// triangle cloth solver or exact native Float32 scheduling. Preserve bind lengths.
export type SwingSetting = {
  bone: string;
  damping: number;
  stiffness: number;
  spring: number;
  mass: number;
  pendulum: number;
  pendulumRange: number;
  dynamicType: number;
  collision?: DynamicColliderSetting;
  axisAddXToY?: number;
  axisAddXToZ?: number;
  limitInfo: {
    useLimit: number;
    axisX: { x: number; y: number };
    axisY: { x: number; y: number };
    axisZ: { x: number; y: number };
  };
};
export type SwingChainSetting = { bones: string[]; radius: number; smoothing: number; around: number };
export type SwingClearanceSettings = { version:number; clips:string[]; response:number; joints:Array<{bone:string;rotation:[number,number,number,number]}> };

type Segment = {
  bone: THREE.Bone;
  child: THREE.Object3D;
  setting: SwingSetting;
  limit: SwingSetting["limitInfo"];
  pose: THREE.Quaternion;
  solved: THREE.Quaternion;
  tip: THREE.Vector3;
  speed: THREE.Vector3;
  axis: THREE.Vector3;
  length: number;
};

const STEP = 1 / 60;
const RAD = Math.PI / 180;

export class Stand3DSwing {
  private readonly segments: Segment[];
  private readonly chains: Array<{ nodes: Segment[]; setting: SwingChainSetting }>;
  private accumulator = 0;
  private initialized = false;
  private readonly lastAnchor = new THREE.Vector3();
  private readonly clearance: Array<{segment:Segment;rotation:THREE.Quaternion}>;
  private clearanceWeight = 0;
  private readonly clearanceClips: Set<string>;
  private readonly clearanceResponse: number;
  maxPenetration = 0;
  contactCount = 0;
  maxEdgePenetration = 0;
  maxLinePenetration = 0;

  constructor(settings: SwingSetting[], bones: Record<string, THREE.Bone>, private collision?: Stand3DCollision, chains: SwingChainSetting[] = [], clearance?:SwingClearanceSettings) {
    const byBone = new Map(settings.map((s) => [bones[s.bone], s]));
    this.segments = settings.flatMap((s): Segment[] => {
      const bone = bones[s.bone];
      const child = bone?.children.find((b) => b.position.lengthSq() > 1e-10);
      if (!bone || !child) return [];
      // Native segment inertia belongs to its child; limits belong to the joint.
      const setting = byBone.get(child as THREE.Bone) ?? s;
      if (![0,1].includes(setting.dynamicType)) return [];
      const length = bone.getWorldPosition(new THREE.Vector3()).distanceTo(child.getWorldPosition(new THREE.Vector3()));
      if (length < 1e-6) return [];
      return [{ bone, child, setting, limit: s.limitInfo, pose: bone.quaternion.clone(),
        solved: bone.quaternion.clone(), tip: new THREE.Vector3(), speed: new THREE.Vector3(),
        axis: child.position.clone().normalize(), length }];
    }).sort((a, b) => depth(a.bone) - depth(b.bone));
    const byChild = new Map(this.segments.map(s => [s.child,s]));
    this.chains = chains.flatMap(setting => {
      const nodes = setting.bones.flatMap(k => { const s=byChild.get(bones[k]); return s?[s]:[]; });
      return nodes.length >= (setting.around ? 3 : 2) ? [{ nodes,setting }] : [];
    }).sort((a,b)=>depth(a.nodes[0].bone)-depth(b.nodes[0].bone));
    const correction=clearance?.version===1?clearance:undefined;
    this.clearanceClips=new Set(correction?.clips??[]);
    this.clearanceResponse=Math.max(0,Math.min(60,correction?.response??14));
    this.clearance=(correction?.joints??[]).flatMap(j=>{const segment=this.segments.find(s=>s.bone===bones[j.bone]);if(!segment?.limit.useLimit||!j.rotation.every(Number.isFinite))return [];const rotation=new THREE.Quaternion().fromArray(j.rotation);return rotation.lengthSq()>1e-12?[{segment,rotation:rotation.normalize()}]:[]});
  }

  get segmentCount(): number { return this.segments.length; }
  get slideCount(): number { return this.segments.filter(s=>s.setting.dynamicType===1).length; }
  get chainCount(): number { return this.chains.length; }
  get lineCount(): number { return this.segments.filter(s=>s.setting.collision?.type===2).length; }
  get clearanceCount():number {return this.clearance.length;}

  reset(): void {
    this.clearanceWeight=0;
    this.initialized = false;
    this.accumulator = 0;
    this.maxPenetration = 0;
    this.contactCount = 0;
    this.maxEdgePenetration = 0;
    this.maxLinePenetration = 0;
  }

  // Called after animation restores/evaluates the skeleton, before skinning.
  update(dt: number, enabled: boolean, clipName?:string): void {
    if (!enabled) { this.reset(); return; }
    if (!this.segments.length) return;
    const anchor = this.segments[0].bone.getWorldPosition(new THREE.Vector3());
    const initialize = !this.initialized || anchor.distanceToSquared(this.lastAnchor) > 0.25 || dt > 0.25;
    if (initialize) {
      for (const s of this.segments) {
        s.child.getWorldPosition(s.tip);
        s.speed.set(0, 0, 0);
        s.solved.copy(s.bone.quaternion);
      }
      this.initialized = true;
      this.accumulator = 0;
    }
    this.lastAnchor.copy(anchor);
    this.maxPenetration = 0;
    this.contactCount = 0;
    for (const s of this.segments) s.pose.copy(s.bone.quaternion);
    // Resolve initial static contacts even when the first display frame has dt=0.
    // This projects constraints without advancing the dynamics clock or velocity.
    if (initialize && this.collision) this.tick(false);
    this.accumulator += Math.max(0, Math.min(dt, 0.1));
    // No backlog after tab suspension. At most six native ticks per draw.
    let ticks = Math.min(6, Math.floor((this.accumulator + 1e-9) / STEP));
    this.accumulator -= ticks * STEP;
    while (ticks-- > 0) this.tick();
    for (const s of this.segments) {
      s.bone.quaternion.copy(s.solved);
      s.bone.updateWorldMatrix(false, true);
    }
    this.applyClearance(dt,clipName);
    this.measurePenetration();
  }

  // Asset-specific display calibration, applied afresh to the fixed-step result.
  // Keep it out of inertia and retain the authored animated-frame angle bounds.
  private applyClearance(dt:number,clipName?:string):void {
    if(!this.clearance.length)return;
    this.clearanceWeight=THREE.MathUtils.damp(this.clearanceWeight,clipName&&this.clearanceClips.has(clipName)?1:0,this.clearanceResponse,Math.max(0,Math.min(.1,dt)));
    if(this.clearanceWeight<1e-8)return;
    const originals=this.clearance.map(({segment:s})=>s.bone.quaternion.clone());
    this.measurePenetration();
    const edgeLimit=Math.max(this.maxEdgePenetration,.00499),pointLimit=this.maxPenetration+1e-5,lineLimit=this.maxLinePenetration+1e-5;
    for(const fraction of [1,.75,.5,.25,0]){
    for(let i=0;i<this.clearance.length;i++){
      const {segment:s,rotation}=this.clearance[i];
      const delta=s.pose.clone().invert().multiply(originals[i]).multiply(new THREE.Quaternion().slerp(rotation,this.clearanceWeight*fraction));
      const angle=new THREE.Euler().setFromQuaternion(delta,'YXZ'),l=s.limit;
      angle.x=THREE.MathUtils.clamp(angle.x,l.axisX.x*RAD,l.axisX.y*RAD);
      angle.y=THREE.MathUtils.clamp(angle.y,-l.axisY.y*RAD,-l.axisY.x*RAD);
      angle.z=THREE.MathUtils.clamp(angle.z,-l.axisZ.y*RAD,-l.axisZ.x*RAD);
      s.bone.quaternion.copy(s.pose).multiply(new THREE.Quaternion().setFromEuler(angle));
      s.bone.updateWorldMatrix(false,true);
    }
    this.measurePenetration();
    // Limits must hold after the complete hierarchy changes, including during
    // gesture transitions. Reduce this display correction instead of relaxing
    // the existing proxy acceptance threshold.
    if(this.maxEdgePenetration<=edgeLimit&&this.maxPenetration<=pointLimit&&this.maxLinePenetration<=lineLimit)break;
    }
  }

  private tick(advance = true): void {
    // The animated baseline must not accumulate the previous solve.
    for (const s of this.segments) s.bone.quaternion.copy(s.pose);
    this.segments[0].bone.updateWorldMatrix(true, true);
    for (const s of this.segments) {
      s.bone.updateWorldMatrix(true, false);
      if (!advance) s.child.getWorldPosition(s.tip);
      const anchor = s.bone.getWorldPosition(new THREE.Vector3());
      const world = s.bone.getWorldQuaternion(new THREE.Quaternion());
      const restDirection = s.axis.clone().applyQuaternion(world);
      const target = anchor.clone().addScaledVector(restDirection, s.length);
      const p = s.setting;
      let pendulum = 0;
      if (p.dynamicType === 1 && p.pendulum > 1e-5 && p.pendulumRange > 1e-5) {
        pendulum = (1-Math.min(target.distanceTo(s.tip)*10,p.pendulumRange)/p.pendulumRange)*p.pendulum;
      } else if (p.pendulum > 1e-5 && p.pendulumRange > 1e-5) {
        const denominator = s.tip.length() * target.length();
        const cosine = denominator > 1e-9 ? Math.abs(s.tip.dot(target)) / denominator : 0;
        pendulum = Math.max(0, cosine - (1 - p.pendulumRange)) / p.pendulumRange * p.pendulum;
      }
      const force = (p.dynamicType===1 ? target.clone().sub(s.tip) : restDirection.clone()).multiplyScalar(p.stiffness - pendulum)
        .addScaledVector(target.clone().sub(s.tip), (1 - p.damping) ** 2)
        .addScaledVector(s.speed, p.spring);
      force.y -= p.mass * 0.01;
      if (p.dynamicType===1) {
        force.applyQuaternion(world.clone().invert());
        force.y += (p.axisAddXToY ?? 0)*Math.sign(force.y)*Math.abs(force.x);
        force.z += (p.axisAddXToZ ?? 0)*Math.sign(force.z)*Math.abs(force.x);
        force.applyQuaternion(world);
      }
      if (advance) s.speed.copy(force).multiplyScalar(STEP * 40);
      const direction = s.tip.clone().add(s.speed).sub(anchor);
      if (direction.lengthSq() < 1e-12) direction.copy(restDirection);
      for (let iteration = 0; iteration < (this.collision ? 5 : 1); iteration++) {
        this.solveDirection(s, world, restDirection, direction);
        if (!this.collision || !p.collision || ![0,2].includes(p.collision.type) || iteration === 4) break;
        if(p.collision.type===2){
          const tip=s.tip.clone(),c=p.collision,scale=s.bone.getWorldScale(new THREE.Vector3()).length()/Math.sqrt(3);
          const hits=this.collision.projectSegment(tip,anchor,c.float_A*scale,(c.float_B!==undefined&&c.float_B>=0?c.float_B:c.float_A)*scale,c.collisionMask,c.vector3_A.x*scale,c.vector3_A.y*scale);
          this.contactCount+=hits;if(!hits)break;direction.copy(tip).sub(anchor);continue;
        }
        const currentWorld = s.bone.getWorldQuaternion(new THREE.Quaternion());
        const offset = new THREE.Vector3(-p.collision.vector3_A.x, p.collision.vector3_A.y, p.collision.vector3_A.z).applyQuaternion(currentWorld);
        const center = s.tip.clone().add(offset);
        const hits = this.collision.project(center, p.collision.float_A, p.collision.collisionMask, restDirection);
        this.contactCount += hits;
        if (!hits) break;
        direction.copy(center).sub(offset).sub(anchor);
        if (direction.lengthSq() < 1e-12) direction.copy(restDirection);
      }
    }
    this.solveChains();
  }

  private solveChains(): void {
    if (!this.collision) return;
    for (const {nodes,setting} of this.chains) {
      const links=setting.around?nodes.length:nodes.length-1;
      for(let i=0;i<links;i++) {
        const a=nodes[i],b=nodes[(i+1)%nodes.length],mask=(a.setting.collision?.collisionMask??0)&(b.setting.collision?.collisionMask??0);
        const pa=a.child.getWorldPosition(new THREE.Vector3()),pb=b.child.getWorldPosition(new THREE.Vector3());
        if(!this.collision.projectEdge(pa,pb,setting.radius,mask))continue;
        for(const [s,target] of [[a,pa],[b,pb]] as const) {
          const anchor=s.bone.getWorldPosition(new THREE.Vector3());
          const parent=s.bone.parent?.getWorldQuaternion(new THREE.Quaternion())??new THREE.Quaternion();
          const world=parent.multiply(s.pose),rest=s.axis.clone().applyQuaternion(world);
          const direction=target.clone().sub(anchor);
          if(direction.lengthSq()>1e-12)this.solveDirection(s,world,rest,direction);
        }
      }
    }
  }

  private measurePenetration(): void {
    this.maxPenetration = 0;
    this.maxEdgePenetration = 0;
    this.maxLinePenetration = 0;
    // Measure the final hierarchy: later descendants or angular constraints can
    // leave contacts unresolved. Never label a projected candidate collision-free.
    if (this.collision) for (const s of this.segments) {
      const c = s.setting.collision;
      if (!c || ![0,2].includes(c.type)) continue;
      if(c.type===2){const scale=s.bone.getWorldScale(new THREE.Vector3()).length()/Math.sqrt(3);this.maxLinePenetration=Math.max(this.maxLinePenetration,this.collision.segmentPenetration(s.child.getWorldPosition(new THREE.Vector3()),s.bone.getWorldPosition(new THREE.Vector3()),c.float_A*scale,(c.float_B!==undefined&&c.float_B>=0?c.float_B:c.float_A)*scale,c.collisionMask,c.vector3_A.x*scale,c.vector3_A.y*scale));continue}
      const world = s.bone.getWorldQuaternion(new THREE.Quaternion());
      const center = s.child.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(-c.vector3_A.x,c.vector3_A.y,c.vector3_A.z).applyQuaternion(world));
      this.maxPenetration = Math.max(this.maxPenetration,this.collision.penetration(center,c.float_A,c.collisionMask));
    }
    if(this.collision)for(const {nodes,setting} of this.chains)for(let i=0;i<(setting.around?nodes.length:nodes.length-1);i++) {
      const a=nodes[i],b=nodes[(i+1)%nodes.length],mask=(a.setting.collision?.collisionMask??0)&(b.setting.collision?.collisionMask??0);
      this.maxEdgePenetration=Math.max(this.maxEdgePenetration,this.collision.edgePenetration(a.child.getWorldPosition(new THREE.Vector3()),b.child.getWorldPosition(new THREE.Vector3()),setting.radius,mask));
    }
  }

  private solveDirection(s: Segment, world: THREE.Quaternion, restDirection: THREE.Vector3, direction: THREE.Vector3): void {
      const solved = new THREE.Quaternion().setFromUnitVectors(restDirection.clone().normalize(), direction.clone().normalize()).multiply(world);
      const parent = s.bone.parent?.getWorldQuaternion(new THREE.Quaternion()) ?? new THREE.Quaternion();
      const local = parent.clone().invert().multiply(solved);
      if (s.limit.useLimit) {
        // Limit the deviation from the animated joint, not its bind orientation.
        const delta = s.pose.clone().invert().multiply(local);
        const e = new THREE.Euler().setFromQuaternion(delta, "YXZ");
        const l = s.limit;
        e.x = THREE.MathUtils.clamp(e.x, l.axisX.x * RAD, l.axisX.y * RAD);
        // Unity -> Three mirrors X: Y/Z angles and their interval endpoints flip.
        e.y = THREE.MathUtils.clamp(e.y, -l.axisY.y * RAD, -l.axisY.x * RAD);
        e.z = THREE.MathUtils.clamp(e.z, -l.axisZ.y * RAD, -l.axisZ.x * RAD);
        local.copy(s.pose).multiply(new THREE.Quaternion().setFromEuler(e));
      }
      s.solved.copy(local);
      s.bone.quaternion.copy(local);
      s.bone.updateWorldMatrix(false, true);
      s.child.getWorldPosition(s.tip);
  }
}

function depth(bone: THREE.Object3D): number {
  let result = 0;
  for (let parent = bone.parent; parent; parent = parent.parent) result++;
  return result;
}
