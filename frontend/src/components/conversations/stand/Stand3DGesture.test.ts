import { describe, expect, it } from "vitest";
import { Stand3DGesture } from "./Stand3DGesture";
const idle={name:"idle",duration:20,sourceLoop:true};
const talk={name:"talk",duration:1.8,sourceLoop:false};
describe("speech body gesture",()=>{
 it("accepts the next gesture at the nominal cooldown boundary across display rates",()=>{
  for(const fps of [30,60,120]){const next={...talk,name:'next'},g=new Stand3DGesture(talk,[next]);g.step(idle,0,true,0,false);for(let f=1;f<8*fps;f++)g.step(idle,f/fps,false,1/fps,false);expect(g.step(idle,8,true,1/fps,false).clip).toBe(next)}
 });
 it("bridges a half-second speech gap without releasing or consuming the next gesture",()=>{
  const next={name:'next',duration:1.2,sourceLoop:false},hold={name:'hold',duration:4,sourceLoop:true},g=new Stand3DGesture(talk,[next],new Map([[talk,hold]]));
  g.step(idle,0,true,0,false);g.step(idle,9,true,9,false);
  expect(g.step(idle,9.25,false,.25,false).clip).toBe(hold);
  expect(g.step(idle,9.5,true,.25,false).clip).toBe(hold);
  expect(g.step(idle,10.11,false,.61,false).clip).toBe(idle);
  expect(g.step(idle,10.12,true,.01,false).clip).toBe(next);
 });
 it("releases at the same silence boundary across display rates and cancels immediately for reduced motion",()=>{
  for(const fps of [30,60,120]){const g=new Stand3DGesture(talk);g.step(idle,0,true,0,false);for(let f=1;f<.6*fps;f++)expect(g.step(idle,f/fps,false,1/fps,false).clip).toBe(talk);expect(g.step(idle,.6,false,1/fps,false).clip).toBe(idle)}
  const g=new Stand3DGesture(talk);g.step(idle,0,true,0,false);expect(g.step(idle,.1,false,.1,true).clip).toBe(idle);
 });
 it("uses a separately authored hold loop without looping the original entrance",()=>{
  const hold={name:'authored-hold',duration:4,sourceLoop:true},g=new Stand3DGesture(talk,[],new Map([[talk,hold]]));
  expect(g.step(idle,0,true,0,false)).toEqual({clip:talk,time:0});
  const first=g.step(idle,2,true,2,false);expect(first.clip).toBe(hold);expect(first.time).toBeCloseTo(.2);
  const wrapped=g.step(idle,6,true,4,false);expect(wrapped.clip).toBe(hold);expect(wrapped.time).toBeCloseTo(.2);
  expect(g.step(idle,6,true,0,false).time).toBeCloseTo(.2);
  expect(g.step(idle,7,false,1,false)).toEqual({clip:idle,time:7});
 });
 it("retains endpoint fallback for an invalid hold and cancels valid holds for reduced motion",()=>{
  const invalid=new Stand3DGesture(talk,[],new Map([[talk,{...talk,name:'not-loop'}]]));invalid.step(idle,0,true,0,false);expect(invalid.step(idle,4,true,4,false)).toEqual({clip:talk,time:talk.duration});
  const hold={name:'hold',duration:4,sourceLoop:true},g=new Stand3DGesture(talk,[],new Map([[talk,hold]]));g.step(idle,0,true,0,false);g.step(idle,4,true,4,false);expect(g.step(idle,4,true,0,true).clip).toBe(idle);
 });
 it("rotates approved clips only when a new gesture actually starts",()=>{
  const second={name:'second',duration:1.2,sourceLoop:false},third={name:'third',duration:2,sourceLoop:false},g=new Stand3DGesture(talk,[second,third]);
  expect(g.step(idle,0,true,0,false).clip).toBe(talk);
  g.step(idle,1,false,1,false);expect(g.step(idle,1.1,true,.1,false).clip).toBe(idle);
  g.step(idle,9,false,8,false);expect(g.step(idle,9,true,0,false).clip).toBe(second);
  expect(g.step(idle,12,true,3,false)).toEqual({clip:second,time:second.duration});
  g.step(idle,18,false,6,false);expect(g.step(idle,18,true,0,false).clip).toBe(third);
  g.step(idle,27,false,9,false);expect(g.step(idle,27,true,0,false).clip).toBe(talk);
 });
 it("skips invalid candidates and keeps reduced-motion starts from consuming the pool",()=>{
  const second={name:'second',duration:1.2,sourceLoop:false},g=new Stand3DGesture(null,[idle,{...talk,duration:Infinity},{...talk,duration:0},talk,second]);
  expect(g.step(idle,0,true,0,true).clip).toBe(idle);g.step(idle,1,false,1,false);
  expect(g.step(idle,1,true,0,false).clip).toBe(talk);g.step(idle,10,false,9,false);
  expect(g.step(idle,10,true,0,false).clip).toBe(second);
 });
 it("holds a completed gesture through a long utterance, then resumes the continuing idle clock",()=>{
  const gesture=new Stand3DGesture(talk);
  expect(gesture.step(idle,5,true,0,false)).toEqual({clip:talk,time:0});
  expect(gesture.step(idle,6,true,1,false)).toEqual({clip:talk,time:1});
  expect(gesture.step(idle,7,true,1,false)).toEqual({clip:talk,time:talk.duration});
  expect(gesture.step(idle,10,true,3,false)).toEqual({clip:talk,time:talk.duration});
  expect(gesture.step(idle,11,false,1,false)).toEqual({clip:idle,time:11});
 });
 it("releases after sustained silence and suppresses new audio starts during cooldown",()=>{
  const gesture=new Stand3DGesture(talk);
  gesture.step(idle,0,true,0,false);
  expect(gesture.step(idle,.61,false,.61,false).clip).toBe(idle);
  expect(gesture.step(idle,.71,true,.1,false).clip).toBe(idle);
  gesture.step(idle,9,false,9,false);
  expect(gesture.step(idle,9,true,0,false).clip).toBe(talk);
 });
 it("holds its clock while paused, suppresses reduced-motion gestures, and tolerates absent/looping candidates",()=>{
  const gesture=new Stand3DGesture(talk);gesture.step(idle,0,true,0,false);
  expect(gesture.step(idle,0,true,0,false).time).toBe(0);
  expect(gesture.step(idle,0,true,0,true).clip).toBe(idle);
  expect(gesture.step(idle,0,true,0,false).clip).toBe(idle);
  expect(new Stand3DGesture(null).step(idle,0,true,0,false).clip).toBe(idle);
  expect(new Stand3DGesture(idle).step(idle,0,true,0,false).clip).toBe(idle);
 });
});
