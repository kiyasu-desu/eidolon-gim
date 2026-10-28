import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { Stand3DBodyMotion, type SkeletalMotion } from "./Stand3DBodyMotion";

function clip(name: string, x: number, angle = 0) {
  const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), angle);
  const skeletal: SkeletalMotion = { version: 1, coordinates: "three-mirror-x", sampleRate: 30, tracks: [{ bone: "hips", positions: [[x, 1, 0], [x + 1, 1, 0]], rotations: [q.toArray(), [-q.x, -q.y, -q.z, -q.w]] }] };
  return { name, skeletal };
}

describe("Unity baked body playback", () => {
  it("interpolates local translation and antipodal quaternions without a wrist flip", () => {
    const bone = new THREE.Bone(), motion = new Stand3DBodyMotion({ hips: bone });
    expect(motion.apply(clip("idle", 2, Math.PI / 2), 1 / 60, 0, false)).toBe(true);
    expect(bone.position.x).toBeCloseTo(2.5);
    expect(bone.quaternion.angleTo(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2))).toBeCloseTo(0);
  });
  it("transitions from the last sampled pose even when the rig has been reset to bind", () => {
    const bone = new THREE.Bone(), motion = new Stand3DBodyMotion({ hips: bone });
    const idle = clip("idle", 1), pose = clip("pose", 3, Math.PI / 2);
    motion.apply(idle, 0, 0, false); bone.position.set(0,0,0);
    motion.apply(pose, 0, 0, false); expect(bone.position.x).toBe(1);
    motion.apply(pose, 0, .15, false); expect(bone.position.x).toBeCloseTo(2);
    motion.apply(pose, 0, .15, false); expect(bone.position.x).toBeCloseTo(3);
  });
  it("snaps reduced motion to a clamped fixed pose and declines unsupported data", () => {
    const bone = new THREE.Bone(), motion = new Stand3DBodyMotion({ hips: bone });
    motion.apply(clip("idle", 1), 0, 0, false);
    motion.apply(clip("pose", 3), 100, 0, true); expect(bone.position.x).toBe(4);
    expect(motion.apply({ name: "legacy" }, 0, 0, false)).toBe(false);
    const future = clip("future", 0); future.skeletal.version = 2;
    expect(motion.apply(future, 0, 0, false)).toBe(false);
  });
});
