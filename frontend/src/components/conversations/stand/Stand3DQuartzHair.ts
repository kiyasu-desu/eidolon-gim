import * as THREE from "three";

// Adapted from Open Swing Dynamics, Copyright (c) 2026 Arin3000, MIT.
// Fixed source 4d1fa5492961eb09d8f7c5620d9a060f6074caca; full license in
// Stand3DSwing.LICENSE. This reproduces that kernel, not the game's full player.
type V = {x:number;y:number;z:number};
export type QuartzHairSetting = {
  translateConnectionAxis:number;rotationOrder:number;rotateConnectionAxis:number;composeType:number;
  headTranslateCoefficient:V;headTranslateLimitMin:V;headTranslateLimitMax:V;
  headRotateCoefficient:V;headRotateLimitMin:V;headRotateLimitMax:V;
  neckRotateCoefficient:V;neckRotateLimitMin:V;neckRotateLimitMax:V;
};
export type QuartzHairDriver = {bone:string;setting:QuartzHairSetting};
const RAD=Math.PI/180,DEG=180/Math.PI;
const exchange=(v:THREE.Vector3,order:number)=>{
  const orders=[[0,1,2],[0,2,1],[1,0,2],[1,2,0],[2,0,1],[2,1,0]],o=orders[order]??orders[0];
  return new THREE.Vector3(v.getComponent(o[0]),v.getComponent(o[1]),v.getComponent(o[2]));
};
const wrap=(v:number)=>v>180?v-360:v < -180?v+360:v;

export function convertQuartzHair(raw:QuartzHairSetting):QuartzHairSetting {
  const s=structuredClone(raw);
  s.headTranslateCoefficient={x:raw.headTranslateCoefficient.x*.01,y:raw.headTranslateCoefficient.y*.01,z:-raw.headTranslateCoefficient.z*.01};
  for(const prefix of ['headTranslate','headRotate','neckRotate'] as const){
    const a=raw[`${prefix}LimitMin`],b=raw[`${prefix}LimitMax`];
    s[`${prefix}LimitMin`]={x:a.x,y:-b.y,z:-b.z};s[`${prefix}LimitMax`]={x:b.x,y:-a.y,z:-a.z};
  }
  for(const prefix of ['headRotate','neckRotate'] as const){const c=raw[`${prefix}Coefficient`];s[`${prefix}Coefficient`]={x:-c.x,y:-c.y,z:-c.z}}
  return s;
}

function toEuler(q:THREE.Quaternion,order:number):THREE.Vector3 {
  const x=q.x,y=q.y,z=q.z,w=-q.w;
  const axis=(a:number,b:number,c:number,d:number,e:number)=>new THREE.Vector3(-Math.atan2(d,e),-Math.asin(THREE.MathUtils.clamp(c,-1,1)),-Math.atan2(a,b));
  if(order===2){const t=axis(2*(w*y+z*x),w*w-x*x-y*y+z*z,2*(w*x-y*z),2*(w*z+x*y),w*w-x*x+y*y-z*z);return new THREE.Vector3(t.y,t.z,t.x)}
  const t=axis(2*(w*x-y*z),w*w-x*x-y*y+z*z,2*(w*y+x*z),2*(w*z-x*y),w*w+x*x-y*y-z*z);return new THREE.Vector3(t.z,t.y,t.x);
}
function bendRoll(e:THREE.Vector3):THREE.Vector3 {
  const h=e.clone().multiplyScalar(RAD*.5),sx=Math.sin(h.x),cx=Math.cos(h.x),sy=Math.sin(h.y),cy=Math.cos(h.y),sz=Math.sin(h.z),cz=Math.cos(h.z);
  const x=sx*cy*cz-sy*sz*cx,y=sy*cx*cz+sx*sz*cy,z=sz*cx*cy+sx*sy*cz,w=cx*cy*cz-sy*sz*sx;
  const denominator=2-2*z*z-2*x*x,bend=2*Math.atan2(2*z*y+2*x*w,denominator)*DEG,roll=-2*Math.atan2(2*x*y-2*z*w,denominator)*DEG;
  // The source swaps its (Y, bend, roll) result before applying coefficients.
  return new THREE.Vector3(bend,e.y,roll);
}
function coefficients(angles:THREE.Vector3,c:V,a:V,b:V):THREE.Vector3 {
  return new THREE.Vector3(THREE.MathUtils.clamp(wrap(angles.x),a.x,b.x)*c.x,THREE.MathUtils.clamp(wrap(angles.y),a.y,b.y)*c.y,THREE.MathUtils.clamp(wrap(angles.z),a.z,b.z)*c.z);
}

// Inputs and outputs are Unity LOCAL coordinates. The caller performs the one
// X-mirror at the Three boundary, after the original parameter conversion.
export function calculateUnityQuartz(head:THREE.Quaternion,neck:THREE.Quaternion,s:QuartzHairSetting):{position:THREE.Vector3;rotation:THREE.Quaternion} {
  const h=bendRoll(toEuler(head,2).multiplyScalar(DEG)),n=bendRoll(toEuler(neck,2).multiplyScalar(DEG));
  const position=exchange(coefficients(h,s.headTranslateCoefficient,s.headTranslateLimitMin,s.headTranslateLimitMax),s.translateConnectionAxis);
  const rotation=coefficients(h,s.headRotateCoefficient,s.headRotateLimitMin,s.headRotateLimitMax)
    .add(coefficients(n,s.neckRotateCoefficient,s.neckRotateLimitMin,s.neckRotateLimitMax)).multiplyScalar(RAD);
  const pitch=Math.tan(rotation.y*.5),yaw=Math.tan(-rotation.z*.5),scale=2/(pitch*pitch+yaw*yaw+1);
  const direction=new THREE.Vector3(scale-1,scale*yaw,scale*pitch).normalize();
  const composed=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),-rotation.x)
    .multiply(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(1,0,0),direction));
  const e=exchange(toEuler(composed,s.rotationOrder),s.rotateConnectionAxis);
  return {position,rotation:new THREE.Quaternion().setFromEuler(new THREE.Euler(e.x,e.y,e.z,'YXZ'))};
}

export class Stand3DQuartzHair {
  private drivers:Array<{bone:THREE.Bone;setting:QuartzHairSetting}>;
  constructor(settings:QuartzHairDriver[],bones:Readonly<Record<string,THREE.Bone>>,private head:THREE.Bone|undefined,private neck:THREE.Bone|undefined){
    this.drivers=settings.flatMap(d=>bones[d.bone]&&d.setting.rotationOrder===0&&d.setting.composeType===0?[{bone:bones[d.bone],setting:convertQuartzHair(d.setting)}]:[]);
  }
  get count():number{return this.head&&this.neck?this.drivers.length:0}
  apply():void {
    if(!this.head||!this.neck)return;
    const h=this.head.quaternion,n=this.neck.quaternion,head=new THREE.Quaternion(h.x,-h.y,-h.z,h.w),neck=new THREE.Quaternion(n.x,-n.y,-n.z,n.w);
    for(const d of this.drivers){const {position:p,rotation:q}=calculateUnityQuartz(head,neck,d.setting);d.bone.position.set(-p.x,p.y,p.z);d.bone.quaternion.set(q.x,-q.y,-q.z,q.w);d.bone.updateWorldMatrix(false,true)}
  }
}
