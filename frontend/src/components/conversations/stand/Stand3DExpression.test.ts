import {describe,expect,it} from "vitest";
import {Stand3DExpression,type FacePresets} from "./Stand3DExpression";
import {blendActorFace} from "./Stand3DFace";
const source:FacePresets={version:1,presets:{happy:{'b_brow.brow_001':0,'b_mouth.mouth_031':.9,'b_eye.eye_010':.5},sad:{'b_brow.brow_001':1,'b_mouth.mouth_031':0,'b_eye.eye_010':0}}};
describe('original facial snapshots',()=>{
  it('replaces controlled zero weights, preserves blink and yields mouth motion to speech',()=>{
    const expression=new Stand3DExpression(source),native={'b_brow.brow_001':.8,'b_eye.eye_001':1};
    const weights=expression.apply(native,'happy',0,true);
    expect(weights['b_brow.brow_001']).toBe(0);expect(weights['b_eye.eye_001']).toBe(1);expect(weights['b_eye.eye_010']).toBe(0);
    const speaking=blendActorFace(weights,{},1);expect(speaking['b_mouth.mouth_031']).toBe(0);expect(speaking['b_mouth.mouth_001']).toBe(1);
    expect(native).toEqual({'b_brow.brow_001':.8,'b_eye.eye_001':1});
  });
  it('settles independently of frame rate, freezes at zero dt and returns to native calm',()=>{
    const sample=(fps:number)=>{const e=new Stand3DExpression(source);let w:Record<string,number>={};for(let i=0;i<fps;i++)w=e.apply({},'happy',1/fps,false);return w};
    expect(sample(30)['b_mouth.mouth_031']).toBeCloseTo(sample(120)['b_mouth.mouth_031'],10);
    const e=new Stand3DExpression(source);const first=e.apply({},'happy',.1,false);expect(e.apply({},'happy',0,false)).toEqual(first);
    const native={'b_brow.brow_001':.3};expect(e.apply(native,'calm',0,true)).toBe(native);
  });
  it('uses original preset transitions without stacking incompatible shapes and keeps old models unchanged',()=>{
    const e=new Stand3DExpression(source);e.apply({},'happy',0,true);const changed=e.apply({},'sad',.05,false);
    expect(changed['b_mouth.mouth_031']).toBeGreaterThan(0);expect(changed['b_mouth.mouth_031']).toBeLessThan(.9);
    expect(changed['b_brow.brow_001']).toBeGreaterThan(0);
    const native={'b_eye.eye_001':.2};expect(new Stand3DExpression(undefined).apply(native,'happy',1,false)).toBe(native);
  });
});
