import * as THREE from "three";
import { loadActorEnvironment, type ActorEnvironment } from "./Stand3DEnvironment";

type XY = { x: number; y: number };
type RGBA = { r: number; g: number; b: number; a: number };
export type ActorTexture = {
  url: string;
  srgb: boolean;
  filter: number;
  aniso: number;
  wrapU: number;
  wrapV: number;
  scale: XY;
  offset: XY;
};
export type ActorMaterial = {
  version: number;
  queue: number;
  scalars: Record<string, number>;
  colors: Record<string, RGBA>;
  keywords: string[];
  maps: Record<string, ActorTexture>;
};
export type Stand3DMaterialSource = {
  name: string;
  baseMap: string;
  scale: XY;
  offset: XY;
  rendering?: ActorMaterial;
};
export type ActorRimSettings={version:number;direction:[number,number,number];color:[number,number,number];power:number;baseColorRatio:number;strength:number};

export function createActorLighting() {
  // Portrait calibration, not recovered original scene globals. Original player
  // requests Linear; a final presentation pass encodes once to display sRGB.
  return {
    actorLight: { value: new THREE.Vector3(-0.5, 0.6, 1).normalize() },
    actorShadowStrength: { value: 1 },
    actorRampOffset: { value: 0 },
    actorHeadRightView: { value: new THREE.Vector3(1, 0, 0) },
    // Formula recovered; the game's matrix convention is still unverified.
    // Keep the reconstructed matrix experiment opt-in during calibration.
    actorFaceReflectionStrength: { value: 0 },
    actorSpecularStrength: { value: 0.35 },
    actorHighlightStrength: { value: 1 },
    actorRampAddStrength: { value: 0.3 },
    actorPortraitTone: { value: true },
    actorBlink: { value: 0 },
    actorRimDirection:{value:new THREE.Vector3(0,0,1)},
    actorRimColor:{value:new THREE.Vector4(1,1,1,0)},
    actorRimPower:{value:32},
    actorRimStrength:{value:0},
    actorSelfShadowEnabled:{value:false},
    actorSelfShadowMap:{value:null as THREE.DepthTexture|null},
    actorSelfShadowMatrix:{value:new THREE.Matrix4()},
    actorSelfShadowTexel:{value:new THREE.Vector2(1/1024,1/1024)},
    actorSelfShadowBias:{value:.0004},
    actorSelfShadowStrength:{value:.6},
    actorEnvironmentEnabled: { value: false },
    actorBodyReflection: { value: null as THREE.CubeTexture | null },
    actorEyeReflection: { value: null as THREE.CubeTexture | null },
    actorBodyReflectionColor: { value: new THREE.Vector3(1, 1, 1) },
    actorEyeReflectionColor: { value: new THREE.Vector3(1, 1, 1) },
    actorLightColor: { value: new THREE.Vector3(1, 1, 1) },
    actorShadeMultiplyColor: { value: new THREE.Vector3(1, 1, 1) },
    actorShadeAdditiveColor: { value: new THREE.Vector3(0, 0, 0) },
  };
}
export type ActorLighting = ReturnType<typeof createActorLighting>;
export function configureActorRim(lighting:ActorLighting,settings?:ActorRimSettings):void {
  lighting.actorRimStrength.value=0;
  lighting.actorRimDirection.value.set(0,0,1);lighting.actorRimColor.value.set(1,1,1,0);lighting.actorRimPower.value=32;
  if(settings?.version!==1||settings.direction.length!==3||!settings.direction.every(Number.isFinite)||new THREE.Vector3(...settings.direction).lengthSq()<1e-8||settings.color.length!==3||!settings.color.every(v=>Number.isFinite(v)&&v>=0&&v<=65504)||!Number.isFinite(settings.power)||settings.power<.001||settings.power>128||!Number.isFinite(settings.baseColorRatio)||settings.baseColorRatio<0||settings.baseColorRatio>1||!Number.isFinite(settings.strength)||settings.strength<0||settings.strength>1)return;
  lighting.actorRimDirection.value.fromArray(settings.direction).normalize();lighting.actorRimColor.value.set(...settings.color,settings.baseColorRatio);lighting.actorRimPower.value=settings.power;lighting.actorRimStrength.value=settings.strength;
}

export function actorMaterialQueue(source: Stand3DMaterialSource): number {
  return source.rendering?.version === 1 && source.rendering.queue >= 0 ? source.rendering.queue : 2000;
}

// Equations checked against the actual Forward DXBC and native GPU capture.
// See .scratch/unity-reference/web-equations.md. This is an independent forward
// implementation, without the game's deferred passes, probes, LUT or stencil.
export function createActorMaterial(
  source: Stand3DMaterialSource,
  maps: Record<string, THREE.Texture>,
  lighting: ActorLighting,
  fallback: THREE.Texture,
): THREE.Material {
  const data = source.rendering;
  if (data?.version !== 1) {
    const glint = source.name === "m_ehl";
    return new THREE.MeshBasicMaterial({ map: maps._BaseMap, side: THREE.DoubleSide,
      transparent: glint, depthWrite: !glint, alphaTest: glint ? 0.01 : 0,
      blending: glint ? THREE.AdditiveBlending : THREE.NormalBlending });
  }
  const p = data.scalars;
  const c = data.colors;
  const vector = (value: RGBA | undefined, defaults: [number, number, number, number]) =>
    new THREE.Vector4(value?.r ?? defaults[0], value?.g ?? defaults[1], value?.b ?? defaults[2], value?.a ?? defaults[3]);
  const base = data.maps._BaseMap;
  const mat = new THREE.ShaderMaterial({
    name: source.name,
    toneMapped: false,
    side: p._Cull === 2 ? THREE.FrontSide : THREE.DoubleSide,
    depthWrite: p._ZWrite !== 0,
    uniforms: {
      ...lighting,
      baseMap: { value: maps._BaseMap },
      shadeMap: { value: maps._ShadeMap ?? fallback },
      defMap: { value: maps._DefMap ?? fallback },
      rampMap: { value: maps._RampMap ?? fallback },
      highlightMap: { value: maps._HighlightMap ?? maps._BaseMap },
      rampAddMap: { value: maps._RampAddMap ?? fallback },
      actorType: { value: p._ShaderType ?? 0 },
      baseColor: { value: vector(c._BaseColor, [1, 1, 1, 1]) },
      defValue: { value: vector(c._DefValue, [0.5, 0, 1, 0]) },
      threshold: { value: vector(c._SpecularThreshold, [0.6, 0.05, 0, 0]) },
      rampAddColor: { value: vector(c._RampAddColor, [1, 1, 1, 1]) },
      uvScaleOffset: { value: new THREE.Vector4(base?.scale.x ?? 1, base?.scale.y ?? 1, base?.offset.x ?? 0, base?.offset.y ?? 0) },
      hasDef: { value: maps._DefMap !== undefined && !data.keywords.includes("_DEFMAP_OFF") },
      hasShade: { value: maps._ShadeMap !== undefined },
      hasRampAdd: { value: maps._RampAddMap !== undefined && data.keywords.includes("_RAMPADD_ON") },
      alphaClip: { value: data.keywords.includes("_ALPHATEST_ON") },
      premultiply: { value: data.keywords.includes("_ALPHAPREMULTIPLY_ON") },
      hasBodyReflection: { value: data.keywords.includes("_USE_REFLECTION_TEXTURE") },
      hasEyeReflection: { value: data.keywords.includes("_USE_EYE_REFLECTION_TEXTURE") },
    },
    vertexShader: `
      varying vec2 actorUV;
      varying vec3 actorNormal;
      varying vec3 actorView;
      varying vec3 actorWorldPosition;
      varying float actorRampID;
      varying float actorRimMask;
      attribute vec4 actorMask;
      uniform vec4 uvScaleOffset;
      #include <common>
      #include <skinning_pars_vertex>
      void main() {
        actorUV = uv * uvScaleOffset.xy + uvScaleOffset.zw;
        float highGreen = floor(actorMask.g * 15.9375 + 0.03125);
        actorRampID = (actorMask.g * 255.0 - highGreen * 16.0) / 15.0;
        actorRimMask=floor(actorMask.a*15.9375+0.03125)/15.0;
        #include <beginnormal_vertex>
        #include <skinbase_vertex>
        #include <skinnormal_vertex>
        #include <defaultnormal_vertex>
        // Original Forward VS normalizes after skinning, before interpolation.
        // Fragment normalization alone changes interpolation when joint blends
        // leave neighboring vertex normals with different lengths.
        actorNormal = normalize(transformedNormal);
        #include <begin_vertex>
        #include <skinning_vertex>
        #include <project_vertex>
        actorView = -mvPosition.xyz;
        actorWorldPosition=(modelMatrix*vec4(transformed,1.0)).xyz;
      }
    `,
    fragmentShader: `
      varying vec2 actorUV;
      varying vec3 actorNormal;
      varying vec3 actorView;
      varying vec3 actorWorldPosition;
      varying float actorRampID;
      varying float actorRimMask;
      uniform sampler2D baseMap, shadeMap, defMap, rampMap, highlightMap, rampAddMap;
      uniform samplerCube actorBodyReflection, actorEyeReflection;
      uniform vec3 actorBodyReflectionColor, actorEyeReflectionColor;
      uniform vec3 actorLightColor, actorShadeMultiplyColor, actorShadeAdditiveColor;
      uniform bool actorEnvironmentEnabled, hasBodyReflection, hasEyeReflection;
      uniform bool actorSelfShadowEnabled;
      uniform sampler2D actorSelfShadowMap;
      uniform mat4 actorSelfShadowMatrix;
      uniform vec2 actorSelfShadowTexel;
      uniform float actorSelfShadowBias,actorSelfShadowStrength;
      uniform vec3 actorLight, actorHeadRightView;
      uniform vec3 actorRimDirection;
      uniform vec4 actorRimColor;
      uniform float actorRimPower,actorRimStrength;
      uniform float actorType, actorShadowStrength, actorRampOffset, actorFaceReflectionStrength, actorSpecularStrength, actorHighlightStrength, actorRampAddStrength, actorBlink;
      uniform vec4 baseColor, defValue, threshold, rampAddColor;
      uniform bool hasDef, hasShade, hasRampAdd, alphaClip, premultiply, actorPortraitTone;
      float sat(float v) { return clamp(v, 0.0, 1.0); }
      float actorOcclusion(){
        if(!actorSelfShadowEnabled)return 1.0;
        vec4 projected=actorSelfShadowMatrix*vec4(actorWorldPosition,1.0);vec3 p=projected.xyz/projected.w;
        if(any(lessThan(p,vec3(0.0)))||any(greaterThan(p,vec3(1.0))))return 1.0;
        vec3 dx=dFdx(p),dy=dFdy(p);float determinant=dx.x*dy.y-dx.y*dy.x;
        vec2 slope=abs(determinant)>1e-10?vec2(dx.z*dy.y-dy.z*dx.y,dy.z*dx.x-dx.z*dy.x)/determinant:vec2(0.0);
        float receiverBias=min(dot(abs(slope),actorSelfShadowTexel)*0.5,0.003);
        float lit=0.0;
        for(int x=-1;x<=1;x++)for(int y=-1;y<=1;y++){
          vec2 offset=vec2(float(x),float(y))*actorSelfShadowTexel;
          lit+=step(p.z+dot(slope,offset)-actorSelfShadowBias-receiverBias,texture2D(actorSelfShadowMap,p.xy+offset).r);
        }
        return mix(1.0,lit/9.0,actorSelfShadowStrength);
      }
      void main() {
        vec4 base = texture2D(baseMap, actorUV);
        if (alphaClip && base.a < 0.33) discard;
        // Portrait correction for the known full-close morph. The native actor
        // highlight controller is not available; hide only its dedicated atlas
        // patch near closure, while the separate additive glint fades smoothly.
        if (actorType == 6.0 && actorUV.x > 0.96875 && actorUV.y > 0.96875 && actorBlink > 0.8) discard;
        if (actorType == 5.0) {
          gl_FragColor = vec4(base.rgb * baseColor.rgb * (1.0 - actorBlink), base.a);
          return;
        }
        vec3 N = normalize(actorNormal) * (gl_FrontFacing ? 1.0 : -1.0);
        vec3 V = normalize(actorView);
        // The model is X-mirrored on import. This basis preserves the source
        // MatCap handedness; the native cross products are not normalized.
        vec3 side = cross(vec3(0.0, 1.0, 0.0), V);
        vec3 up = cross(V, side);
        vec3 M = vec3(dot(N, side), dot(N, up), dot(N, V));
        vec3 L = normalize(actorLight);
        vec3 H = normalize(L + vec3(0.0, 0.0, 1.0));
        vec4 def = hasDef ? texture2D(defMap, actorUV) : defValue;
        vec4 shade = hasShade ? texture2D(shadeMap, actorUV) : vec4(base.rgb, 0.0);
        // Keep authored facial lighting. Face skin casts onto the neck/body,
        // while eye/face subpasses do not receive this portrait shadow layer.
        float selfShadow=(actorType==0.0||actorType==1.0)?actorOcclusion():1.0;
        float intensity = min(def.a,selfShadow);
        if (actorType == 8.0) {
          float signal = pow(sat(dot(M, H)), 4.0);
          float bright = threshold.y < 0.00001 ? step(threshold.x, signal)
            : smoothstep(threshold.x - threshold.y, threshold.x + threshold.y, signal);
          bool prop = actorUV.x > 0.75 && actorUV.y > 0.75;
          base.rgb = mix(base.rgb, texture2D(highlightMap, actorUV).rgb,
            prop ? 0.0 : bright * intensity * actorHighlightStrength);
          if (!prop) intensity = 0.0;
        }
        vec4 add = hasRampAdd ? texture2D(rampAddMap, vec2(sat(def.r * 2.0 - 1.0 + M.z), actorRampID)) : vec4(0.0);
        vec3 addColor = add.rgb * rampAddColor.rgb * actorRampAddStrength;
        base.rgb += addColor * (1.0 - add.a);
        shade.rgb += addColor * (1.0 - add.a);
        // Native _MatCapParam.x offsets the ramp input. Expose it separately
        // from shadow amplitude so calibration can move the cel boundary.
        float lighting = sat(dot(M, L) * 0.5 + def.r - 0.5 * actorRampOffset);
        if (actorType == 9.0 && actorFaceReflectionStrength > 0.0) {
          // Original Forward blends max(base, reflected-head lighting) by Def.B.
          // Reconstruct the head-local X-plane reflection in view coordinates.
          // The game's exact matrix construction/update order is not recovered.
          vec3 axis = normalize(actorHeadRightView);
          vec3 reflected = N - 2.0 * axis * dot(axis, N);
          vec3 faceMat = vec3(dot(reflected, side), dot(reflected, up), dot(reflected, V));
          float faceLighting = sat(dot(faceMat, L) * 0.5 + def.r - 0.5 * actorRampOffset);
          lighting = mix(lighting, max(lighting, faceLighting), def.b * actorFaceReflectionStrength);
        }
        vec4 ramp = texture2D(rampMap, vec2(lighting, 0.0));
        // Blend authored lit/shadow ramps by filtered coverage. Applying the
        // filtered depth to the ramp coordinate would quantize it a second time.
        if(selfShadow<1.0)ramp=mix(texture2D(rampMap,vec2(0.0)),ramp,selfShadow);
        vec3 painted = mix(base.rgb, shade.rgb * actorShadeMultiplyColor, ramp.a * actorShadowStrength);
        vec3 skinRamp = mix(ramp.rgb, ramp.rgb * actorShadeMultiplyColor, ramp.a);
        vec3 skin = base.rgb * mix(vec3(1.0), skinRamp, actorShadowStrength);
        painted = mix(painted, skin, shade.a) * baseColor.rgb;
        bool eye = actorType == 4.0;
        float metallic = actorType == 9.0 ? 0.0 : def.b;
        float smoothness = min(def.g, 1.0);
        float roughness = max(pow(1.0 - smoothness, 2.0), 0.0078125);
        float r2 = roughness * roughness;
        float nh = sat(dot(M, H));
        float lh = sat(dot(L, H));
        float d = nh * nh * (r2 - 1.0) + 1.00001;
        float direct = r2 / (d * d * max(0.1, lh * lh) * (4.0 * roughness + 2.0));
        direct *= sat(dot(M, L));
        float reflectivity = eye ? 0.04 : 1.0 - 0.96 * (1.0 - metallic);
        vec3 f0 = eye ? painted : mix(vec3(0.04), painted, metallic);
        float grazing = sat(smoothness + reflectivity);
        vec3 fresnel = mix(f0, vec3(grazing), pow(1.0 - sat(M.z), 4.0)) / (r2 + 1.0);
        vec3 diffuse = painted * 0.96 * (eye ? 1.0 : 1.0 - metallic);
        vec3 indirect = vec3(0.0);
        if (actorEnvironmentEnabled && (hasBodyReflection || hasEyeReflection)) {
          vec3 reflected = reflect(-V, N);
          // View -> world, then undo the model's single X-mirror to sample the
          // original Unity Cube. Sampling/upload orientation has a GPU fixture.
          vec3 worldReflection = vec3(dot(viewMatrix[0].xyz, reflected), dot(viewMatrix[1].xyz, reflected), dot(viewMatrix[2].xyz, reflected));
          worldReflection.x = -worldReflection.x;
          float perceptual = 1.0 - smoothness;
          float lod = perceptual * (1.7 - 0.7 * perceptual) * 6.0;
          indirect = hasEyeReflection ? textureCubeLodEXT(actorEyeReflection, worldReflection, lod).rgb * actorEyeReflectionColor
            : textureCubeLodEXT(actorBodyReflection, worldReflection, lod).rgb * actorBodyReflectionColor;
        }
        vec3 specular = fresnel * (direct + indirect) * intensity * actorSpecularStrength;
        if (actorType == 6.0 && actorUV.x > 0.96875 && actorUV.y > 0.96875) specular += painted * 2.0;
        specular = mix(specular, specular * addColor, add.a);
        // The native isolated reference lacks the game's exposure/LUT stage.
        // Compress portrait highlights instead of letting raw HDR clip white,
        // with softer skin and a larger range for metallic accessories.
        if (actorPortraitTone && !eye) {
          float peak = max(specular.r, max(specular.g, specular.b));
          float ceiling = mix(mix(0.25, 0.8, metallic), 0.08, shade.a);
          specular *= ceiling / (ceiling + peak);
        }
        // Original Forward PS125: min(2*Def.R,1) times high-alpha nibble.
        float rimSignal=pow(sat(1.0-dot(N,normalize(actorRimDirection))),actorRimPower);
        vec3 rim=mix(vec3(1.0),painted,actorRimColor.a)*actorRimColor.rgb*rimSignal*min(2.0*def.r,1.0)*actorRimMask*actorRimStrength;
        vec3 result = (diffuse + specular) * actorLightColor + rim + ramp.a * actorShadeAdditiveColor;
        float alpha = eye ? base.a : 1.0;
        if (premultiply) result *= alpha;
        // Scene-linear output. The whole actor is composited in a linear render
        // target and display-encoded once, after eye and additive passes.
        gl_FragColor = vec4(result, alpha);
      }
    `,
  });
  if (p._DstBlend === 1 || p._DstBlend === 10) {
    // Keep the opaque queue for source-ordered subpasses; custom blending still
    // applies. Glints add RGB while preserving the canvas coverage underneath.
    mat.blending = THREE.CustomBlending;
    mat.blendSrc = THREE.OneFactor;
    mat.blendDst = p._DstBlend === 1 ? THREE.OneFactor : THREE.OneMinusSrcAlphaFactor;
    mat.blendSrcAlpha = p._DstBlend === 1 ? THREE.ZeroFactor : THREE.OneFactor;
    mat.blendDstAlpha = p._DstBlend === 1 ? THREE.OneFactor : THREE.OneMinusSrcAlphaFactor;
  }
  return mat;
}

export async function loadActorMaterials(
  sources: Record<string, Stand3DMaterialSource>,
  assetUrl: (path: string) => string,
  lighting: ActorLighting,
  linearWorkflow = true,
  environment?: ActorEnvironment,
) {
  const textures: THREE.Texture[] = [];
  const materials: THREE.Material[] = [];
  const map: Record<string, THREE.Material> = {};
  const loader = new THREE.TextureLoader();
  const cache = new Map<string, Promise<THREE.Texture>>();
  const fallback = new THREE.DataTexture(new Uint8Array([255, 255, 255, 0]), 1, 1);
  fallback.needsUpdate = true;
  textures.push(fallback);
  const load = (spec: ActorTexture, legacy: boolean) => {
    const key = JSON.stringify([spec.url, legacy, linearWorkflow, spec.filter, spec.aniso, spec.wrapU, spec.wrapV, spec.scale, spec.offset]);
    let pending = cache.get(key);
    if (!pending) {
      pending = loader.loadAsync(assetUrl(spec.url)).then((tex) => {
        tex.colorSpace = legacy || (linearWorkflow && spec.srgb) ? THREE.SRGBColorSpace : THREE.NoColorSpace;
        const wrap = (v: number) => v === 0 ? THREE.RepeatWrapping : v === 2 ? THREE.MirroredRepeatWrapping : THREE.ClampToEdgeWrapping;
        tex.wrapS = wrap(spec.wrapU); tex.wrapT = wrap(spec.wrapV);
        tex.anisotropy = Math.min(4, Math.max(1, spec.aniso));
        tex.magFilter = spec.filter === 0 ? THREE.NearestFilter : THREE.LinearFilter;
        tex.minFilter = spec.filter === 0 ? THREE.NearestMipmapNearestFilter : spec.filter === 2 ? THREE.LinearMipmapLinearFilter : THREE.LinearMipmapNearestFilter;
        tex.repeat.set(spec.scale.x, spec.scale.y); tex.offset.set(spec.offset.x, spec.offset.y);
        textures.push(tex);
        return tex;
      });
      cache.set(key, pending);
    }
    return pending;
  };
  // Allocate materials in source queue order, after all parallel texture loads.
  // Opaque Three render lists sort subpasses by material id, not group order.
  const entries = Object.entries(sources).sort(([, a], [, b]) => actorMaterialQueue(a) - actorMaterialQueue(b));
  const loaded = await Promise.allSettled(entries.map(async ([key, source]) => {
    const maps: Record<string, THREE.Texture> = {};
    if (source.rendering?.version === 1) {
      const slots = source.rendering.scalars._ShaderType === 5 ? new Set(["_BaseMap"])
        : new Set(["_BaseMap", "_ShadeMap", "_DefMap", "_RampMap",
          ...(source.rendering.scalars._ShaderType === 8 ? ["_HighlightMap"] : []),
          ...(source.rendering.keywords.includes("_RAMPADD_ON") ? ["_RampAddMap"] : [])]);
      await Promise.all(Object.entries(source.rendering.maps).filter(([slot]) => slots.has(slot))
        .map(async ([slot, spec]) => { maps[slot] = await load(spec, false); }));
    } else {
      maps._BaseMap = await load({ url: source.baseMap, srgb: true, filter: 1, aniso: 4, wrapU: 0, wrapV: 0, scale: source.scale, offset: source.offset }, true);
    }
    return { key, source, maps };
  }));
  // A failed material's other texture loads may still be pending. Settle the
  // cache before releasing ownership so late successes cannot leak textures.
  await Promise.allSettled(cache.values());
  try {
    const reflections = await loadActorEnvironment(environment, assetUrl);
    lighting.actorEnvironmentEnabled.value = reflections !== null;
    lighting.actorBodyReflection.value = reflections?.body ?? null;
    lighting.actorEyeReflection.value = reflections?.eye ?? null;
    lighting.actorLightColor.value.set(1, 1, 1);
    lighting.actorShadeMultiplyColor.value.set(1, 1, 1);
    lighting.actorShadeAdditiveColor.value.set(0, 0, 0);
    lighting.actorRampOffset.value=0;
    if (reflections && environment) {
      textures.push(...reflections.textures);
      lighting.actorBodyReflectionColor.value.fromArray(environment.bodyColor);
      lighting.actorEyeReflectionColor.value.fromArray(environment.eyeColor);
      if (environment.lighting) {
        lighting.actorLightColor.value.fromArray(environment.lighting.lightColor);
        lighting.actorShadeMultiplyColor.value.fromArray(environment.lighting.shadeMultiplyColor);
        lighting.actorShadeAdditiveColor.value.fromArray(environment.lighting.shadeAdditiveColor);
        const offset=environment.lighting.rampOffset;
        if(offset!==undefined&&Number.isFinite(offset)&&Math.abs(offset)<=1)lighting.actorRampOffset.value=offset;
      }
    }
    for (const result of loaded) {
      if (result.status === "rejected") throw result.reason;
      const { key, source, maps } = result.value;
      if (!maps._BaseMap) throw new Error(`Missing actor base map: ${source.name}`);
      const material = createActorMaterial(source, maps, lighting, fallback);
      materials.push(material); map[key] = material;
    }
    return { textures, materials, map };
  } catch (error) {
    materials.forEach((material) => material.dispose());
    textures.forEach((texture) => texture.dispose());
    throw error;
  }
}
