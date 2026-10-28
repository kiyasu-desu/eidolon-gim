import * as THREE from "three";

export type ActorCubeSource = { url: string; width: number; mipCount: number; encoding: "rgb9e5" };
export type ActorEnvironment = {
  version: number;
  body: ActorCubeSource;
  eye: ActorCubeSource;
  bodyColor: [number, number, number];
  eyeColor: [number, number, number];
  lighting?: {
    lightColor: [number, number, number];
    shadeMultiplyColor: [number, number, number];
    shadeAdditiveColor: [number, number, number];
    rampOffset?:number;
  };
};

/** Original RGB9E5 shared exponent, without display encoding or HDR clipping. */
export function unpackRGB9E5(word: number): [number, number, number] {
  const scale = 2 ** ((word >>> 27) - 24);
  return [(word & 511) * scale, ((word >>> 9) & 511) * scale, ((word >>> 18) & 511) * scale];
}

export function createActorCube(source: ActorCubeSource, bytes: ArrayBuffer): THREE.CubeTexture<THREE.DataTexture> {
  const { width, mipCount } = source;
  if (source.encoding !== "rgb9e5" || !Number.isInteger(width) || width < 1 || width > 512 ||
    (width & (width - 1)) !== 0 || mipCount !== Math.log2(width) + 1) throw new Error("Invalid actor reflection layout");
  const sizes = Array.from({ length: mipCount }, (_, i) => Math.max(1, width >> i));
  const faceBytes = sizes.reduce((sum, size) => sum + size * size * 4, 0);
  if (bytes.byteLength !== faceBytes * 6) throw new Error("Truncated actor reflection data");
  const input = new DataView(bytes);
  const levels: THREE.DataTexture[][] = Array.from({ length: mipCount }, () => []);
  let offset = 0;
  // Unity serialized order: +X,-X,+Y,-Y,+Z,-Z, each face's full mip chain.
  for (let face = 0; face < 6; face++) for (let mip = 0; mip < mipCount; mip++) {
    const size = sizes[mip], data = new Uint16Array(size * size * 4);
    for (let pixel = 0; pixel < size * size; pixel++, offset += 4) {
      const rgb = unpackRGB9E5(input.getUint32(offset, true));
      for (let c = 0; c < 3; c++) data[pixel * 4 + c] = THREE.DataUtils.toHalfFloat(rgb[c]);
      data[pixel * 4 + 3] = 0x3c00;
    }
    levels[mip].push(new THREE.DataTexture(data, size, size, THREE.RGBAFormat, THREE.HalfFloatType));
  }
  const cube = new THREE.CubeTexture<THREE.DataTexture>(levels[0]);
  cube.type = THREE.HalfFloatType;
  cube.format = THREE.RGBAFormat;
  cube.colorSpace = THREE.LinearSRGBColorSpace;
  cube.generateMipmaps = false;
  cube.minFilter = THREE.LinearMipmapLinearFilter;
  cube.magFilter = THREE.LinearFilter;
  cube.mipmaps = levels.slice(1).map(image => new THREE.CubeTexture(image));
  cube.needsUpdate = true;
  return cube;
}

export async function loadActorEnvironment(source: ActorEnvironment | undefined, assetUrl: (path: string) => string) {
  if (source?.version !== 1) return null;
  const results = await Promise.allSettled([source.body, source.eye].map(async spec => {
    const response = await fetch(assetUrl(spec.url));
    if (!response.ok) throw new Error(`Missing actor reflection: ${spec.url}`);
    return createActorCube(spec, await response.arrayBuffer());
  }));
  const failure = results.find(result => result.status === "rejected");
  if (failure?.status === "rejected") {
    for (const result of results) if (result.status === "fulfilled") result.value.dispose();
    throw failure.reason;
  }
  const cubes = results.flatMap(result => result.status === "fulfilled" ? [result.value] : []);
  return { body: cubes[0], eye: cubes[1], textures: cubes };
}
