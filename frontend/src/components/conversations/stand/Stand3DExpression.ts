import type { Emotion } from "@/lib/standAnimations";

export type FacePresets = { version: number; presets: Partial<Record<Emotion, Record<string, number>>> };
const BLINK="b_eye.eye_001";
const clamp=(value:number)=>Math.max(0,Math.min(1,Number.isFinite(value)?value:0));

// Original common facial snapshots. Mood associations and the 0.3s settling
// envelope are production choices, not recovered game emotion classification.
export class Stand3DExpression {
  readonly enabled:boolean;
  private presets:FacePresets['presets'];
  private keys:string[];
  private weights:Record<string,number>={};
  private strength=0;
  constructor(source:FacePresets|undefined){
    this.presets=source?.version===1?source.presets:{};
    this.keys=[...new Set(Object.values(this.presets).flatMap(p=>Object.keys(p??{})))].filter(k=>k!==BLINK);
    this.enabled=this.keys.length>0;
  }
  get count():number{return Object.keys(this.presets).length}
  apply(native:Record<string,number>,mood:Emotion,dt:number,reducedMotion:boolean):Record<string,number>{
    if(!this.enabled)return native;
    const target=mood==='calm'?undefined:this.presets[mood],alpha=reducedMotion?1:1-Math.exp(-Math.max(0,Math.min(.1,dt))*10);
    if(target){
      if(this.strength===0)this.weights={...target};
      for(const name of this.keys)this.weights[name]=(this.weights[name]??0)+alpha*(clamp(target[name]??0)-(this.weights[name]??0));
    }
    this.strength+=alpha*((target?1:0)-this.strength);
    if(this.strength<1e-5&&!target){this.strength=0;return native}
    const result={...native},blink=clamp(native[BLINK]??0);
    for(const name of this.keys){
      const value=(native[name]??0)*(1-this.strength)+(this.weights[name]??0)*this.strength;
      result[name]=clamp(value)*(name.startsWith('b_eye.')?1-blink:1);
    }
    result[BLINK]=blink;
    return result;
  }
}
