import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { Stand3DSecondary } from "./Stand3DSecondary";
import { Stand3DCollision } from "./Stand3DCollision";
import { Stand3DSwing, type SwingSetting } from "./Stand3DSwing";

describe("auxiliary joint approximation", () => {
  it("uses change from bind rotation and the original signed coefficient without accumulating", () => {
    const reference = new THREE.Bone(), helper = new THREE.Bone(), x = new THREE.Vector3(1,0,0);
    reference.quaternion.setFromAxisAngle(new THREE.Vector3(0,1,0),.7);
    const bind = reference.quaternion.clone();
    const solve = new Stand3DSecondary([{ bone:"helper", reference:"reference", axis:"x", coefficient:-.8 }], { reference,helper });
    solve.apply(); expect(helper.quaternion.angleTo(new THREE.Quaternion())).toBeCloseTo(0);
    reference.quaternion.copy(bind).multiply(new THREE.Quaternion().setFromAxisAngle(x,.5));
    const expected = new THREE.Quaternion().setFromAxisAngle(x,-.4);
    for(let i=0;i<100;i++)solve.apply();
    expect(helper.quaternion.angleTo(expected)).toBeCloseTo(0);
    reference.quaternion.set(-reference.quaternion.x,-reference.quaternion.y,-reference.quaternion.z,-reference.quaternion.w);
    solve.apply(); expect(helper.quaternion.angleTo(expected)).toBeCloseTo(0);
  });
});

function fixture(limited: boolean) {
  const anchor = new THREE.Bone(), joint = new THREE.Bone(), tip = new THREE.Bone();
  anchor.add(joint);joint.add(tip);tip.position.x=1;anchor.updateMatrixWorld(true);
  const c = new Stand3DCollision([{ bone:"anchor",source:"sphere",type:0,collisionMask:64,vector3_A:{x:-1,y:.1,z:0},vector3_B:{x:0,y:0,z:0},float_A:.2,float_B:.2 }],{anchor});
  c.capture();
  const setting: SwingSetting={bone:"joint",damping:.5,stiffness:0,spring:0,mass:0,pendulum:0,pendulumRange:1,dynamicType:0,limitInfo:{useLimit:limited?1:0,axisX:{x:0,y:0},axisY:{x:0,y:0},axisZ:{x:0,y:0}},collision:{type:0,collisionMask:64,vector3_A:{x:0,y:0,z:0},float_A:.02}};
  const swing=new Stand3DSwing([setting,{...setting,bone:"tip"}],{joint,tip},c);
  return {anchor,joint,tip,c,swing};
}

describe("chain collision", () => {
  it("finds contact between two safe endpoints and a body collider, and separates the link",()=>{
    const root=new THREE.Bone();root.updateMatrixWorld(true);
    const collision=new Stand3DCollision([{bone:"root",source:"sphere",type:0,collisionMask:1,vector3_A:{x:0,y:0,z:0},vector3_B:{x:0,y:0,z:0},float_A:.2,float_B:.2}],{root});collision.capture();
    const a=new THREE.Vector3(-.5,0,0),b=new THREE.Vector3(.5,0,0);
    expect(collision.penetration(a,.02,1)).toBe(0);expect(collision.penetration(b,.02,1)).toBe(0);
    expect(collision.edgePenetration(a,b,.02,1)).toBeCloseTo(.22);
    collision.projectEdge(a,b,.02,1);expect(collision.edgePenetration(a,b,.02,1)).toBeLessThan(1e-7);expect(a.distanceTo(b)).toBeCloseTo(1);
  });
  it("converts capsule axes and line insets without mirroring shape metadata", () => {
    const root=new THREE.Bone(),hand=new THREE.Bone();root.add(hand);hand.position.x=1;root.updateMatrixWorld(true);
    const capsule=new Stand3DCollision([{bone:"root",source:"capsule",type:1,collisionMask:1,vector3_A:{x:0,y:0,z:0},vector3_B:{x:0,y:1,z:0},float_A:.1,float_B:.1}],{root});
    capsule.capture();expect(capsule.penetration(new THREE.Vector3(.45,0,0),0,1)).toBeCloseTo(.05);
    const line=new Stand3DCollision([{bone:"hand",source:"line",type:2,collisionMask:1,vector3_A:{x:.2,y:.1,z:0},vector3_B:{x:0,y:0,z:0},float_A:.1,float_B:.1}],{hand});
    line.capture();expect(line.penetration(new THREE.Vector3(1,0,0),0,1)).toBe(0);
    expect(line.penetration(new THREE.Vector3(.8,0,0),0,1)).toBeCloseTo(.1);
  });
  it("projects a reachable contact while preserving bone length and mask isolation", () => {
    const f=fixture(false),point=new THREE.Vector3(1,0,0);
    expect(f.c.penetration(point,.02,8)).toBe(0);
    expect(f.c.penetration(point,.02,64)).toBeCloseTo(.12);
    f.swing.update(0,true);
    expect(f.swing.maxPenetration).toBeLessThan(1e-4);
    f.swing.update(1/60,true);
    expect(f.swing.maxPenetration).toBeLessThan(1e-4);
    expect(f.tip.getWorldPosition(new THREE.Vector3()).distanceTo(f.joint.getWorldPosition(new THREE.Vector3()))).toBeCloseTo(1,8);
    expect(f.joint.quaternion.angleTo(new THREE.Quaternion())).toBeGreaterThan(.1);
  });
  it("reports unresolved contact when source limits prevent a safe direction", () => {
    const f=fixture(true);f.swing.update(1/60,true);
    expect(f.swing.maxPenetration).toBeGreaterThan(.1);
    expect(f.joint.quaternion.angleTo(new THREE.Quaternion())).toBeCloseTo(0);
  });
});
