import * as THREE from "three";
import type {ActorLighting} from "./Stand3DMaterial";

export type ActorShadowSettings={version:number;resolution:number;extent:number;bias:number;strength:number};
export function validActorShadowSettings(s:ActorShadowSettings|undefined):s is ActorShadowSettings {
  return s?.version===1&&Number.isInteger(s.resolution)&&s.resolution>=64&&s.resolution<=2048&&(s.resolution&(s.resolution-1))===0&&Number.isFinite(s.extent)&&s.extent>0&&s.extent<=4&&Number.isFinite(s.bias)&&s.bias>=0&&s.bias<=.01&&Number.isFinite(s.strength)&&s.strength>=0&&s.strength<=1;
}

// Actor-only depth projection. Keep facial/hair receiving on their authored
// ramps; the portrait layer shades body/props. This is not the native atlas.
export class Stand3DActorShadow {
  private target:THREE.WebGLRenderTarget;
  private camera:THREE.OrthographicCamera;
  private materials=new Map<THREE.Material,THREE.Material>();
  private disabled=new THREE.MeshBasicMaterial();
  private disposed=false;
  enabled=true;
  failure:string|null=null;
  constructor(readonly settings:ActorShadowSettings,private lighting:ActorLighting){
    const size=settings.resolution;
    this.disabled.visible=false;
    this.target=new THREE.WebGLRenderTarget(size,size,{depthBuffer:true});
    this.target.depthTexture=new THREE.DepthTexture(size,size,THREE.UnsignedIntType);
    this.camera=new THREE.OrthographicCamera(-settings.extent,settings.extent,settings.extent,-settings.extent,.1,6);
    lighting.actorSelfShadowMap.value=this.target.depthTexture;
    lighting.actorSelfShadowTexel.value.set(1/size,1/size);
    lighting.actorSelfShadowBias.value=settings.bias;
    lighting.actorSelfShadowStrength.value=settings.strength;
  }
  private depthMaterial(source:THREE.Material):THREE.Material {
    if(this.materials.has(source))return this.materials.get(source)!;
    if(!(source instanceof THREE.ShaderMaterial)||[3,4,5,6].includes(source.uniforms.actorType?.value))return this.disabled;
    const depth=new THREE.MeshDepthMaterial({side:source.side,depthPacking:THREE.BasicDepthPacking,
      map:source.uniforms.baseMap?.value??null,alphaTest:source.uniforms.alphaClip?.value ? .33 : 0});
    this.materials.set(source,depth);return depth;
  }
  render(renderer:THREE.WebGLRenderer,scene:THREE.Scene,view:THREE.Camera,meshes:THREE.SkinnedMesh[],outlines:THREE.SkinnedMesh[]):void {
    if(this.disposed||!this.enabled){this.lighting.actorSelfShadowEnabled.value=false;return}
    view.updateMatrixWorld(true);
    const center=new THREE.Vector3(0,.85,0),direction=this.lighting.actorLight.value.clone().transformDirection(view.matrixWorld);
    this.camera.position.copy(center).addScaledVector(direction,3);this.camera.lookAt(center);this.camera.updateMatrixWorld(true);
    const bias=new THREE.Matrix4().set(.5,0,0,.5,0,.5,0,.5,0,0,.5,.5,0,0,0,1);
    this.lighting.actorSelfShadowMatrix.value.copy(bias).multiply(this.camera.projectionMatrix).multiply(this.camera.matrixWorldInverse);
    const original=meshes.map(m=>m.material),visible=outlines.map(m=>m.visible),target=renderer.getRenderTarget(),clear=renderer.getClearColor(new THREE.Color()),alpha=renderer.getClearAlpha();
    try{
      meshes.forEach(m=>{m.material=Array.isArray(m.material)?m.material.map(s=>this.depthMaterial(s)):this.depthMaterial(m.material)});
      outlines.forEach(m=>m.visible=false);renderer.setRenderTarget(this.target);
      const gl=renderer.getContext();if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw new Error('Actor shadow framebuffer unavailable');
      renderer.setClearColor(0xffffff,1);renderer.clear();renderer.render(scene,this.camera);this.lighting.actorSelfShadowEnabled.value=true;
    }catch(error){this.enabled=false;this.failure=String(error);this.lighting.actorSelfShadowEnabled.value=false;}
    finally{meshes.forEach((m,i)=>m.material=original[i]);outlines.forEach((m,i)=>m.visible=visible[i]);renderer.setRenderTarget(target);renderer.setClearColor(clear,alpha)}
  }
  dispose():void{
    if(this.disposed)return;this.disposed=true;
    if(this.lighting.actorSelfShadowMap.value===this.target.depthTexture){this.lighting.actorSelfShadowEnabled.value=false;this.lighting.actorSelfShadowMap.value=null}
    this.target.dispose();this.disabled.dispose();for(const material of this.materials.values())material.dispose();this.materials.clear();
  }
}
