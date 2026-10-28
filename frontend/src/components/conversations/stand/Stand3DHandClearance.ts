import * as THREE from "three";
import {solveArmContact} from "./Stand3DHandContact";

type Offset={x:number;y:number;z:number};
export type HandClearanceSettings={version:number;hips:string;clips:string[];introClips?:Array<{name:string;holdUntil:number}>;transitionDuration?:number;transitionResponse?:number;hands:Array<{hand:string;upper:string;lower:string;offset:Offset;transitionOffset?:Offset}>};

// Mesh-calibrated portrait pose adjustment, separate from original IK settings.
// Static offsets use the web Hips frame and are capped at 40mm, short transition
// guards at 60mm (one source goal radius). This does not claim to
// reconstruct the game's native mesh collision solver or arbitrary self-contact.
export class Stand3DHandClearance {
  private hips:THREE.Bone|undefined;
  private clips:Set<string>;
  private hands:Array<{hand:THREE.Bone;upper:THREE.Bone;lower:THREE.Bone;offset:THREE.Vector3;transition:THREE.Vector3;current:THREE.Vector3}>;
  private introClips:Map<string,number>;
  private transitionDuration:number;
  private transitionResponse:number;
  private transitionRemaining=0;
  private lastClip:string|null=null;
  private guardedIntro:string|null=null;
  private initialized=false;
  maxCorrection=0;
  constructor(settings:HandClearanceSettings|undefined,bones:Readonly<Record<string,THREE.Bone>>){
    const valid=settings?.version===1?settings:undefined;this.hips=valid?bones[valid.hips]:undefined;this.clips=new Set(valid?.clips??[]);
    this.introClips=new Map((valid?.introClips??[]).filter(c=>Number.isFinite(c.holdUntil)&&c.holdUntil>=0&&c.holdUntil<=1).map(c=>[c.name,c.holdUntil]));
    this.transitionDuration=Number.isFinite(valid?.transitionDuration)?Math.max(0,Math.min(.5,valid?.transitionDuration??0)):0;
    this.transitionResponse=Number.isFinite(valid?.transitionResponse)?Math.max(10,Math.min(20,valid?.transitionResponse??10)):10;
    this.hands=(valid?.hands??[]).flatMap(s=>{const hand=bones[s.hand],upper=bones[s.upper],lower=bones[s.lower],offset=new THREE.Vector3(s.offset.x,s.offset.y,s.offset.z),peak=s.transitionOffset,transition=peak?new THREE.Vector3(peak.x,peak.y,peak.z):offset.clone();if(!transition.toArray().every(Number.isFinite)||transition.length()>.060001)transition.copy(offset);return hand&&upper&&lower&&offset.toArray().every(Number.isFinite)&&offset.length()<=.040001?[{hand,upper,lower,offset,transition,current:new THREE.Vector3()}]:[]});
  }
  get count():number{return this.hips?this.hands.length:0}
  reset():void{this.initialized=false;this.lastClip=null;this.guardedIntro=null;this.transitionRemaining=0;for(const hand of this.hands)hand.current.set(0,0,0)}
  apply(clip:{name:string}|null,dt:number,reducedMotion:boolean,clipTime=0):void{
    this.maxCorrection=0;if(!this.hips)return;
    const name=clip?.name??null,eligible=name!==null&&this.clips.has(name);
    if(name!==this.lastClip){
      this.guardedIntro=this.initialized&&this.lastClip!==null&&this.clips.has(this.lastClip)&&name!==null&&this.introClips.has(name)?name:null;
      this.transitionRemaining=this.initialized&&eligible&&this.lastClip!==null&&!this.clips.has(this.lastClip)?this.transitionDuration:0;
      this.lastClip=name;
    }
    if(reducedMotion)this.transitionRemaining=0;
    const active=eligible||(name!==null&&this.guardedIntro===name&&clipTime<(this.introClips.get(name)??0)),rate=this.transitionRemaining>0?this.transitionResponse:10,alpha=!this.initialized||reducedMotion?1:1-Math.exp(-Math.max(0,Math.min(.1,dt))*rate);
    this.hips.updateWorldMatrix(true,false);const origin=this.hips.getWorldPosition(new THREE.Vector3());
    for(const h of this.hands){
      h.current.lerp(active?(this.transitionRemaining>0?h.transition:h.offset):new THREE.Vector3(),alpha);
      if(h.current.lengthSq()<1e-12)continue;
      const delta=h.current.clone().applyMatrix4(this.hips.matrixWorld).sub(origin);h.hand.updateWorldMatrix(true,false);
      const before=h.hand.getWorldPosition(new THREE.Vector3());solveArmContact(h.upper,h.lower,h.hand,before.clone().add(delta));
      this.maxCorrection=Math.max(this.maxCorrection,h.hand.getWorldPosition(new THREE.Vector3()).distanceTo(before));
    }
    this.initialized=true;
    this.transitionRemaining=Math.max(0,this.transitionRemaining-Math.max(0,dt));
  }
}
