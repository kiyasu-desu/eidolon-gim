import * as THREE from "three";

export type ActorColorLUT = {
  version: number;
  url: string;
  size: number;
  encoding: "rgba32f";
  domain: "logc";
  exposure: number;
};

// Original UberPost _3D_GRADING + _HDR_GRADING branch. The constants are from
// its DXBC, not a guessed GT curve. CPU settings must supply a verified LUT.
export const ACTOR_LUT_GLSL = `
  vec3 actorLUTCoordinate(vec3 color, float size, float exposure) {
    vec3 linearColor = clamp(color * exposure, 0.0, 100.0);
    vec3 encoded = min(log2(linearColor * 5.555556 + 0.047996) * 0.073500 + 0.386036, vec3(1.0));
    return encoded * ((size - 1.0) / size) + vec3(0.5 / size);
  }
`;

export function createActorColorLUT(source: ActorColorLUT, bytes: ArrayBuffer): THREE.Data3DTexture {
  const { size } = source;
  if (source.version !== 1 || source.encoding !== "rgba32f" || source.domain !== "logc" ||
    !Number.isInteger(size) || size < 4 || size > 64 || (size & (size - 1)) !== 0 ||
    !Number.isFinite(source.exposure) || source.exposure <= 0 || source.exposure > 64) throw new Error("Invalid actor color LUT");
  if (bytes.byteLength !== size ** 3 * 16) throw new Error("Truncated actor color LUT");
  const view = new DataView(bytes), values = new Uint16Array(size ** 3 * 4);
  for (let i = 0; i < values.length; i++) {
    const value = view.getFloat32(i * 4, true);
    if (!Number.isFinite(value) || value < 0 || value > 65504) throw new Error("Invalid actor color LUT texel");
    values[i] = THREE.DataUtils.toHalfFloat(value);
  }
  // D3D readback order is X fastest, then Y, then Z, matching WebGL 3D upload.
  const texture = new THREE.Data3DTexture(values, size, size, size);
  texture.type = THREE.HalfFloatType;
  texture.format = THREE.RGBAFormat;
  texture.colorSpace = THREE.LinearSRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.wrapR = THREE.ClampToEdgeWrapping;
  texture.generateMipmaps = false;
  texture.unpackAlignment = 1;
  texture.needsUpdate = true;
  return texture;
}

export async function loadActorColorLUT(source: ActorColorLUT | undefined, assetUrl: (path: string) => string) {
  if (source?.version !== 1) return null;
  const response = await fetch(assetUrl(source.url));
  if (!response.ok) throw new Error(`Missing actor color LUT: ${source.url}`);
  return createActorColorLUT(source, await response.arrayBuffer());
}
