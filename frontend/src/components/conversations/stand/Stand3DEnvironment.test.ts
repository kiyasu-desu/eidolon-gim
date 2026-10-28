import {afterEach,describe,expect,it,vi} from "vitest";
import * as THREE from "three";
import {createActorCube,loadActorEnvironment,unpackRGB9E5,type ActorEnvironment} from "./Stand3DEnvironment";

afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals()});
const spec={url:'body.bin',width:1,mipCount:1,encoding:'rgb9e5' as const};
describe('actor reflection resources',()=>{
  it('preserves shared-exponent HDR values and tiny representable components',()=>{
    expect(unpackRGB9E5((16<<27)|(64<<18)|(128<<9)|256)).toEqual([1,.5,.25]);
    expect(unpackRGB9E5((31<<27)|511)[0]).toBe(65408);
    expect(unpackRGB9E5(1)[0]).toBe(2**-24);
    const bytes=new ArrayBuffer(24),words=new DataView(bytes);
    for(let face=0;face<6;face++)words.setUint32(face*4,(16<<27)|(face*64),true);
    const cube=createActorCube(spec,bytes);
    for(let face=0;face<6;face++){
      const data=cube.images[face].image.data;
      if(!data)throw new Error('Missing cube face');
      expect(THREE.DataUtils.fromHalfFloat(data[0])).toBe(face*.25);
    }
    expect(cube.generateMipmaps).toBe(false);expect(cube.type).toBe(THREE.HalfFloatType);cube.dispose();
  });
  it('rejects malformed dimensions or truncated mip chains',()=>{
    expect(()=>createActorCube({...spec,width:3},new ArrayBuffer(24))).toThrow('layout');
    expect(()=>createActorCube({...spec,width:4,mipCount:2},new ArrayBuffer(24))).toThrow('layout');
    expect(()=>createActorCube(spec,new ArrayBuffer(20))).toThrow('Truncated');
  });
  it('settles both loads and disposes a successful cube when its companion fails',async()=>{
    const late=Promise.withResolvers<Response>();
    vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('eye.bin')?Promise.resolve(new Response('',{status:404})):late.promise));
    const dispose=vi.spyOn(THREE.CubeTexture.prototype,'dispose');
    const source:ActorEnvironment={version:1,body:spec,eye:{...spec,url:'eye.bin'},bodyColor:[1,1,1],eyeColor:[1,1,1]};
    const loaded=loadActorEnvironment(source,x=>x);const rejected=expect(loaded).rejects.toThrow('Missing actor reflection');
    expect(dispose).not.toHaveBeenCalled();late.resolve(new Response(new ArrayBuffer(24)));await rejected;expect(dispose).toHaveBeenCalledTimes(1);
    expect(await loadActorEnvironment(undefined,x=>x)).toBe(null);
  });
});
