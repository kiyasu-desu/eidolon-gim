import {afterEach,describe,expect,it,vi} from "vitest";
import * as THREE from "three";
import {createActorColorLUT,loadActorColorLUT,type ActorColorLUT} from "./Stand3DColorLUT";

const source:ActorColorLUT={version:1,url:'textures/lut.bin',size:4,encoding:'rgba32f',domain:'logc',exposure:1};
afterEach(()=>vi.unstubAllGlobals());
describe('actor color lookup data',()=>{
  it('retains x-fastest 3D order and HDR texels',()=>{
    const input=new Float32Array(4**3*4);for(let z=0;z<4;z++)for(let y=0;y<4;y++)for(let x=0;x<4;x++)input.set([x,y,z,1],((z*4+y)*4+x)*4);
    const texture=createActorColorLUT(source,input.buffer),data=texture.image.data;
    if(!data)throw new Error('Missing LUT data');
    const pixel=((2*4+1)*4+3)*4;
    expect(Array.from(data.slice(pixel,pixel+4)).map(THREE.DataUtils.fromHalfFloat)).toEqual([3,1,2,1]);
    expect(texture.minFilter).toBe(THREE.LinearFilter);expect(texture.generateMipmaps).toBe(false);texture.dispose();
  });
  it('rejects incomplete, non-finite and unsupported lookup volumes',()=>{
    expect(()=>createActorColorLUT(source,new ArrayBuffer(16))).toThrow('Truncated');
    expect(()=>createActorColorLUT({...source,size:7},new ArrayBuffer(0))).toThrow('Invalid');
    const input=new Float32Array(4**3*4);input[0]=NaN;
    expect(()=>createActorColorLUT(source,input.buffer)).toThrow('texel');
    expect(()=>createActorColorLUT({...source,exposure:0},input.buffer)).toThrow('Invalid');
  });
  it('keeps old assets optional and reports a declared missing file',async()=>{
    const fetch=vi.fn(async()=>new Response('',{status:404}));vi.stubGlobal('fetch',fetch);
    expect(await loadActorColorLUT(undefined,x=>x)).toBe(null);expect(fetch).not.toHaveBeenCalled();
    await expect(loadActorColorLUT(source,x=>'/assets/'+x)).rejects.toThrow('Missing actor color LUT');
  });
});
