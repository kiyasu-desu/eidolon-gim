import { describe,expect,it } from "vitest";
import * as THREE from "three";
import { Stand3DSlide } from "./Stand3DSlide";
import type { SwingSetting } from "./Stand3DSwing";
const setting:SwingSetting={bone:"skin",damping:.4,stiffness:.4,spring:.1,mass:.1,pendulum:0,pendulumRange:1,dynamicType:1,axisAddXToY:.2,axisAddXToZ:.1,limitInfo:{useLimit:0,axisX:{x:0,y:0},axisY:{x:0,y:0},axisZ:{x:0,y:0}}};
describe("zero-length Slide skin nodes",()=>{
 it("moves only weighted positional helpers, caps offset and resets after teleport/reduced motion",()=>{
  const root=new THREE.Bone(),skin=new THREE.Bone(),unused=new THREE.Bone();root.add(skin,unused);root.updateMatrixWorld(true);
  const solve=new Stand3DSlide([setting,{...setting,bone:"unused"}],{skin,unused},new Set(["skin"]));expect(solve.count).toBe(1);
  let peak=0;
  for(let i=0;i<240;i++){root.position.x=Math.sin(i/10)*.03;skin.position.set(0,0,0);root.updateMatrixWorld(true);solve.update(1/60,true);peak=Math.max(peak,solve.maxOffset);expect(solve.maxOffset).toBeLessThanOrEqual(.012000001);expect(skin.position.toArray().every(Number.isFinite)).toBe(true)}
  expect(peak).toBeGreaterThan(.001);expect(unused.position.length()).toBe(0);
  skin.position.set(0,0,0);root.position.x=10;root.updateMatrixWorld(true);solve.update(0,true);expect(solve.maxOffset).toBe(0);
  skin.position.set(0,0,0);solve.update(0,false);expect(skin.position.length()).toBe(0);
 });
});
