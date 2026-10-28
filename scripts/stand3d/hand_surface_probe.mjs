import * as T from 'three';

// Diagnostic only: actual deformed hand-skin edges versus torso/garment surface.
export function createHandSurfaceProbe(mesh){
 const g=mesh.geometry,skin=g.attributes.skinIndex,weights=g.attributes.skinWeight,index=g.index.array,uv=g.attributes.uv;
 const image=mesh.material.find(m=>m.uniforms?.shadeMap)?.uniforms.shadeMap.value.image,canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);const rgba=ctx.getImageData(0,0,image.width,image.height).data;
 const side=[],arm=[];for(let i=0;i<skin.count;i++){let left=0,right=0,total=0;for(let k=0;k<4;k++){const name=mesh.skeleton.bones[skin.getComponent(i,k)].name,w=weights.getComponent(i,k);if(name.startsWith('LeftHand'))left+=w;if(name.startsWith('RightHand'))right+=w;if(/Hand|Arm|Shoulder/.test(name))total+=w}const x=Math.max(0,Math.min(image.width-1,Math.floor(uv.getX(i)*image.width))),y=Math.max(0,Math.min(image.height-1,Math.floor((1-uv.getY(i))*image.height)));side[i]=rgba[(y*image.width+x)*4+3]>127?(left>.95?'left':right>.95?'right':null):null;arm[i]=total}
 const edges=new Map(),torso=[];let handTriangles=0;for(let i=0;i<index.length;i+=3){const ids=[index[i],index[i+1],index[i+2]];if(side[ids[0]]&&ids.every(v=>side[v]===side[ids[0]])){handTriangles++;for(let k=0;k<3;k++){const a=ids[k],b=ids[(k+1)%3];edges.set(a<b?a+','+b:b+','+a,[a,b])}}else if(ids.every(v=>arm[v]<.05))torso.push(ids)}
 const handVertices=[...new Set([...edges.values()].flat())],cell=.025,visit=(box,fn)=>{for(let x=Math.floor(box.min.x/cell);x<=Math.floor(box.max.x/cell);x++)for(let y=Math.floor(box.min.y/cell);y<=Math.floor(box.max.y/cell);y++)for(let z=Math.floor(box.min.z/cell);z<=Math.floor(box.max.z/cell);z++)fn(x+','+y+','+z)};
 return {handTriangles,handEdges:edges.size,torsoTriangles:torso.length,measure(){
  mesh.updateMatrixWorld(true);mesh.skeleton.update();const points=new Map(),point=i=>{if(!points.has(i))points.set(i,mesh.getVertexPosition(i,new T.Vector3()).applyMatrix4(mesh.matrixWorld));return points.get(i)},box=new T.Box3().setFromPoints(handVertices.map(point)),triangles=[],grid=new Map();
  for(const ids of torso){const triangle=ids.map(point),bounds=new T.Box3().setFromPoints(triangle);if(!bounds.intersectsBox(box))continue;const id=triangles.length;triangles.push(triangle);visit(bounds,key=>{if(!grid.has(key))grid.set(key,[]);grid.get(key).push(id)})}
  const bySide={left:0,right:0},ray=new T.Ray(),hit=new T.Vector3();let count=0;
  for(const [a,b] of edges.values()){const start=point(a),end=point(b),delta=end.clone().sub(start),length=delta.length();if(length<1e-8)continue;ray.set(start,delta.divideScalar(length));const candidates=new Set();visit(new T.Box3().setFromPoints([start,end]),key=>{for(const id of grid.get(key)??[])candidates.add(id)});for(const id of candidates){const t=triangles[id];if(ray.intersectTriangle(t[0],t[1],t[2],false,hit)){const d=hit.distanceTo(start);if(d>1e-5&&d<length-1e-5){bySide[side[a]]++;count++;break}}}}
  return {edges:count,bySide};
 }};
}
