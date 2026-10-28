import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { Stand3DSwing, type SwingSetting } from "./Stand3DSwing";
import { Stand3DCollision } from "./Stand3DCollision";

function fixture() {
  const head = new THREE.Bone();
  const joint = new THREE.Bone();
  const tip = new THREE.Bone();
  head.add(joint); joint.add(tip); tip.position.x = 0.1;
  head.updateMatrixWorld(true);
  const source: SwingSetting = {
    bone: "joint", damping: 0.5, stiffness: 0.001, spring: 0.55, mass: 0,
    dynamicType: 0, pendulum: 0, pendulumRange: 1,
    limitInfo: { useLimit: 1, axisX: { x: 0, y: 0 }, axisY: { x: -10, y: 30 }, axisZ: { x: -20, y: 10 } },
  };
  const swing = new Stand3DSwing([source, { ...source, bone: "tip", mass: 0.85 }], { joint, tip });
  const advance = (dt: number) => {
    joint.quaternion.identity(); head.updateMatrixWorld(true);
    swing.update(dt, true);
  };
  return { head, joint, tip, swing, advance };
}

describe("hair swing", () => {
  it("applies optional clip calibration within authored limits without accumulating it into dynamics",()=>{
    const root=new THREE.Bone(),joint=new THREE.Bone(),tip=new THREE.Bone();root.add(joint);joint.add(tip);tip.position.x=.1;root.updateMatrixWorld(true);
    const row:SwingSetting={bone:'joint',damping:1,stiffness:0,spring:0,mass:0,pendulum:0,pendulumRange:0,dynamicType:0,limitInfo:{useLimit:1,axisX:{x:0,y:0},axisY:{x:0,y:0},axisZ:{x:-5,y:5}}};
    const q=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),Math.PI/3);
    const swing=new Stand3DSwing([row],{joint,tip},undefined,[],{version:1,clips:['talk'],response:14,joints:[{bone:'joint',rotation:q.toArray()}]});
    const frame=(clip:string,enabled=true)=>{joint.quaternion.identity();root.updateMatrixWorld(true);swing.update(.1,enabled,clip)};
    frame('idle');expect(joint.quaternion.angleTo(new THREE.Quaternion())).toBe(0);
    frame('talk');expect(joint.quaternion.angleTo(new THREE.Quaternion())).toBeGreaterThan(.05);
    for(let i=0;i<20;i++)frame('talk');expect(joint.quaternion.angleTo(new THREE.Quaternion())).toBeCloseTo(5*Math.PI/180,8);expect(joint.getWorldPosition(new THREE.Vector3()).distanceTo(tip.getWorldPosition(new THREE.Vector3()))).toBeCloseTo(.1,9);
    for(let i=0;i<20;i++)frame('idle');expect(joint.quaternion.angleTo(new THREE.Quaternion())).toBeLessThan(1e-6);
    frame('talk');frame('talk',false);expect(joint.quaternion.angleTo(new THREE.Quaternion())).toBe(0);
    frame('idle');expect(joint.quaternion.angleTo(new THREE.Quaternion())).toBe(0);
  });
  it("resolves a dynamic line's middle contact when both endpoint spheres are clear",()=>{
    const root=new THREE.Bone(),joint=new THREE.Bone(),tip=new THREE.Bone();root.add(joint);joint.add(tip);tip.position.x=1;root.updateMatrixWorld(true);
    const row:SwingSetting={bone:'joint',damping:.5,stiffness:0,spring:0,mass:0,pendulum:0,pendulumRange:0,dynamicType:0,collision:{type:2,collisionMask:1,vector3_A:{x:0,y:0,z:0},float_A:.02},limitInfo:{useLimit:0,axisX:{x:-180,y:180},axisY:{x:-180,y:180},axisZ:{x:-180,y:180}}};
    const collision=new Stand3DCollision([{bone:'root',source:'sphere',type:0,collisionMask:1,vector3_A:{x:-.5,y:.02,z:0},vector3_B:{x:0,y:0,z:0},float_A:.1,float_B:.1}],{root});collision.capture();
    const swing=new Stand3DSwing([row,{...row,bone:'tip'}],{joint,tip},collision);swing.update(0,true);
    expect(collision.edgePenetration(tip.getWorldPosition(new THREE.Vector3()),joint.getWorldPosition(new THREE.Vector3()),.02,1)).toBeLessThan(1e-4);
    expect(tip.getWorldPosition(new THREE.Vector3()).distanceTo(joint.getWorldPosition(new THREE.Vector3()))).toBeCloseTo(1,8);
  });
  it("keeps anchored line contacts consistent at 30, 60 and 120 display FPS",()=>{
    const results=[30,60,120].map(fps=>{const root=new THREE.Bone(),joint=new THREE.Bone(),tip=new THREE.Bone();root.add(joint);joint.add(tip);tip.position.x=1;root.updateMatrixWorld(true);const row:SwingSetting={bone:'joint',damping:.5,stiffness:0,spring:0,mass:0,pendulum:0,pendulumRange:0,dynamicType:0,collision:{type:2,collisionMask:1,vector3_A:{x:0,y:0,z:0},float_A:.02},limitInfo:{useLimit:0,axisX:{x:-180,y:180},axisY:{x:-180,y:180},axisZ:{x:-180,y:180}}};const c=new Stand3DCollision([{bone:'root',source:'sphere',type:0,collisionMask:1,vector3_A:{x:-.5,y:.02,z:0},vector3_B:{x:0,y:0,z:0},float_A:.1,float_B:.1}],{root});c.capture();const swing=new Stand3DSwing([row,{...row,bone:'tip'}],{joint,tip},c);for(let i=0;i<fps;i++){joint.quaternion.identity();root.updateMatrixWorld(true);swing.update(1/fps,true)}expect(swing.maxLinePenetration).toBeLessThan(1e-4);return joint.quaternion.clone()});expect(results[0].angleTo(results[1])).toBeLessThan(1e-6);expect(results[1].angleTo(results[2])).toBeLessThan(1e-6);
  });
  it("uses child inertia, preserves bone length and source angle bounds through motion and reset", () => {
    const f = fixture();
    expect(f.swing.segmentCount).toBe(1); // The terminal component has no segment.
    for (let frame = 0; frame < 600; frame++) {
      f.head.position.y = Math.sin(frame / 30) * 0.02;
      f.advance(1 / 60);
      const angles = new THREE.Euler().setFromQuaternion(f.joint.quaternion, "YXZ");
      expect([angles.x, angles.y, angles.z].every(Number.isFinite)).toBe(true);
      expect(angles.z).toBeGreaterThanOrEqual(-10 * Math.PI / 180 - 1e-8);
      expect(angles.z).toBeLessThanOrEqual(20 * Math.PI / 180 + 1e-8);
      expect(f.joint.getWorldPosition(new THREE.Vector3()).distanceTo(f.tip.getWorldPosition(new THREE.Vector3()))).toBeCloseTo(0.1, 7);
    }
    expect(f.joint.quaternion.angleTo(new THREE.Quaternion())).toBeGreaterThan(0.01);
    f.joint.quaternion.identity(); f.head.updateMatrixWorld(true);
    f.swing.update(0, false);
    f.swing.update(0, true);
    expect(f.joint.quaternion.angleTo(new THREE.Quaternion())).toBe(0);
  });

  it("runs the same fixed ticks at 30, 60 and 120 display FPS without a large-gap backlog", () => {
    const results = [30, 60, 120].map((fps) => {
      const f = fixture();
      for (let i = 0; i < fps * 2; i++) f.advance(1 / fps);
      const result = f.joint.quaternion.clone();
      f.joint.quaternion.identity(); f.head.updateMatrixWorld(true);
      f.swing.update(10, true);
      expect(f.joint.quaternion.angleTo(new THREE.Quaternion())).toBeLessThan(0.4);
      return result;
    });
    expect(results[0].angleTo(results[1])).toBeLessThan(1e-6);
    expect(results[1].angleTo(results[2])).toBeLessThan(1e-6);
  });
});
