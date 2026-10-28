import * as THREE from "three";
import type {ActorLighting,Stand3DMaterialSource} from "./Stand3DMaterial";

export type ActorOutlineSettings={version:number;parameters:[number,number,number,number];depthBias:number};

// Native Default/Forward(Outline) VS271 and PS275. Parameters are an explicit
// portrait calibration; the original runtime global binding is not recovered.
export function createActorOutlineMaterial(source:Stand3DMaterialSource,lighting:ActorLighting,settings:ActorOutlineSettings):THREE.ShaderMaterial|null {
  const p=settings.parameters,r=source.rendering;
  if(settings.version!==1||p.length!==4||!p.every(Number.isFinite)||p[0]<0||p[1]<p[0]||p[1]>1||p[2]<0||p[3]<0||!Number.isFinite(settings.depthBias)||settings.depthBias<0||settings.depthBias>.001||r?.version!==1||[4,5].includes(r.scalars._ShaderType))return null;
  const color=r.colors._MultiplyOutlineColor,alpha=r.colors._MultiplyColor?.a??1;
  return new THREE.ShaderMaterial({
    name:source.name+':outline',side:THREE.BackSide,depthWrite:r.scalars._ZWrite!==0,toneMapped:false,
    uniforms:{actorLightColor:lighting.actorLightColor,actorBlink:lighting.actorBlink,actorType:{value:r.scalars._ShaderType},outlineParameters:{value:new THREE.Vector4(...p)},outlineDepthBias:{value:settings.depthBias},outlineMultiply:{value:new THREE.Vector3(color?.r??1,color?.g??1,color?.b??1)},outlineAlpha:{value:alpha}},
    vertexShader:`
      attribute vec3 actorOutlineNormal;
      attribute vec4 actorMask;
      uniform vec4 outlineParameters;
      uniform float outlineDepthBias;
      uniform vec3 actorLightColor;
      varying vec3 outlineColor;
      varying vec2 outlineUV;
      #include <common>
      #include <skinning_pars_vertex>
      void main(){
        vec4 high=floor(actorMask*15.9375+0.03125);
        vec4 low=actorMask*255.0-high*16.0;
        vec3 objectNormal=actorOutlineNormal;
        #include <skinbase_vertex>
        #include <skinnormal_vertex>
        #include <begin_vertex>
        #include <skinning_vertex>
        vec3 world=(modelMatrix*vec4(transformed,1.0)).xyz;
        float distanceMix=min(length(cameraPosition-world)*outlineParameters.z*outlineParameters.w,1.0);
        float width=mix(outlineParameters.x,outlineParameters.y,distanceMix)*0.01*(low.b/15.0);
        // Preserve authored tangent magnitude, including near-zero face entries.
        transformed+=objectNormal*width;
        #include <project_vertex>
        // D3D reversed [0,w] -> conventional GL [-w,w]. Native bias uses the
        // RAW high blue nibble, not its /15 normalized value.
        gl_Position.z+=2.0*high.b*outlineDepthBias;
        outlineColor=vec3(high.r,low.r,high.g)/15.0*min(actorLightColor,vec3(1.0));
        outlineUV=uv;
      }`,
    fragmentShader:`
      varying vec3 outlineColor;
      varying vec2 outlineUV;
      uniform vec3 outlineMultiply;
      uniform float outlineAlpha,actorType,actorBlink;
      void main(){
        // Match the forward pass's portrait eye-highlight cleanup at closure.
        if(actorType==6.0&&outlineUV.x>0.96875&&outlineUV.y>0.96875&&actorBlink>0.8)discard;
        gl_FragColor=vec4(outlineColor*outlineMultiply,outlineAlpha);
      }`,
  });
}
