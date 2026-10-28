import { describe, expect, it } from "vitest";
import { blendActorFace, sampleActorFace } from "./Stand3DFace";

describe("original face animation", () => {
  it("samples percent weights on the source time axis while excluding decal tracks", () => {
    const clip = { sampleRate: 30, times: [0, 1 / 30], tracks: [
      { shapeName: "b_eye.eye_001", shapeScale: 0.01, samples: [[0], [100]] },
      { shapeName: "b_brow.brow_003", shapeScale: 0.01, samples: [[50], [80]] },
      { samples: [[1], [1]] },
    ] };
    expect(sampleActorFace(clip, 1 / 60)).toEqual({ "b_eye.eye_001": 0.5, "b_brow.brow_003": 0.65 });
    expect(sampleActorFace(clip, 10)["b_eye.eye_001"]).toBe(1);
    expect(sampleActorFace(null, 0)).toEqual({});
  });

  it("keeps the authored neutral face and blink, giving speech and mood bounded priority", () => {
    const original = { "b_eye.eye_001": 1, "b_brow.brow_003": 0.8, "b_mouth.mouth_014": 0.7 };
    expect(blendActorFace(original, {}, 0)).toEqual(original);
    const expressive = blendActorFace(original, { "b_eye.eye_008": 0.65, "b_brow.brow_002": 0.75 }, 1);
    expect(expressive["b_eye.eye_001"]).toBe(1);
    expect(expressive["b_eye.eye_008"]).toBe(0);
    expect(expressive["b_brow.brow_003"]).toBeCloseTo(0.2);
    expect(expressive["b_mouth.mouth_014"]).toBe(0);
    expect(expressive["b_mouth.mouth_001"]).toBe(1);
  });
});
