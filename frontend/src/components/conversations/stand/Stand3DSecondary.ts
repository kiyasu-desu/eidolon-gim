import * as THREE from "three";
import type { SwingSetting, SwingChainSetting, SwingClearanceSettings } from "./Stand3DSwing";
import type { StaticColliderSetting } from "./Stand3DCollision";
import type { HandContactSettings } from "./Stand3DHandContact";

export type AuxiliarySetting = { bone: string; reference: string; axis: "x" | "y" | "z"; coefficient: number };
export type SecondaryMotion = { version: number; auxiliary: AuxiliarySetting[]; body: SwingSetting[]; colliders: StaticColliderSetting[]; hands?: HandContactSettings; bodyChains?: SwingChainSetting[]; hairChains?: SwingChainSetting[]; clothClearance?:SwingClearanceSettings };

// Original coefficients, but a bounded swing/twist approximation. The original
// Quartz decomposition/compose enums and Humanoid DoF implementation are unknown.
export class Stand3DSecondary {
  private drivers: Array<{ bone: THREE.Bone; reference: THREE.Bone; inverse: THREE.Quaternion; bind: THREE.Quaternion; setting: AuxiliarySetting }>;
  private delta = new THREE.Quaternion();
  private correction = new THREE.Quaternion();
  constructor(settings: AuxiliarySetting[], bones: Readonly<Record<string, THREE.Bone>>) {
    this.drivers = settings.flatMap(setting => {
      const bone = bones[setting.bone], reference = bones[setting.reference];
      if (!bone || !reference) return [];
      return [{ bone, reference, inverse: reference.quaternion.clone().invert(), bind: bone.quaternion.clone(), setting }];
    });
  }
  get count(): number { return this.drivers.length; }
  apply(): void {
    for (const d of this.drivers) {
      this.delta.copy(d.inverse).multiply(d.reference.quaternion).normalize();
      // Only the specified axis participates. Signed atan2 with canonical w
      // avoids interpreting equivalent q/-q as a full revolution.
      if (this.delta.w < 0) this.delta.set(-this.delta.x, -this.delta.y, -this.delta.z, -this.delta.w);
      const angle = 2 * Math.atan2(this.delta[d.setting.axis], this.delta.w) * d.setting.coefficient;
      this.correction.set(0, 0, 0, Math.cos(angle / 2));
      this.correction[d.setting.axis] = Math.sin(angle / 2);
      d.bone.quaternion.copy(d.bind).multiply(this.correction);
    }
  }
}
