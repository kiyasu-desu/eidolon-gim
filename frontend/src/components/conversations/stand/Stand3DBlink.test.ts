import {describe,expect,it} from "vitest";
import {Stand3DBlink,type BlinkTiming} from "./Stand3DBlink";
const timing:BlinkTiming={minInterval:3.4,maxInterval:5.6,close:.05,hold:.025,open:.095,seed:1953787250};
describe("native-sample calibrated automatic blink",()=>{
 it("has bounded intervals and a short smooth closure independent of body-loop boundaries",()=>{
  const blink=new Stand3DBlink(timing),events:number[]=[],widths:number[]=[];let start:number|null=null;
  for(let i=0;i<3600;i++){
   const value=blink.step(1/120,0,false);expect(value).toBeGreaterThanOrEqual(0);expect(value).toBeLessThanOrEqual(1);
   if(value>0&&start===null){start=i/120;events.push(start)}
   if(value===0&&start!==null){widths.push(i/120-start);start=null}
  }
  expect(events.length).toBeGreaterThanOrEqual(5);
  for(let i=1;i<events.length;i++){expect(events[i]-events[i-1]).toBeGreaterThanOrEqual(3.39);expect(events[i]-events[i-1]).toBeLessThanOrEqual(5.61)}
  for(const w of widths)expect(w).toBeCloseTo(.17,1);
 });
 it("keeps the same schedule at 30/60/120fps and freezes on dt=0",()=>{
  const events=[30,60,120].map(fps=>{const b=new Stand3DBlink(timing),starts:number[]=[];let prior=0;for(let i=0;i<fps*20;i++){const v=b.step(1/fps,0,false);if(v>.2&&prior<=.2)starts.push((i+1)/fps);if(v>.2)expect(b.step(0,0,false)).toBeCloseTo(v);prior=v}return starts});
  expect(events[0].length).toBeGreaterThan(2);
  expect(events[0].length).toBe(events[2].length);
  for(let i=0;i<events[0].length;i++)expect(Math.abs(events[0][i]-events[2][i])).toBeLessThanOrEqual(1/30);
 });
 it("yields to authored or explicitly closed eyes, suppresses reduced-motion blinking, and tolerates old assets",()=>{
  const b=new Stand3DBlink({...timing,minInterval:.2,maxInterval:.2});b.step(.1,0,false);expect(b.step(.1,1,false)).toBe(0);
  expect(b.step(.1,0,false)).toBe(0);expect(b.step(.1,0,true)).toBe(0);expect(b.step(.1,0,true)).toBe(0);
  expect(new Stand3DBlink(null).step(10,0,false)).toBe(0);
 });
});
