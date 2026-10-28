import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { solveArmContact, Stand3DHandContact, type HandContactSettings } from "./Stand3DHandContact";

function arm() {
  const root=new THREE.Bone(),upper=new THREE.Bone(),lower=new THREE.Bone(),hand=new THREE.Bone();
  root.add(upper);upper.add(lower);lower.add(hand);
  lower.position.set(.3,0,0);hand.position.set(.25,0,0);lower.quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1),.8);
  hand.quaternion.setFromAxisAngle(new THREE.Vector3(1,0,0),.4);root.updateMatrixWorld(true);
  return {root,upper,lower,hand};
}
describe("hand contact IK",()=>{
 it("reaches a nearby target, keeps both segment lengths and retains authored wrist orientation",()=>{
  const f=arm(),q=f.hand.getWorldQuaternion(new THREE.Quaternion()),p=f.hand.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,.04,.02));
  solveArmContact(f.upper,f.lower,f.hand,p);
  expect(f.hand.getWorldPosition(new THREE.Vector3()).distanceTo(p)).toBeLessThan(1e-7);
  expect(f.hand.getWorldQuaternion(new THREE.Quaternion()).angleTo(q)).toBeLessThan(1e-7);
  expect(f.upper.getWorldPosition(new THREE.Vector3()).distanceTo(f.lower.getWorldPosition(new THREE.Vector3()))).toBeCloseTo(.3,7);
  expect(f.lower.getWorldPosition(new THREE.Vector3()).distanceTo(f.hand.getWorldPosition(new THREE.Vector3()))).toBeCloseTo(.25,7);
 });
 it("preserves elbow-side continuity around a nearly straight arm and clamps unreachable targets",()=>{
  const f=arm();f.lower.quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1),.001);f.root.updateMatrixWorld(true);
  for(let i=0;i<40;i++){
   solveArmContact(f.upper,f.lower,f.hand,new THREE.Vector3(.54,.03,Math.sin(i/20)*.01));
   expect([...f.upper.quaternion.toArray(),...f.lower.quaternion.toArray()].every(Number.isFinite)).toBe(true);
  }
  solveArmContact(f.upper,f.lower,f.hand,new THREE.Vector3(5,0,0));
  expect(f.hand.getWorldPosition(new THREE.Vector3()).length()).toBeCloseTo(.55,5);
 });
 it("weights reconstructed capsule contacts and leaves non-contact poses untouched",()=>{
  const f=arm();f.root.position.set(0,0,0);f.root.updateMatrixWorld(true);
  const p=f.hand.getWorldPosition(new THREE.Vector3());
  const settings:HandContactSettings={goals:[{bone:"hand",goal:2,radius:.06,offset:{x:0,y:0,z:0}}],colliders:[{bone:"root",type:1,weight:.75,radius:p.length()-.03,radiusSub:p.length()-.03,length:0,dampArea:.01,offset:{x:0,y:0,z:0},rotation:{x:0,y:0,z:0}}]};
  const solve=new Stand3DHandContact(settings,{root:f.root,hand:f.hand});solve.apply();
  expect(solve.maxBefore).toBeCloseTo(.03);expect(solve.maxAfter).toBeLessThan(solve.maxBefore);
  settings.colliders[0].radius=settings.colliders[0].radiusSub=.01;
  const q=f.upper.quaternion.clone();solve.apply();expect(solve.maxCorrection).toBe(0);expect(f.upper.quaternion.angleTo(q)).toBeLessThan(1e-7);
 });
});
