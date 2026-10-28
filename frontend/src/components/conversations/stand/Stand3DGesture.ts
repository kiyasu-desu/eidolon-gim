type Clip = { duration: number; sourceLoop: boolean };
const SPEECH_GAP_SECONDS = 0.6;
const TIME_EPSILON = 1e-9;

// Rotate approved original entrance gestures on speech starts, with a cooldown for short
// sentence/audio events. An optional, separately authored hold loop can follow
// the non-looping entrance. Without one, retain the original endpoint behavior.
// Brief audio gaps retain the body gesture; the mouth follows actual speech.
// Selection and delayed release are production rules. Idle time continues.
export class Stand3DGesture<T extends Clip> {
  private clock = 0;
  private nextAllowed = 0;
  private speaking = false;
  private quiet = 0;
  private elapsed: number | null = null;
  private readonly talks:T[];
  private active:T|null=null;
  private cursor=0;
  private readonly holds:ReadonlyMap<T,T>;
  constructor(talk:T|null, alternatives:readonly T[]=[], holds:ReadonlyMap<T,T>=new Map()){
    this.talks=[talk,...alternatives].filter((c):c is T=>c!==null&&Number.isFinite(c.duration)&&c.duration>0&&!c.sourceLoop);
    this.holds=new Map([...holds].filter(([source,hold])=>this.talks.includes(source)&&hold.sourceLoop&&Number.isFinite(hold.duration)&&hold.duration>0));
  }
  get count():number{return this.talks.length;}
  get holdCount():number{return this.holds.size;}

  step(idle: T | null, idleTime: number, speaking: boolean, dt: number, reducedMotion: boolean): { clip: T | null; time: number } {
    const delta=Math.max(0,dt);
    this.clock += delta;
    const start = speaking && !this.speaking;
    this.speaking = speaking;
    if(reducedMotion){this.elapsed=null;this.active=null;this.quiet=0;}
    else {
      if(speaking)this.quiet=0;
      else if(this.active){
        this.quiet+=delta;
        if(this.quiet+TIME_EPSILON>=SPEECH_GAP_SECONDS){this.elapsed=null;this.active=null;this.quiet=0;}
      }
      if(speaking&&start&&!this.active&&this.clock+TIME_EPSILON>=this.nextAllowed&&this.talks.length){
        this.active=this.talks[this.cursor%this.talks.length];
        this.cursor++;
        this.elapsed=0;
        this.nextAllowed=this.clock+8;
      }else if(this.elapsed!==null){
        this.elapsed+=delta;
        if(!this.active||!this.holds.has(this.active))this.elapsed=Math.min(this.active?.duration??0,this.elapsed);
      }
    }
    if (this.elapsed !== null && this.active) {
      const hold=this.holds.get(this.active);
      if(hold&&this.elapsed>=this.active.duration)return {clip:hold,time:(this.elapsed-this.active.duration)%hold.duration};
      return { clip: this.active, time: this.elapsed };
    }
    return { clip: idle, time: idleTime };
  }
}
