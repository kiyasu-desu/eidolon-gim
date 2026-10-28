// Pure decisions for her 3D stand in the call layer: recognizing a 3D stand outfit,
// framing the Three.js camera for desktop ("waist"), mobile ("knees"), and "full" views,
// choosing the idle clip under normal or reduced motion, and stepping her facial/head pose
// from `StandDirection`.

import type { Outfit } from "@/lib/api";
import type { Emotion, StandDirection } from "@/lib/standAnimations";

export type Stand3DFraming = "knees" | "waist" | "full";

export type Stand3DClipInfo = {
  name: string;
  duration: number;
  sourceLoop: boolean;
  role?: string;
};

export type Stand3DCameraFrame = {
  targetY: number;
  cameraZ: number;
  fov: number;
};

export type Stand3DPoseState = {
  clipTime: number;
  speakingPhase: number;
  mouthOpen: number;
  gazeWeight: number;
  shapeWeights: Record<string, number>;
  lastNodId: number | null;
  nodKind: "yes" | "no" | null;
  nodElapsed: number | null;
  headPitchDeg: number;
  headYawDeg: number;
};

const CAMERA_FOV_DEG = 26;
const FRONT_SURFACE_Z_OFFSET = 0.08;

const FRAMING_BOUNDS: Record<Stand3DFraming, { topY: number; bottomY: number; minSpanX: number }> = {
  waist: { topY: 1.66, bottomY: 0.86, minSpanX: 0.56 },
  knees: { topY: 1.66, bottomY: 0.50, minSpanX: 0.62 },
  full: { topY: 1.68, bottomY: -0.04, minSpanX: 0.72 },
};

const MOOD_SHAPES: Record<Emotion, Readonly<Record<string, number>>> = {
  calm: {},
  happy: { "b_brow.brow_002": 0.75, "b_mouth.mouth_002": 0.85 },
  shy: { "b_brow.brow_003": 0.75, "b_mouth.mouth_016": 0.65 },
  surprised: { "b_brow.brow_013": 0.7, "b_eye.eye_008": 0.65 },
  sad: { "b_brow.brow_004": 0.8, "b_mouth.mouth_005": 0.75 },
  angry: { "b_brow.brow_009": 0.85, "b_mouth.mouth_006": 0.75 },
  thinking: { "b_brow.brow_005": 0.7, "b_mouth.mouth_020": 0.6 },
};

const ALL_MOOD_SHAPE_KEYS = Array.from(
  new Set(Object.values(MOOD_SHAPES).flatMap((weights) => Object.keys(weights))),
);

const MOOD_BLEND_SECONDS = 0.3;
const MOUTH_BLEND_SECONDS = 0.1;
const NOD_DURATION_SECONDS = 0.55;

export function is3DStandOutfit(outfit: Pick<Outfit, "id">): boolean {
  return outfit.id.startsWith("stand_3d/");
}

export function frameStand3D(
  framing: Stand3DFraming,
  viewportWidth: number,
  viewportHeight: number,
): Stand3DCameraFrame {
  const { topY, bottomY, minSpanX } = FRAMING_BOUNDS[framing];
  const spanY = topY - bottomY;
  const targetY = (topY + bottomY) / 2;
  const aspect = Math.max(0.1, viewportWidth / Math.max(1, viewportHeight));
  const halfVerticalSpan = Math.max(spanY / 2, minSpanX / aspect / 2);
  const halfFovRad = (CAMERA_FOV_DEG * Math.PI) / 360;
  const cameraZ = halfVerticalSpan / Math.tan(halfFovRad) + FRONT_SURFACE_Z_OFFSET;
  return { targetY, cameraZ, fov: CAMERA_FOV_DEG };
}

export function selectStand3DClip<T extends Stand3DClipInfo>(
  clips: readonly T[],
  isReducedMotion: boolean,
): T | null {
  const bodyClips = clips.filter((clip) => clip.name.endsWith("_b"));
  if (bodyClips.length === 0) return null;
  if (isReducedMotion) {
    return (
      bodyClips.find((clip) => clip.name.endsWith("_pose_b")) ??
      bodyClips.find((clip) => !clip.sourceLoop) ??
      bodyClips[0]
    );
  }
  return (
    bodyClips.find((clip) => clip.role === "portraitIdle" && clip.sourceLoop) ??
    bodyClips.find((clip) => clip.sourceLoop) ??
    bodyClips[bodyClips.length - 1]
  );
}

export function createStand3DPoseState(): Stand3DPoseState {
  const shapeWeights: Record<string, number> = {};
  for (const key of ALL_MOOD_SHAPE_KEYS) {
    shapeWeights[key] = 0;
  }
  return {
    clipTime: 0,
    speakingPhase: 0,
    mouthOpen: 0,
    gazeWeight: 0,
    shapeWeights,
    lastNodId: null,
    nodKind: null,
    nodElapsed: null,
    headPitchDeg: 0,
    headYawDeg: 0,
  };
}

export function stepStand3DPose(
  prev: Stand3DPoseState,
  direction: StandDirection,
  dt: number,
  isReducedMotion: boolean,
  clipDuration: number,
  clipLoops: boolean,
): Stand3DPoseState {
  const clampedDt = Math.max(0, dt);

  let clipTime = 0;
  if (!isReducedMotion && clipDuration > 0) {
    const advanced = prev.clipTime + clampedDt;
    clipTime = clipLoops ? advanced % clipDuration : Math.min(advanced, clipDuration);
  }

  let speakingPhase = prev.speakingPhase;
  let mouthOpen = prev.mouthOpen;
  const mouthStep = clampedDt / MOUTH_BLEND_SECONDS;
  if (direction.speaking) {
    speakingPhase = (prev.speakingPhase + clampedDt * 3.2) % 1;
    const targetOpen = 0.25 + 0.65 * (0.5 - 0.5 * Math.cos(speakingPhase * Math.PI * 2));
    mouthOpen = moveToward(prev.mouthOpen, targetOpen, Math.max(mouthStep, 0.35));
  } else {
    speakingPhase = 0;
    mouthOpen = moveToward(prev.mouthOpen, 0, mouthStep);
    if (mouthOpen < 1e-3) mouthOpen = 0;
  }

  const moodBlend = Math.min(1, clampedDt / MOOD_BLEND_SECONDS);
  const moodTargets = MOOD_SHAPES[direction.mood] ?? {};
  const shapeWeights: Record<string, number> = {};
  for (const key of ALL_MOOD_SHAPE_KEYS) {
    const target = moodTargets[key] ?? 0;
    const next = moveToward(prev.shapeWeights[key] ?? 0, target, moodBlend);
    shapeWeights[key] = next < 1e-3 && target === 0 ? 0 : next;
  }

  const gazeTarget = direction.looking ? 1 : 0;
  const gazeWeight = moveToward(prev.gazeWeight, gazeTarget, moodBlend);

  let lastNodId = prev.lastNodId;
  let nodKind = prev.nodKind;
  let nodElapsed = prev.nodElapsed;
  if (direction.nod && direction.nod.id !== prev.lastNodId) {
    lastNodId = direction.nod.id;
    nodKind = direction.nod.kind;
    nodElapsed = 0;
  }
  if (nodElapsed !== null) {
    nodElapsed += clampedDt;
    if (nodElapsed >= NOD_DURATION_SECONDS) {
      nodElapsed = null;
      nodKind = null;
    }
  }

  let nodPitch = 0;
  let nodYaw = 0;
  if (nodElapsed !== null && nodKind !== null) {
    const progress = nodElapsed / NOD_DURATION_SECONDS;
    const envelope = Math.sin(progress * Math.PI);
    if (nodKind === "yes") {
      nodPitch = Math.sin(progress * Math.PI * 2) * 6.5 * envelope;
    } else {
      nodYaw = Math.sin(progress * Math.PI * 2) * 8.0 * envelope;
    }
  }

  const headPitchDeg = gazeWeight * 2.5 + nodPitch;
  const headYawDeg = nodYaw;

  return {
    clipTime,
    speakingPhase,
    mouthOpen,
    gazeWeight,
    shapeWeights,
    lastNodId,
    nodKind,
    nodElapsed,
    headPitchDeg,
    headYawDeg,
  };
}

function moveToward(current: number, target: number, maxDelta: number): number {
  if (Math.abs(target - current) <= maxDelta) return target;
  return current + Math.sign(target - current) * maxDelta;
}
