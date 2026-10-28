export type ActorFaceClip = {
  sampleRate: number;
  times: number[];
  tracks: Array<{ shapeName?: string; shapeScale?: number; samples: number[][] }>;
};

const BLINK = "b_eye.eye_001";
const OPEN_MOUTH = "b_mouth.mouth_001";
const clamp = (n: number) => Math.max(0, Math.min(1, n));
const group = (name: string) => name.split(".")[0];

export function sampleActorFace(clip: ActorFaceClip | null, time: number): Record<string, number> {
  if (!clip?.times.length) return {};
  const frame = Math.max(0, Math.min(time * clip.sampleRate, clip.times.length - 1));
  const a = Math.floor(frame), b = Math.min(a + 1, clip.times.length - 1), f = frame - a;
  const weights: Record<string, number> = {};
  for (const track of clip.tracks) {
    if (!track.shapeName) continue; // The eight decal-fade tracks are not shapes.
    const left = track.samples[a]?.[0] ?? 0, right = track.samples[b]?.[0] ?? left;
    weights[track.shapeName] = clamp((left + (right - left) * f) * (track.shapeScale ?? 0.01));
  }
  return weights;
}

export function blendActorFace(
  native: Record<string, number>,
  mood: Record<string, number>,
  mouthOpen: number,
): Record<string, number> {
  const overrides: Record<string, number> = {};
  for (const [name, weight] of Object.entries(mood)) overrides[group(name)] = Math.max(overrides[group(name)] ?? 0, clamp(weight));
  const mouth = clamp(mouthOpen), blink = native[BLINK] ?? 0;
  const weights: Record<string, number> = {};
  for (const [name, weight] of Object.entries(native)) {
    const attenuation = name === BLINK ? 1 : 1 - (overrides[group(name)] ?? 0);
    weights[name] = weight * attenuation * (name.startsWith("b_mouth.") ? 1 - mouth : 1);
  }
  for (const [name, weight] of Object.entries(mood)) {
    const attenuation = name.startsWith("b_mouth.") ? 1 - mouth * 0.7
      : name.startsWith("b_eye.") && name !== BLINK ? 1 - blink : 1;
    weights[name] = clamp((weights[name] ?? 0) + weight * attenuation);
  }
  if (mouth > 0) weights[OPEN_MOUTH] = clamp((weights[OPEN_MOUTH] ?? 0) + mouth);
  return weights;
}
