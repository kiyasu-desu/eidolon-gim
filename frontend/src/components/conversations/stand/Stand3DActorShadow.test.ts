import {describe,it,expect,vi} from 'vitest';
import * as THREE from 'three';
import {Stand3DActorShadow,validActorShadowSettings} from './Stand3DActorShadow';
import {createActorLighting,configureActorRim} from './Stand3DMaterial';

describe('actor appearance ownership',()=>{
 it('clears optional rim state for legacy and invalid profiles',()=>{
  const light=createActorLighting();configureActorRim(light,{version:1,direction:[0,0,2],color:[1,.5,.2],power:32,baseColorRatio:.5,strength:.2});expect(light.actorRimStrength.value).toBe(.2);expect(light.actorRimDirection.value.length()).toBeCloseTo(1);
  configureActorRim(light);expect(light.actorRimStrength.value).toBe(0);expect(light.actorRimColor.value.toArray()).toEqual([1,1,1,0]);
  configureActorRim(light,{version:1,direction:[0,0,0],color:[1,1,1],power:32,baseColorRatio:0,strength:1});expect(light.actorRimStrength.value).toBe(0);
 });
 it('restores source materials and visibility if a shadow draw fails, and keeps shared maps owned by the forward pass',()=>{
  const light=createActorLighting(),map=new THREE.Texture(),source=new THREE.ShaderMaterial({uniforms:{actorType:{value:0},baseMap:{value:map},alphaClip:{value:false}}}),mesh=new THREE.SkinnedMesh(new THREE.BufferGeometry(),source),outline=new THREE.SkinnedMesh();
  const oldTarget=new THREE.WebGLRenderTarget(),color=new THREE.Color(.2,.3,.4),renderer={getRenderTarget:()=>oldTarget,getClearColor:(out:THREE.Color)=>out.copy(color),getClearAlpha:()=>.3,setRenderTarget:vi.fn(),getContext:()=>({FRAMEBUFFER:1,FRAMEBUFFER_COMPLETE:2,checkFramebufferStatus:()=>2}),setClearColor:vi.fn(),clear:vi.fn(),render:()=>{throw new Error('test draw failure')}};
  const shadow=new Stand3DActorShadow({version:1,resolution:64,extent:1,bias:.001,strength:.5},light),dispose=vi.spyOn(source,'dispose'),disposeMap=vi.spyOn(map,'dispose');
  shadow.render(renderer as unknown as THREE.WebGLRenderer,new THREE.Scene(),new THREE.PerspectiveCamera(),[mesh],[outline]);
  expect(mesh.material).toBe(source);expect(outline.visible).toBe(true);expect(renderer.setRenderTarget).toHaveBeenLastCalledWith(oldTarget);expect(shadow.enabled).toBe(false);expect(shadow.failure).toContain('test draw failure');
  shadow.dispose();shadow.dispose();expect(dispose).not.toHaveBeenCalled();expect(disposeMap).not.toHaveBeenCalled();expect(light.actorSelfShadowMap.value).toBe(null);map.dispose();source.dispose();oldTarget.dispose();
 });
 it('declines unsupported shadow profiles',()=>{expect(validActorShadowSettings({version:1,resolution:100,extent:1,bias:0,strength:1})).toBe(false);expect(validActorShadowSettings({version:1,resolution:1024,extent:1.15,bias:.0004,strength:.6})).toBe(true)});
});
