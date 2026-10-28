import { describe,expect,it } from "vitest";
import * as THREE from "three";
import { evaluateFaceCurve,cameraFaceWeights,type FaceCorrection } from "./Stand3DFaceCorrection";
describe("authored camera corrective curves",()=>{
 it("evaluates unweighted Hermite tangents and clamps beyond authored endpoints",()=>{
  const keys=[{time:0,value:0,inSlope:0,outSlope:2},{time:1,value:1,inSlope:0,outSlope:0}];
  expect(evaluateFaceCurve(keys,-1)).toBe(0);expect(evaluateFaceCurve(keys,2)).toBe(1);expect(evaluateFaceCurve(keys,.5)).toBeCloseTo(.75);
 });
 it("measures camera angles in the moving head frame and mirrors yaw once",()=>{
  const head=new THREE.Bone(),camera=new THREE.PerspectiveCamera();head.quaternion.setFromAxisAngle(new THREE.Vector3(0,1,0),.3);head.updateMatrixWorld(true);
  camera.position.set(Math.sin(.3-Math.PI/4),0,Math.cos(.3-Math.PI/4));
  const s:FaceCorrection={version:1,target:"head",curves:[{shape:"side",axis:"yaw",keys:[{time:0,value:0,inSlope:0,outSlope:0},{time:45,value:1,inSlope:0,outSlope:0}]}]};
  expect(cameraFaceWeights(s,{head},camera).side).toBeCloseTo(1);expect(cameraFaceWeights(undefined,{head},camera)).toEqual({});
 });
});
