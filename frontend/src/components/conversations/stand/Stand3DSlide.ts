import * as THREE from "three";
import type { SwingSetting } from "./Stand3DSwing";

// Force/coupling adapted from Open Swing Dynamics, MIT, revision
// 4d1fa5492961eb09d8f7c5620d9a060f6074caca. See Stand3DSwing.LICENSE.

// Some native Slide chains have coincident joints and cannot define a swing
// direction. This bounded positional approximation drives only skinned nodes;
// it never invents a nonzero bone length or moves the Humanoid limb joints.
export class Stand3DSlide {
  private nodes: Array<{ bone:THREE.Bone; setting:SwingSetting; point:THREE.Vector3; target:THREE.Vector3; velocity:THREE.Vector3 }>;
  private initialized=false;
  private accumulator=0;
  maxOffset=0;
  constructor(settings:SwingSetting[],bones:Readonly<Record<string,THREE.Bone>>,weighted:ReadonlySet<string>) {
    this.nodes=settings.flatMap(setting=>setting.dynamicType===1&&weighted.has(setting.bone)&&bones[setting.bone]?[{bone:bones[setting.bone],setting,point:new THREE.Vector3(),target:new THREE.Vector3(),velocity:new THREE.Vector3()}]:[]);
  }
  get count():number{return this.nodes.length}
  reset():void{this.initialized=false;this.accumulator=0;this.maxOffset=0}
  update(dt:number,enabled:boolean):void {
    if(!enabled){this.reset();return}
    this.maxOffset=0;
    for(const n of this.nodes){n.bone.updateWorldMatrix(true,false);n.bone.getWorldPosition(n.target)}
    if(!this.initialized||dt>.25||this.nodes.some(n=>n.target.distanceToSquared(n.point)>.25)) {
      for(const n of this.nodes){n.point.copy(n.target);n.velocity.set(0,0,0)}
      this.initialized=true;this.accumulator=0;
    }
    const step=1/60;this.accumulator+=THREE.MathUtils.clamp(dt,0,.1);
    let ticks=Math.min(6,Math.floor((this.accumulator+1e-9)/step));this.accumulator-=ticks*step;
    while(ticks-->0)for(const n of this.nodes){
      const p=n.setting,delta=n.target.clone().sub(n.point);
      const pendulum=p.pendulumRange>1e-5?(1-Math.min(delta.length()*10,p.pendulumRange)/p.pendulumRange)*p.pendulum:0;
      const force=delta.multiplyScalar(p.stiffness-pendulum+(1-p.damping)**2).addScaledVector(n.velocity,p.spring);
      force.y-=p.mass*.01;
      const q=n.bone.getWorldQuaternion(new THREE.Quaternion());force.applyQuaternion(q.clone().invert());
      force.y+=(p.axisAddXToY??0)*Math.sign(force.y)*Math.abs(force.x);
      force.z+=(p.axisAddXToZ??0)*Math.sign(force.z)*Math.abs(force.x);force.applyQuaternion(q);
      n.velocity.copy(force).multiplyScalar(step*40);n.point.add(n.velocity);
      const offset=n.point.clone().sub(n.target),length=offset.length();
      // Application bound in metres; not a recovered native limit.
      if(length>.012){offset.multiplyScalar(.012/length);n.point.copy(n.target).add(offset);n.velocity.multiplyScalar(.5)}
    }
    for(const n of this.nodes){
      this.maxOffset=Math.max(this.maxOffset,n.point.distanceTo(n.target));
      const local=n.point.clone();if(n.bone.parent)n.bone.parent.worldToLocal(local);
      n.bone.position.copy(local);n.bone.updateWorldMatrix(false,true);
    }
  }
}
