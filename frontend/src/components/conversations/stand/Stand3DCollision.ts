import * as THREE from "three";

type Vec3 = { x: number; y: number; z: number };
export type StaticColliderSetting = { bone: string; source: string; type: number; collisionMask: number; vector3_A: Vec3; vector3_B: Vec3; float_A: number; float_B: number };
export type DynamicColliderSetting = { type: number; collisionMask: number; vector3_A: Vec3; float_A: number; float_B?: number };
type WorldCollider = { a: THREE.Vector3; b: THREE.Vector3; radiusA: number; radiusB: number; mask: number };

// Capsule and inset-line conversion/projection follows Open Swing Dynamics (MIT),
// revision 4d1fa5492961eb09d8f7c5620d9a060f6074caca. See Stand3DSwing.LICENSE.
// Finite-radius point contacts; this is not triangle-mesh cloth collision.
export class Stand3DCollision {
  private colliders: Array<{ setting: StaticColliderSetting; bone: THREE.Bone; world: WorldCollider }>;
  private offset = new THREE.Vector3();
  private scale = new THREE.Vector3();
  private nearest = new THREE.Vector3();
  private ab = new THREE.Vector3();
  private delta = new THREE.Vector3();
  constructor(settings: StaticColliderSetting[], bones: Readonly<Record<string, THREE.Bone>>) {
    this.colliders = settings.flatMap(setting => {
      const bone = bones[setting.bone];
      if (!bone || ![0, 1, 2].includes(setting.type)) return [];
      return [{ setting, bone, world: { a: new THREE.Vector3(), b: new THREE.Vector3(), radiusA: 0, radiusB: 0, mask: setting.collisionMask } }];
    });
  }
  get count(): number { return this.colliders.length; }
  capture(): void {
    for (const { setting: s, bone, world: w } of this.colliders) {
      bone.updateWorldMatrix(true, false);
      const scale = bone.getWorldScale(this.scale).length() / Math.sqrt(3);
      w.radiusA = Math.max(0, s.float_A * scale); w.radiusB = Math.max(0, s.float_B * scale);
      w.a.set(-s.vector3_A.x, s.vector3_A.y, s.vector3_A.z); w.b.copy(w.a);
      if (s.type === 1) {
        this.offset.set(0, 0, 0);
        const axis = Math.trunc(s.vector3_B.x);
        if (axis < 0 || axis > 2) continue;
        this.offset.setComponent(axis, (s.vector3_B.y / 2 - s.float_A) * (axis === 0 ? -1 : 1));
        w.a.sub(this.offset); w.b.add(this.offset);
        w.a.applyMatrix4(bone.matrixWorld); w.b.applyMatrix4(bone.matrixWorld);
      } else if (s.type === 2) {
        bone.getWorldPosition(w.a);
        if (bone.parent) bone.parent.getWorldPosition(w.b); else w.b.copy(w.a);
        this.ab.copy(w.b).sub(w.a); const length = this.ab.length();
        if (length > .01) {
          let a = Math.max(0, s.vector3_A.x) * scale, b = Math.max(0, s.vector3_A.y) * scale;
          const fit = Math.min(1, length / Math.max(1e-12, a + b)); a *= fit; b *= fit;
          this.ab.divideScalar(length); w.a.addScaledVector(this.ab, a); w.b.addScaledVector(this.ab, -b);
        }
      } else { w.a.applyMatrix4(bone.matrixWorld); w.b.copy(w.a); }
    }
  }
  // Visits sequential contacts. The caller alternates these with bone-length and
  // angle constraints, and reports residuals after the final constrained pose.
  project(center: THREE.Vector3, radius: number, mask: number, fallback: THREE.Vector3): number {
    let hits = 0;
    for (const { world: w } of this.colliders) {
      if (!(mask & w.mask)) continue;
      const depth = this.contact(center, radius, w);
      if (depth <= 0) continue;
      if (this.delta.lengthSq() < 1e-12) this.delta.copy(fallback);
      if (this.delta.lengthSq() < 1e-12) this.delta.set(0,0,1);
      center.addScaledVector(this.delta.normalize(), depth); hits++;
    }
    return hits;
  }
  penetration(center: THREE.Vector3, radius: number, mask: number): number {
    let depth = 0;
    for (const { world: w } of this.colliders) if (mask & w.mask) depth = Math.max(depth, this.contact(center, radius, w));
    return depth;
  }
  projectEdge(a: THREE.Vector3,b: THREE.Vector3,radius: number,mask: number): number {
    const contacts=this.colliders.filter(c=>mask&c.world.mask).map(c=>({world:c.world,hit:this.edgeContact(a,b,radius,c.world)}));
    const deepest=contacts.reduce<typeof contacts[number]|null>((best,c)=>!best||c.hit.depth>best.hit.depth?c:best,null);
    if(!deepest||deepest.hit.depth<=0)return 0;
    if(contacts.some(c=>c.hit.normal.lengthSq()>.1&&c.hit.normal.dot(deepest.hit.normal)<-.5)){
      // Opposed proxies can undo each other's sequential projection. Select a
      // bounded translation that reduces their worst residual together. This
      // leaves an honest compromise when no local collision-free move is found.
      const axis=b.clone().sub(a).normalize(),push=deepest.hit.normal.clone().multiplyScalar(deepest.hit.depth);
      push.addScaledVector(axis,-push.dot(axis));let best=deepest.hit.depth,fraction=0;
      for(const f of [1,.75,.5,.25,.125]){const pa=a.clone().addScaledVector(push,f),pb=b.clone().addScaledVector(push,f);let depth=0;for(const c of contacts)depth=Math.max(depth,this.edgeContact(pa,pb,radius,c.world).depth);if(depth<best-1e-9){best=depth;fraction=f}}
      if(fraction===0)return 0;
      a.addScaledVector(push,fraction);b.addScaledVector(push,fraction);return 1;
    }
    let hits=0;
    for(const c of contacts) {
      const hit=hits?this.edgeContact(a,b,radius,c.world):c.hit;
      if(hit.depth<=0)continue;
      const axis=b.clone().sub(a).normalize();
      const push=hit.normal.multiplyScalar(hit.depth);
      push.addScaledVector(axis,-push.dot(axis));
      if(push.lengthSq()<1e-14)continue;
      a.add(push);b.add(push);hits++;
    }
    return hits;
  }
  edgePenetration(a: THREE.Vector3,b: THREE.Vector3,radius: number,mask: number): number {
    let depth=0;
    for(const {world:w} of this.colliders)if(mask&w.mask)depth=Math.max(depth,this.edgeContact(a,b,radius,w).depth);
    return depth;
  }
  // The dynamic Line is anchored at its parent. Move only its tip; compensate
  // for the contact's position along the segment, then let the swing solver
  // enforce authored lengths and limits. Near-anchor contacts may stay residual.
  projectSegment(tip:THREE.Vector3,anchor:THREE.Vector3,radius:number,endRadius:number,mask:number,insetTip=0,insetAnchor=0):number {
    let hits=0;
    for(const {world:w}of this.colliders){
      if(!(mask&w.mask))continue;
      const shape=this.dynamicSegment(tip,anchor,insetTip,insetAnchor),hit=this.segmentContacts(shape.a,shape.b,radius,endRadius,w).sort((a,b)=>b.depth-a.depth).find(h=>h.depth>0&&1-(shape.start+(shape.end-shape.start)*h.fraction)>=1e-3);
      if(!hit)continue;
      const influence=1-(shape.start+(shape.end-shape.start)*hit.fraction);
      if(influence<1e-3)continue;
      tip.addScaledVector(hit.normal,Math.min(hit.depth/influence,tip.distanceTo(anchor)*.5));hits++;
    }
    return hits;
  }
  segmentPenetration(tip:THREE.Vector3,anchor:THREE.Vector3,radius:number,endRadius:number,mask:number,insetTip=0,insetAnchor=0):number {
    const shape=this.dynamicSegment(tip,anchor,insetTip,insetAnchor);let depth=0;
    for(const {world:w}of this.colliders)if(mask&w.mask)for(const contact of this.segmentContacts(shape.a,shape.b,radius,endRadius,w))depth=Math.max(depth,contact.depth);
    return depth;
  }
  private dynamicSegment(tip:THREE.Vector3,anchor:THREE.Vector3,insetTip:number,insetAnchor:number){
    const length=tip.distanceTo(anchor),sum=Math.max(0,insetTip)+Math.max(0,insetAnchor),fit=sum>length?length/Math.max(sum,1e-12):1;
    const start=length>1e-12?Math.max(0,insetTip)*fit/length:0,end=length>1e-12?1-Math.max(0,insetAnchor)*fit/length:1;
    return {a:tip.clone().lerp(anchor,start),b:tip.clone().lerp(anchor,end),start,end};
  }
  private segmentContacts(a:THREE.Vector3,b:THREE.Vector3,radius:number,endRadius:number,w:WorldCollider){
    // A varying-radius end cap can overlap even when the nearest axis pair is
    // clear. Keep both caps in the query and in residual reporting.
    const contacts=[this.edgeContact(a,b,radius,w,endRadius)];
    for(const [point,r,fraction]of [[a,radius,0],[b,endRadius,1]] as const){const depth=this.contact(point,r,w),normal=this.delta.clone();if(normal.lengthSq()>1e-12)normal.normalize();else normal.set(0,0,1);contacts.push({depth,normal,fraction})}
    return contacts;
  }
  private edgeContact(p:THREE.Vector3,q:THREE.Vector3,radius:number,w:WorldCollider,endRadius=radius): {depth:number;normal:THREE.Vector3;fraction:number} {
    const padding=Math.max(radius,endRadius)+Math.max(w.radiusA,w.radiusB);
    for(const axis of ["x","y","z"] as const)if(Math.max(p[axis],q[axis])+padding<Math.min(w.a[axis],w.b[axis])||Math.min(p[axis],q[axis])-padding>Math.max(w.a[axis],w.b[axis]))return {depth:0,normal:new THREE.Vector3(),fraction:0};
    // Closest points of two finite segments, including point/parallel cases.
    const u=q.clone().sub(p),v=w.b.clone().sub(w.a),r=p.clone().sub(w.a);
    const aa=u.lengthSq(),ee=v.lengthSq(),ff=v.dot(r);let s=0,t=0;
    if(aa<1e-12)t=ee<1e-12?0:THREE.MathUtils.clamp(ff/ee,0,1);
    else {
      const cc=u.dot(r);
      if(ee<1e-12)s=THREE.MathUtils.clamp(-cc/aa,0,1);
      else {
        const bb=u.dot(v),denominator=aa*ee-bb*bb;
        s=denominator>1e-12?THREE.MathUtils.clamp((bb*ff-cc*ee)/denominator,0,1):0;
        t=(bb*s+ff)/ee;
        if(t<0){t=0;s=THREE.MathUtils.clamp(-cc/aa,0,1)}
        else if(t>1){t=1;s=THREE.MathUtils.clamp((bb-cc)/aa,0,1)}
      }
    }
    const normal=p.clone().addScaledVector(u,s).sub(w.a).addScaledVector(v,-t),length=normal.length();
    if(length>1e-9)normal.divideScalar(length);
    else {normal.crossVectors(u,new THREE.Vector3(0,1,0));if(normal.lengthSq()<1e-10)normal.set(0,0,1);normal.normalize()}
    return {depth:Math.max(0,(aa<1e-12?Math.max(radius,endRadius):THREE.MathUtils.lerp(radius,endRadius,s))+THREE.MathUtils.lerp(w.radiusA,w.radiusB,t)-length),normal,fraction:s};
  }
  private contact(center: THREE.Vector3, radius: number, w: WorldCollider): number {
    this.ab.copy(w.b).sub(w.a); this.delta.copy(center).sub(w.a);
    const t = this.ab.lengthSq() > 1e-12 ? THREE.MathUtils.clamp(this.delta.dot(this.ab) / this.ab.lengthSq(), 0, 1) : 0;
    this.nearest.copy(w.a).addScaledVector(this.ab, t); this.delta.copy(center).sub(this.nearest);
    return Math.max(0, radius + THREE.MathUtils.lerp(w.radiusA, w.radiusB, t) - this.delta.length());
  }
}
