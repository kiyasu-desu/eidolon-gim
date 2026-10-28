import * as THREE from "three";
export type FaceCurveKey = { time:number; value:number; inSlope:number; outSlope:number };
export type FaceCorrection = {version:number;target:string;curves:Array<{shape:string;axis:"pitch"|"yaw"|"absoluteYaw";keys:FaceCurveKey[]}>};

export function evaluateFaceCurve(keys:readonly FaceCurveKey[],time:number):number {
  if(!keys.length)return 0;
  if(time<=keys[0].time)return keys[0].value;
  if(time>=keys[keys.length-1].time)return keys[keys.length-1].value;
  const i=keys.findIndex(k=>k.time>=time),a=keys[i-1],b=keys[i],span=b.time-a.time;
  if(span<=0)return b.value;
  const t=(time-a.time)/span,t2=t*t,t3=t2*t;
  return (2*t3-3*t2+1)*a.value+(t3-2*t2+t)*span*a.outSlope+(-2*t3+3*t2)*b.value+(t3-t2)*span*b.inSlope;
}

// Original corrective shapes and Hermite tangents, with reconstructed camera
// yaw/pitch mapping in the mirrored Head_Face frame (not a native-code claim).
export function cameraFaceWeights(setting:FaceCorrection|undefined,bones:Readonly<Record<string,THREE.Bone>>,camera:THREE.Camera):Record<string,number> {
  const target=setting?.version===1?bones[setting.target]:null;
  if(!target||!setting)return {};
  target.updateWorldMatrix(true,false);
  const direction=camera.getWorldPosition(new THREE.Vector3()).sub(target.getWorldPosition(new THREE.Vector3())).applyQuaternion(target.getWorldQuaternion(new THREE.Quaternion()).invert());
  const yaw=-Math.atan2(direction.x,direction.z)*180/Math.PI;
  const pitch=Math.atan2(direction.y,Math.hypot(direction.x,direction.z))*180/Math.PI;
  return Object.fromEntries(setting.curves.map(curve=>[curve.shape,THREE.MathUtils.clamp(evaluateFaceCurve(curve.keys,curve.axis==="pitch"?pitch:curve.axis==="absoluteYaw"?Math.abs(yaw):yaw),0,1)]));
}
