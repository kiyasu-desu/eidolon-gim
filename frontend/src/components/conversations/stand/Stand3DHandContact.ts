import * as THREE from "three";

type Vec3 = { x: number; y: number; z: number };
export type HandContactSettings = {
  goals: Array<{ bone: string; goal: number; radius: number; offset: Vec3 }>;
  colliders: Array<{ bone: string; type: number; weight: number; radius: number; radiusSub: number; length: number; dampArea: number; offset: Vec3; rotation: Vec3 }>;
};

// Reconstructed contact pass using original serialized radii/weight. The local-Y
// tapered capsule convention and smooth damping are explicit approximations;
// this does not implement the unknown native IKCorrection routine.
export class Stand3DHandContact {
  private goals: Array<{ setting: HandContactSettings["goals"][number]; hand: THREE.Bone; forearm: THREE.Bone; arm: THREE.Bone }>;
  private colliders: Array<{ setting: HandContactSettings["colliders"][number]; bone: THREE.Bone }>;
  maxBefore = 0;
  maxAfter = 0;
  maxCorrection = 0;
  constructor(settings: HandContactSettings | undefined, bones: Readonly<Record<string, THREE.Bone>>) {
    this.goals = (settings?.goals ?? []).flatMap(setting => {
      const hand = bones[setting.bone], forearm = hand?.parent, arm = forearm?.parent;
      if (!(hand instanceof THREE.Bone) || !(forearm instanceof THREE.Bone) || !(arm instanceof THREE.Bone)) return [];
      return [{ setting, hand, forearm, arm }];
    });
    this.colliders = (settings?.colliders ?? []).flatMap(setting => bones[setting.bone] && setting.type === 1 ? [{ setting, bone: bones[setting.bone] }] : []);
  }
  get count(): number { return this.goals.length; }
  measure():void {
    this.maxAfter=0;
    for(const g of this.goals){g.hand.updateWorldMatrix(true,false);const q=g.hand.getWorldQuaternion(new THREE.Quaternion()),center=g.hand.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(-g.setting.offset.x,g.setting.offset.y,g.setting.offset.z).applyQuaternion(q));for(const c of this.colliders)this.maxAfter=Math.max(this.maxAfter,this.contact(center,g.setting.radius,c).depth)}
  }
  apply(): void {
    this.maxBefore = 0; this.maxAfter = 0; this.maxCorrection = 0;
    for (const g of this.goals) {
      g.arm.updateWorldMatrix(true, true);
      const origin = g.hand.getWorldPosition(new THREE.Vector3());
      const handQ = g.hand.getWorldQuaternion(new THREE.Quaternion());
      const offset = new THREE.Vector3(-g.setting.offset.x,g.setting.offset.y,g.setting.offset.z).applyQuaternion(handQ);
      const center = origin.clone().add(offset), target = center.clone();
      for (const c of this.colliders) {
        const contact = this.contact(target,g.setting.radius,c);
        this.maxBefore = Math.max(this.maxBefore,contact.depth);
        const damp = c.setting.dampArea > 0 ? THREE.MathUtils.smoothstep(contact.depth,0,c.setting.dampArea) : 1;
        target.addScaledVector(contact.normal,Math.min(.05,contact.depth * THREE.MathUtils.clamp(c.setting.weight,0,1) * damp));
      }
      const correction = target.distanceTo(center);
      if (correction > 1e-8) {
        solveArmContact(g.arm,g.forearm,g.hand,target.sub(offset));
        this.maxCorrection = Math.max(this.maxCorrection,g.hand.getWorldPosition(new THREE.Vector3()).distanceTo(origin));
      }
      const actual = g.hand.getWorldPosition(new THREE.Vector3()).add(offset);
      for (const c of this.colliders) this.maxAfter = Math.max(this.maxAfter,this.contact(actual,g.setting.radius,c).depth);
    }
  }
  private contact(center: THREE.Vector3, radius: number, c: typeof this.colliders[number]): { depth: number; normal: THREE.Vector3 } {
    c.bone.updateWorldMatrix(true,false);
    const s=c.setting, matrix=c.bone.matrixWorld;
    const rotation=new THREE.Quaternion().setFromEuler(new THREE.Euler(s.rotation.x*Math.PI/180,-s.rotation.y*Math.PI/180,-s.rotation.z*Math.PI/180,"YXZ"));
    const offset=new THREE.Vector3(-s.offset.x,s.offset.y,s.offset.z);
    const a=new THREE.Vector3(0,-s.length/2,0).applyQuaternion(rotation).add(offset).applyMatrix4(matrix);
    const b=new THREE.Vector3(0,s.length/2,0).applyQuaternion(rotation).add(offset).applyMatrix4(matrix);
    const ab=b.sub(a),delta=center.clone().sub(a);
    const t=ab.lengthSq()>1e-12?THREE.MathUtils.clamp(delta.dot(ab)/ab.lengthSq(),0,1):.5;
    const nearest=a.addScaledVector(ab,t),normal=center.clone().sub(nearest),distance=normal.length();
    const scale=c.bone.getWorldScale(new THREE.Vector3()).length()/Math.sqrt(3);
    if(distance<1e-8) normal.set(0,0,1).transformDirection(matrix); else normal.divideScalar(distance);
    return { depth:Math.max(0,radius+THREE.MathUtils.lerp(s.radius,s.radiusSub,t)*scale-distance), normal };
  }
}

// Analytic two-bone solve transports the authored elbow plane to the target.
// Bone translations are untouched and the hand's world orientation is retained.
export function solveArmContact(upper: THREE.Bone, lower: THREE.Bone, hand: THREE.Bone, target: THREE.Vector3): void {
  upper.updateWorldMatrix(true,true);
  const a=upper.getWorldPosition(new THREE.Vector3()),b=lower.getWorldPosition(new THREE.Vector3()),c=hand.getWorldPosition(new THREE.Vector3());
  const handQ=hand.getWorldQuaternion(new THREE.Quaternion()),l1=a.distanceTo(b),l2=b.distanceTo(c);
  if(l1<1e-6||l2<1e-6)return;
  const original=c.clone().sub(a).normalize(),direction=target.clone().sub(a);
  if(original.lengthSq()<1e-12)original.copy(b).sub(a).normalize();
  const distance=THREE.MathUtils.clamp(direction.length(),Math.abs(l1-l2)+1e-6,l1+l2-1e-6);direction.normalize();
  if(direction.lengthSq()<1e-12)return;
  const bend=b.clone().sub(a).addScaledVector(original,-b.clone().sub(a).dot(original));
  if(bend.lengthSq()<1e-10) {
    bend.set(0,0,1).applyQuaternion(upper.getWorldQuaternion(new THREE.Quaternion()));
    bend.addScaledVector(original,-bend.dot(original));
    if(bend.lengthSq()<1e-10)bend.set(0,1,0).applyQuaternion(upper.getWorldQuaternion(new THREE.Quaternion())).addScaledVector(original,-bend.dot(original));
  }
  bend.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(original,direction));
  bend.addScaledVector(direction,-bend.dot(direction)).normalize();
  const along=(l1*l1-l2*l2+distance*distance)/(2*distance),height=Math.sqrt(Math.max(0,l1*l1-along*along));
  const mid=a.clone().addScaledVector(direction,along).addScaledVector(bend,height);
  const reached=a.clone().addScaledVector(direction,distance);
  const aim=(bone:THREE.Bone,from:THREE.Vector3,to:THREE.Vector3)=>{
    const q=bone.getWorldQuaternion(new THREE.Quaternion()).premultiply(new THREE.Quaternion().setFromUnitVectors(from.normalize(),to.normalize()));
    const parent=bone.parent?.getWorldQuaternion(new THREE.Quaternion())??new THREE.Quaternion();
    bone.quaternion.copy(parent.invert().multiply(q));bone.updateWorldMatrix(false,true);
  };
  aim(upper,b.clone().sub(a),mid.clone().sub(a));
  const newB=lower.getWorldPosition(new THREE.Vector3()),newC=hand.getWorldPosition(new THREE.Vector3());
  aim(lower,newC.sub(newB),reached.sub(newB));
  const parentQ=hand.parent?.getWorldQuaternion(new THREE.Quaternion())??new THREE.Quaternion();
  hand.quaternion.copy(parentQ.invert().multiply(handQ));hand.updateWorldMatrix(false,true);
}
