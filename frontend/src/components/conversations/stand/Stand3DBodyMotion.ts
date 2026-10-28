import * as THREE from "three";

export type SkeletalMotion = {
  version: number;
  coordinates: string;
  sampleRate: number;
  tracks: Array<{
    bone: string;
    positions: [number, number, number][];
    rotations: [number, number, number, number][];
  }>;
};

type Pose = { position: THREE.Vector3; rotation: THREE.Quaternion };
type BodyClip = { name: string; skeletal?: SkeletalMotion };
const TRANSITION_SECONDS = 0.3;

// Samples already use the web rig's mirrored coordinates. Unity, rather than
// browser muscle-angle guesses, has solved these local bone transforms.
export class Stand3DBodyMotion {
  private active: BodyClip | null = null;
  private previous = new Map<string, Pose>();
  private from = new Map<string, Pose>();
  private elapsed = TRANSITION_SECONDS;
  private position = new THREE.Vector3();
  private nextPosition = new THREE.Vector3();
  private rotation = new THREE.Quaternion();
  private nextRotation = new THREE.Quaternion();

  constructor(private bones: Readonly<Record<string, THREE.Bone>>) {}

  apply(clip: BodyClip | null, time: number, dt: number, reducedMotion: boolean): boolean {
    const motion = clip?.skeletal;
    if (!motion || motion.version !== 1 || motion.coordinates !== "three-mirror-x" || !(motion.sampleRate > 0)) {
      this.active = null;
      this.previous.clear();
      this.from.clear();
      return false;
    }
    if (this.active !== clip) {
      this.from = new Map(this.previous);
      this.previous = new Map();
      this.elapsed = this.active ? 0 : TRANSITION_SECONDS;
      this.active = clip;
    }
    this.elapsed = reducedMotion ? TRANSITION_SECONDS : Math.min(TRANSITION_SECONDS, this.elapsed + Math.max(0, dt));
    const t = this.elapsed / TRANSITION_SECONDS;
    const blend = t * t * (3 - 2 * t);
    for (const track of motion.tracks) {
      const bone = this.bones[track.bone];
      const count = Math.min(track.positions.length, track.rotations.length);
      if (!bone || count === 0) continue;
      const frame = THREE.MathUtils.clamp(time * motion.sampleRate, 0, count - 1);
      const i = Math.floor(frame), j = Math.min(i + 1, count - 1), fraction = frame - i;
      this.position.fromArray(track.positions[i]).lerp(this.nextPosition.fromArray(track.positions[j]), fraction);
      this.rotation.fromArray(track.rotations[i]).normalize();
      this.nextRotation.fromArray(track.rotations[j]).normalize();
      this.rotation.slerp(this.nextRotation, fraction);
      const from = this.from.get(track.bone);
      if (from && blend < 1) {
        bone.position.copy(from.position).lerp(this.position, blend);
        bone.quaternion.copy(from.rotation).slerp(this.rotation, blend);
      } else {
        bone.position.copy(this.position);
        bone.quaternion.copy(this.rotation);
      }
      let saved = this.previous.get(track.bone);
      if (!saved) {
        saved = { position: new THREE.Vector3(), rotation: new THREE.Quaternion() };
        this.previous.set(track.bone, saved);
      }
      saved.position.copy(bone.position); saved.rotation.copy(bone.quaternion);
    }
    if (blend === 1) this.from.clear();
    return true;
  }
}
