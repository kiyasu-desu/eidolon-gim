import { afterEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import { createActorLighting, loadActorMaterials, type Stand3DMaterialSource } from "./Stand3DMaterial";

function source(queue: number): Stand3DMaterialSource {
  const texture = { url: "textures/base.png", srgb: true, filter: 1, aniso: 1, wrapU: 1, wrapV: 1, scale: { x: 1, y: 1 }, offset: { x: 0, y: 0 } };
  return { name: "test", baseMap: texture.url, scale: texture.scale, offset: texture.offset,
    rendering: { version: 1, queue, scalars: { _ShaderType: 8, _ZWrite: 1 }, colors: {}, keywords: [], maps: { _BaseMap: texture } } };
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("actor material loading", () => {
  it("applies a source lighting profile and resets it when switching to a legacy outfit",async()=>{
    vi.spyOn(THREE.TextureLoader.prototype,"loadAsync").mockImplementation(async()=>new THREE.Texture<HTMLImageElement>());
    vi.stubGlobal("fetch",vi.fn(async()=>new Response(new ArrayBuffer(24))));
    const lighting=createActorLighting(),cube={url:"reflection.bin",width:1,mipCount:1,encoding:"rgb9e5" as const};
    const loaded=await loadActorMaterials({face:source(2000)},x=>x,lighting,true,{
      version:1,body:cube,eye:cube,bodyColor:[2,2,2],eyeColor:[1,1,1],
      lighting:{lightColor:[.9,1,.8],shadeMultiplyColor:[.79,.63,.617],shadeAdditiveColor:[.01,.02,0],rampOffset:.3},
    });
    expect(lighting.actorEnvironmentEnabled.value).toBe(true);
    expect(lighting.actorShadeMultiplyColor.value.toArray()).toEqual([.79,.63,.617]);
    expect(lighting.actorLightColor.value.toArray()).toEqual([.9,1,.8]);
    expect(lighting.actorRampOffset.value).toBe(.3);
    loaded.materials.forEach(m=>m.dispose());loaded.textures.forEach(t=>t.dispose());
    const legacy=await loadActorMaterials({face:source(2000)},x=>x,lighting);
    expect(lighting.actorEnvironmentEnabled.value).toBe(false);
    expect(lighting.actorBodyReflection.value).toBe(null);
    expect(lighting.actorLightColor.value.toArray()).toEqual([1,1,1]);
    expect(lighting.actorShadeMultiplyColor.value.toArray()).toEqual([1,1,1]);
    expect(lighting.actorShadeAdditiveColor.value.toArray()).toEqual([0,0,0]);
    expect(lighting.actorRampOffset.value).toBe(0);
    legacy.materials.forEach(m=>m.dispose());legacy.textures.forEach(t=>t.dispose());
  });
  it("shares texture ownership and preserves pass order independently of fetch completion", async () => {
    const base = new THREE.Texture<HTMLImageElement>();
    const load = vi.spyOn(THREE.TextureLoader.prototype, "loadAsync").mockResolvedValue(base);
    const lighting = createActorLighting();
    const result = await loadActorMaterials({ hair: source(2301), face: source(2000) }, (url) => url, lighting);
    expect(load).toHaveBeenCalledTimes(1);
    expect(result.materials).toEqual([result.map.face, result.map.hair]);
    for (const material of result.materials) {
      if (!(material instanceof THREE.ShaderMaterial)) throw new Error("Expected actor shader");
      expect(material.uniforms.baseMap.value).toBe(base);
      expect(material.uniforms.actorLight).toBe(lighting.actorLight);
    }
    expect(base.colorSpace).toBe(THREE.SRGBColorSpace);
    expect(result.textures.filter((texture) => texture === base)).toHaveLength(1);
    result.materials.forEach((material) => material.dispose());
    result.textures.forEach((texture) => texture.dispose());
  });

  it("keeps Def data linear while decoding color maps, with explicit Gamma-reference compatibility",async()=>{
    const base=new THREE.Texture<HTMLImageElement>(),def=new THREE.Texture<HTMLImageElement>();
    vi.spyOn(THREE.TextureLoader.prototype,"loadAsync").mockImplementation(url=>Promise.resolve(url.includes('def')?def:base));
    const s=source(2000);s.rendering!.maps._DefMap={...s.rendering!.maps._BaseMap,url:'textures/def.png',srgb:false};
    const loaded=await loadActorMaterials({face:s},x=>x,createActorLighting());
    expect(base.colorSpace).toBe(THREE.SRGBColorSpace);expect(def.colorSpace).toBe(THREE.NoColorSpace);
    loaded.materials.forEach(m=>m.dispose());loaded.textures.forEach(t=>t.dispose());
    const reference=await loadActorMaterials({face:s},x=>x,createActorLighting(),false);
    expect(base.colorSpace).toBe(THREE.NoColorSpace);expect(def.colorSpace).toBe(THREE.NoColorSpace);
    reference.materials.forEach(m=>m.dispose());reference.textures.forEach(t=>t.dispose());
  });

  it("waits for late texture successes before releasing resources after a failed load", async () => {
    const late = Promise.withResolvers<THREE.Texture<HTMLImageElement>>();
    const texture = new THREE.Texture<HTMLImageElement>();
    const dispose = vi.spyOn(texture, "dispose");
    vi.spyOn(THREE.TextureLoader.prototype, "loadAsync").mockImplementation((url) => url.includes("missing")
      ? Promise.reject(new Error("missing map")) : late.promise);
    const broken = source(2000);
    broken.rendering!.maps._DefMap = { ...broken.rendering!.maps._BaseMap, url: "textures/missing.png" };
    const loading = loadActorMaterials({ broken }, (url) => url, createActorLighting());
    const rejected = expect(loading).rejects.toThrow("missing map");
    await Promise.resolve();
    expect(dispose).not.toHaveBeenCalled();
    late.resolve(texture);
    await rejected;
    expect(dispose).toHaveBeenCalledTimes(1);
  });
});
