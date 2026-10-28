import {describe,it,expect} from "vitest";
import {Bone,Quaternion} from "three";
import {calculateUnityQuartz,convertQuartzHair,Stand3DQuartzHair,type QuartzHairSetting} from "./Stand3DQuartzHair";

const v=(x=0,y=x,z=x)=>({x,y,z});
const setting:QuartzHairSetting={translateConnectionAxis:3,rotationOrder:0,rotateConnectionAxis:0,composeType:0,
  headTranslateCoefficient:v(.05,.05,0),headTranslateLimitMin:v(-30),headTranslateLimitMax:v(30),
  headRotateCoefficient:v(-.4),headRotateLimitMin:v(-45),headRotateLimitMax:v(45),
  neckRotateCoefficient:v(-.2),neckRotateLimitMin:v(-45),neckRotateLimitMax:v(45)};
describe("Quartz hair roots",()=>{
  it("converts source units and asymmetric limits without mutating source",()=>{
    const raw={...setting,headRotateLimitMin:v(-10,-20,-30),headRotateLimitMax:v(40,50,60)};
    const s=convertQuartzHair(raw);
    expect(s.headTranslateCoefficient.x).toBe(.0005);
    expect(s.headRotateCoefficient.x).toBe(.4);
    expect(s.headRotateLimitMin).toEqual(v(-10,-50,-60));
    expect(raw.headRotateLimitMin).toEqual(v(-10,-20,-30));
  });
  it("has a stationary identity and mirrors the boundary once",()=>{
    const result=calculateUnityQuartz(new Quaternion(),new Quaternion(),convertQuartzHair(setting));
    expect(result.position.length()).toBe(0);
    expect(result.rotation.angleTo(new Quaternion())).toBeLessThan(1e-7);
    const head=new Bone(),neck=new Bone(),root=new Bone();head.quaternion.setFromAxisAngle({x:1,y:0,z:0},.2);
    const driver=new Stand3DQuartzHair([{bone:'root',setting}],{root},head,neck);
    driver.apply();const first=root.quaternion.clone();driver.apply();
    expect(driver.count).toBe(1);expect(root.quaternion.angleTo(first)).toBeLessThan(1e-7);
    expect(root.quaternion.length()).toBeCloseTo(1,10);
  });
});
