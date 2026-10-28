export type BlinkTiming = {
  minInterval: number; maxInterval: number;
  close: number; hold: number; open: number; seed: number;
};
const smooth = (t: number) => { const x=Math.max(0,Math.min(1,t));return x*x*(3-2*x); };

// Independent runtime layer, calibrated from a native screen sample. These are
// production timing choices, not recovered AutoEyeBlinkMixerPlayable constants.
export class Stand3DBlink {
  private time=0;
  private next=Infinity;
  private started:number|null=null;
  private seed:number;
  private authored=false;
  private reduced=false;
  constructor(private timing:BlinkTiming|null) {
    this.seed=(timing?.seed??1)>>>0||1;
    if(timing)this.next=this.interval();
  }
  private interval():number {
    if(!this.timing)return Infinity;
    let x=this.seed;x^=x<<13;x^=x>>>17;x^=x<<5;this.seed=x>>>0;
    return this.timing.minInterval+(this.timing.maxInterval-this.timing.minInterval)*(this.seed/4294967296);
  }
  step(dt:number,authoredBlink:number,reducedMotion:boolean):number {
    const p=this.timing;if(!p)return 0;
    if(reducedMotion){
      if(!this.reduced){this.started=null;this.next=this.time+this.interval()}
      this.reduced=true;return 0;
    }
    this.reduced=false;this.time+=Math.max(0,Math.min(.1,Number.isFinite(dt)?dt:0));
    const authored=authoredBlink>.02;
    if(authored){
      if(!this.authored){this.started=null;this.next=this.time+this.interval()}
      this.authored=true;return 0;
    }
    this.authored=false;
    if(this.started===null&&this.time>=this.next){this.started=this.next;this.next=this.started+this.interval()}
    if(this.started===null)return 0;
    const elapsed=this.time-this.started;
    if(elapsed<p.close)return smooth(elapsed/p.close);
    if(elapsed<p.close+p.hold)return 1;
    if(elapsed<p.close+p.hold+p.open)return 1-smooth((elapsed-p.close-p.hold)/p.open);
    this.started=null;return 0;
  }
}
