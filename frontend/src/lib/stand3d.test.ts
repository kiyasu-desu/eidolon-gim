import { describe, expect, it } from "vitest";
import {
  createStand3DPoseState,
  frameStand3D,
  is3DStandOutfit,
  selectStand3DClip,
  stepStand3DPose,
  type Stand3DClipInfo,
} from "@/lib/stand3d";
import { CALM, type StandDirection } from "@/lib/standAnimations";

const TEMARI_CLIPS: readonly Stand3DClipInfo[] = [
  { name: "mot_all_chr_ttmr_idle-001_in_b", duration: 1, sourceLoop: false },
  { name: "mot_all_chr_ttmr_idle-001_in_f", duration: 1, sourceLoop: false },
  { name: "mot_all_chr_ttmr_idle-001_pose_f", duration: 1 / 30, sourceLoop: false },
  { name: "mot_all_chr_ttmr_idle-001_pose_b", duration: 1 / 30, sourceLoop: false },
  { name: "mot_lesson_chr_cmmn_cmmn-vi-idle-ac-001_lp_b", duration: 20.533335, sourceLoop: true },
  { name: "mot_lesson_chr_cmmn_cmmn-vi-idle-ac-001_lp_f", duration: 20.533333, sourceLoop: true },
];

describe("identifying a 3D stand outfit", () => {
  it("tells a 3D stand outfit apart from a Spine stand outfit", () => {
    expect(is3DStandOutfit({ id: "stand_3d/ttmr-default" })).toBe(true);
    expect(is3DStandOutfit({ id: "stand/1030010010" })).toBe(false);
    expect(is3DStandOutfit({ id: "stand_costume/1030010010" })).toBe(false);
  });
});

describe("framing her 3D stand in the call layer", () => {
  it("frames head-to-waist on desktop, head-to-knees on mobile, and full height in full framing", () => {
    const waist = frameStand3D("waist", 800, 900);
    const knees = frameStand3D("knees", 390, 675);
    const full = frameStand3D("full", 400, 800);

    expect(waist.targetY).toBeGreaterThan(knees.targetY);
    expect(knees.targetY).toBeGreaterThan(full.targetY);
    expect(waist.cameraZ).toBeLessThan(knees.cameraZ);
    expect(knees.cameraZ).toBeLessThan(full.cameraZ);
  });

  it("pulls the camera back on a narrow viewport so her shoulders are not clipped", () => {
    const wide = frameStand3D("waist", 900, 900);
    const narrow = frameStand3D("waist", 240, 900);

    expect(narrow.cameraZ).toBeGreaterThan(wide.cameraZ);
    expect(narrow.targetY).toBe(wide.targetY);
  });
});

describe("selecting her 3D idle clip", () => {
  it("prefers an explicit calibrated portrait idle without replacing reduced motion or legacy selection",()=>{
    const portrait={name:"eidolon_ttmr_portrait-idle_b",duration:20,sourceLoop:true,role:"portraitIdle"};
    expect(selectStand3DClip([...TEMARI_CLIPS,portrait],false)).toBe(portrait);
    expect(selectStand3DClip([...TEMARI_CLIPS,portrait],true)?.name).toBe('mot_all_chr_ttmr_idle-001_pose_b');
    expect(selectStand3DClip(TEMARI_CLIPS,false)?.name).toBe('mot_lesson_chr_cmmn_cmmn-vi-idle-ac-001_lp_b');
  });
  it("plays the looping body idle clip in normal motion and holds her static pose in reduced motion", () => {
    expect(selectStand3DClip(TEMARI_CLIPS, false)?.name).toBe(
      "mot_lesson_chr_cmmn_cmmn-vi-idle-ac-001_lp_b",
    );
    expect(selectStand3DClip(TEMARI_CLIPS, true)?.name).toBe(
      "mot_all_chr_ttmr_idle-001_pose_b",
    );
  });
});

describe("directing her 3D pose during a call", () => {
  it("wraps the idle loop time and freezes body time under reduced motion", () => {
    let state = createStand3DPoseState();
    state = stepStand3DPose(state, CALM, 21.0, false, 20.0, true);
    expect(state.clipTime).toBeCloseTo(1.0, 5);

    state = stepStand3DPose(state, CALM, 0.5, true, 1 / 30, false);
    expect(state.clipTime).toBe(0);
  });

  it("moves her mouth while speaking and closes it completely once she stops", () => {
    const speaking: StandDirection = { ...CALM, speaking: true };
    let state = createStand3DPoseState();
    state = stepStand3DPose(state, speaking, 0.12, false, 20, true);
    expect(state.mouthOpen).toBeGreaterThan(0.15);

    for (let i = 0; i < 10; i++) {
      state = stepStand3DPose(state, CALM, 0.05, false, 20, true);
    }
    expect(state.mouthOpen).toBe(0);
  });

  it("blends facial expression weights toward her current mood and triggers each nod id once", () => {
    const happyNod: StandDirection = {
      mood: "happy",
      speaking: false,
      looking: true,
      nod: { kind: "yes", id: 1 },
    };
    let state = createStand3DPoseState();
    state = stepStand3DPose(state, happyNod, 0.15, false, 20, true);

    expect(state.shapeWeights["b_brow.brow_002"]).toBeGreaterThan(0);
    expect(state.shapeWeights["b_mouth.mouth_002"]).toBeGreaterThan(0);
    expect(state.gazeWeight).toBeGreaterThan(0);
    expect(Math.abs(state.headPitchDeg)).toBeGreaterThan(0.5);

    // Let the nod finish; keeping the same nod.id=1 must not replay it.
    for (let i = 0; i < 20; i++) {
      state = stepStand3DPose(state, happyNod, 0.05, false, 20, true);
    }
    expect(state.nodElapsed).toBeNull();

    // A new nod id triggers a shake ("no").
    const shake: StandDirection = { ...happyNod, nod: { kind: "no", id: 2 } };
    state = stepStand3DPose(state, shake, 0.12, false, 20, true);
    expect(Math.abs(state.headYawDeg)).toBeGreaterThan(0.5);
  });
});
