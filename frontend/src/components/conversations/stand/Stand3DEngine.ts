// Three.js WebGL 3D stand engine for the call layer. Reuses the verified inverse-bind
// recovery, Head submodule attachment, Humanoid + 2-bone IK retargeting, conservative Hips
// cloth constraints, and palmar/opposition finger retargeting from `.scratch/temari-animation/viewer.js`.

import * as THREE from "three";
import type { Outfit } from "@/lib/api";
import { CALM, type StandDirection } from "@/lib/standAnimations";
import {
  createStand3DPoseState,
  frameStand3D,
  selectStand3DClip,
  stepStand3DPose,
  type Stand3DPoseState,
} from "@/lib/stand3d";
import { FrameGate, MAX_PIXEL_RATIO, pixelRatio } from "@/lib/standFrames";
import { StandUnavailable, type Framing } from "./StandEngine";

type Vec3 = { x: number; y: number; z: number };
type Quat4 = { x: number; y: number; z: number; w: number };
type Matrix16 = Record<string, number>;

type BoneEntry = {
  name: string;
  transform: {
    m_Father: { m_PathID: string | number };
    m_LocalPosition: Vec3;
    m_LocalRotation: Quat4;
    m_LocalScale: Vec3;
  };
};

type MaterialEntry = {
  name: string;
  baseMap: string;
  scale: { x: number; y: number };
  offset: { x: number; y: number };
};

type BlendShapeVertex = {
  vertIndex: number;
  position: Vec3;
};

type BlendShapeEntry = {
  blendShapeName: string;
  blendShapeVertices: BlendShapeVertex[];
};

type MeshEntry = {
  name: string;
  part: string;
  vertices: [number, number, number][];
  uv: [number, number][];
  boneIndices: [number, number, number, number][];
  boneWeights: [number, number, number, number][];
  indices: number[];
  groups: Array<{ start: number; count: number; material: string }>;
  renderer: {
    m_Bones?: Array<{ m_PathID: string | number }>;
    bones?: Array<{ m_PathID: string | number }>;
    bindposes?: Matrix16[];
  };
  meshBindPoses?: Matrix16[];
  shapes?: BlendShapeEntry[];
};

type ModelData = {
  bones: Record<string, BoneEntry>;
  materials: Record<string, MaterialEntry>;
  meshes: MeshEntry[];
};

type ClipTrack = {
  binding: {
    typeID: number;
    attribute: number;
  };
  samples: number[][];
};

type AnimationClipData = {
  name: string;
  duration: number;
  sampleRate: number;
  times: number[];
  sourceLoop: boolean;
  tracks: ClipTrack[];
};

type AnimationData = {
  clips: AnimationClipData[];
};

type FingerJointRig = {
  bone: THREE.Bone;
  axis: THREE.Vector3;
  spread: THREE.Vector3;
  side: "Left" | "Right";
  finger: "Thumb" | "Index" | "Middle" | "Ring" | "Pinky";
  joint: 1 | 2 | 3;
  attribute: number;
  spreadAttribute: number;
};

type LoadedRig = {
  url: string;
  root: THREE.Group;
  bones: Record<string, THREE.Bone>;
  bodyBones: Record<string, THREE.Bone>;
  rest: Map<THREE.Bone, { position: THREE.Vector3; quaternion: THREE.Quaternion; scale: THREE.Vector3 }>;
  clothBind: Map<THREE.Bone, THREE.Matrix4>;
  fingerRig: Record<string, FingerJointRig>;
  meshes: THREE.SkinnedMesh[];
  textures: THREE.Texture[];
  materials: THREE.Material[];
  faceMesh: THREE.SkinnedMesh | null;
  faceSource: MeshEntry | null;
  shapeByName: Map<string, BlendShapeEntry>;
  clips: AnimationClipData[];
};

export type Stand3DDebugInfo = {
  loaded: boolean;
  outfitUrl: string | null;
  clipName: string | null;
  clipTime: number;
  mouthOpen: number;
  mood: string;
  framing: Framing;
  paused: boolean;
  reducedMotion: boolean;
  frameCount: number;
  meshCount: number;
};

export type Stand3DCanvas = HTMLCanvasElement & {
  __stand3d?: () => Stand3DDebugInfo;
};

const MAX_STEP_SECONDS = 0.1;
const MIRROR = new THREE.Matrix4().makeScale(-1, 1, 1);

function sourceMatrix(m: Matrix16): THREE.Matrix4 {
  const elements = Array.from({ length: 16 }, (_, i) => m[`e${Math.floor(i / 4)}${i % 4}`] ?? 0);
  return new THREE.Matrix4()
    .set(
      elements[0], elements[1], elements[2], elements[3],
      elements[4], elements[5], elements[6], elements[7],
      elements[8], elements[9], elements[10], elements[11],
      elements[12], elements[13], elements[14], elements[15],
    )
    .premultiply(MIRROR)
    .multiply(MIRROR);
}

function resolveAssetUrl(outfitUrl: string, relativePath: string): string {
  const base = outfitUrl.endsWith("/") ? outfitUrl : `${outfitUrl}/`;
  return `${base}${relativePath.replace(/^\/+/, "")}`;
}

export class Stand3DEngine {
  private readonly canvas: Stand3DCanvas;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(26, 1, 0.01, 30);
  private readonly listeners = new AbortController();
  private readonly gate = new FrameGate();

  private rig: LoadedRig | null = null;
  private direction: StandDirection = CALM;
  private reducedMotion = false;
  private poseState: Stand3DPoseState = createStand3DPoseState();
  private lastShapeSignature = "";

  private paused = false;
  private still = false;
  private lost = false;
  private disposed = false;
  private loads = 0;
  private raf = 0;
  private last = 0;
  private frameCount = 0;

  constructor(
    canvas: HTMLCanvasElement,
    public framing: Framing,
    private readonly maxPixelRatio: number = MAX_PIXEL_RATIO,
  ) {
    this.canvas = canvas as Stand3DCanvas;
    const signal = this.listeners.signal;
    canvas.addEventListener(
      "webglcontextlost",
      (event) => {
        event.preventDefault();
        this.lost = true;
        this.stop();
      },
      { signal },
    );
    canvas.addEventListener(
      "webglcontextrestored",
      () => {
        if (this.disposed) return;
        this.lost = false;
        this.start();
      },
      { signal },
    );

    try {
      this.renderer = new THREE.WebGLRenderer({
        canvas,
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
      });
    } catch {
      this.listeners.abort();
      throw new StandUnavailable("浏览器不支持 WebGL");
    }

    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setClearColor(0x000000, 0);

    this.canvas.__stand3d = () => ({
      loaded: this.rig !== null,
      outfitUrl: this.rig?.url ?? null,
      clipName: this.rig ? (selectStand3DClip(this.rig.clips, this.reducedMotion)?.name ?? null) : null,
      clipTime: this.poseState.clipTime,
      mouthOpen: this.poseState.mouthOpen,
      mood: this.direction.mood,
      framing: this.framing,
      paused: this.paused,
      reducedMotion: this.reducedMotion,
      frameCount: this.frameCount,
      meshCount: this.rig?.meshes.length ?? 0,
    });
  }

  direct(direction: StandDirection, reducedMotion: boolean): void {
    const motionChanged = this.reducedMotion !== reducedMotion;
    this.direction = direction;
    this.reducedMotion = reducedMotion;
    if (this.rig && (motionChanged || this.paused || this.still)) {
      this.draw(this.rig, 0);
    }
  }

  setStill(still: boolean): void {
    this.still = still;
  }

  setPaused(paused: boolean): void {
    this.paused = paused;
    if (paused) this.stop();
    else this.start();
  }

  async load(outfit: Outfit): Promise<void> {
    const { url } = outfit;
    const ticket = ++this.loads;
    if (this.rig?.url === url) return;

    const [modelRes, animRes] = await Promise.all([
      fetch(resolveAssetUrl(url, "model.json")),
      fetch(resolveAssetUrl(url, "animations.json")),
    ]);
    if (!modelRes.ok || !animRes.ok) {
      throw new Error(`3D 立绘素材 ${modelRes.status}/${animRes.status}`);
    }
    const [modelData, animData] = (await Promise.all([
      modelRes.json(),
      animRes.json(),
    ])) as [ModelData, AnimationData];

    if (this.disposed || ticket !== this.loads) return;

    const built = await this.buildRig(url, modelData, animData);
    if (this.disposed || ticket !== this.loads) {
      this.disposeRig(built);
      return;
    }

    if (this.rig) {
      this.disposeRig(this.rig);
    }
    this.rig = built;
    this.poseState = createStand3DPoseState();
    this.lastShapeSignature = "";
    this.scene.add(built.root);

    this.draw(built, 0);
    this.start();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.stop();
    this.listeners.abort();
    delete this.canvas.__stand3d;
    if (this.rig) {
      this.disposeRig(this.rig);
      this.rig = null;
    }
    this.renderer.dispose();
  }

  private start(): void {
    if (this.raf || this.paused || this.still || this.lost || this.disposed || !this.rig) return;
    this.last = 0;
    this.raf = requestAnimationFrame(this.frame);
  }

  private stop(): void {
    if (!this.raf) return;
    cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  private readonly frame = (now: number): void => {
    this.raf = requestAnimationFrame(this.frame);
    if (!this.gate.shouldDraw(now)) return;
    const step = this.last ? Math.min((now - this.last) / 1000, MAX_STEP_SECONDS) : 0;
    this.last = now;
    if (this.rig) this.draw(this.rig, step);
    if (this.still) this.stop();
  };

  private draw(rig: LoadedRig, step: number): void {
    if (this.lost || this.disposed) return;
    const ratio = pixelRatio(window.devicePixelRatio, this.maxPixelRatio);
    const cssWidth = Math.max(1, this.canvas.clientWidth || 360);
    const cssHeight = Math.max(1, this.canvas.clientHeight || 640);
    this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(cssWidth, cssHeight, false);

    const frame = frameStand3D(this.framing, cssWidth, cssHeight);
    this.camera.fov = frame.fov;
    this.camera.aspect = cssWidth / cssHeight;
    this.camera.position.set(0, frame.targetY, frame.cameraZ);
    this.camera.lookAt(0, frame.targetY, 0);
    this.camera.updateProjectionMatrix();

    const clip = selectStand3DClip(rig.clips, this.reducedMotion);
    this.poseState = stepStand3DPose(
      this.poseState,
      this.direction,
      step,
      this.reducedMotion,
      clip?.duration ?? 0,
      clip?.sourceLoop ?? false,
    );

    this.applyPose(rig, clip, this.poseState);
    this.renderer.render(this.scene, this.camera);
    this.frameCount++;
  }

  private async buildRig(
    outfitUrl: string,
    data: ModelData,
    animationData: AnimationData,
  ): Promise<LoadedRig> {
    const root = new THREE.Group();
    const bones: Record<string, THREE.Bone> = {};
    const bodyBones: Record<string, THREE.Bone> = {};

    for (const [key, b] of Object.entries(data.bones)) {
      const bone = new THREE.Bone();
      const t = b.transform;
      const p = t.m_LocalPosition;
      const q = t.m_LocalRotation;
      const s = t.m_LocalScale;
      bone.name = b.name;
      bone.position.set(-p.x, p.y, p.z);
      bone.quaternion.set(q.x, -q.y, -q.z, q.w);
      bone.scale.set(s.x, s.y, s.z);
      bones[key] = bone;
      if (key.startsWith("body:")) {
        bodyBones[b.name] = bone;
      }
    }

    for (const [key, b] of Object.entries(data.bones)) {
      const part = key.split(":")[0];
      const parent = bones[`${part}:${b.transform.m_Father.m_PathID}`];
      (parent ?? root).add(bones[key]);
    }
    root.updateMatrixWorld(true);

    for (const name of ["Head_Face", "Head_Hair"]) {
      const key = Object.keys(bones).find((k) => bones[k].name === name);
      if (key && bodyBones.Head) {
        bodyBones.Head.add(bones[key]);
      }
    }
    root.updateMatrixWorld(true);

    const bindTargets = new Map<THREE.Bone, THREE.Matrix4>();
    for (const m of data.meshes) {
      const refs = m.renderer.m_Bones ?? m.renderer.bones ?? [];
      const inv = (m.part === "face" ? m.renderer.bindposes : m.meshBindPoses) ?? [];
      refs.forEach((r, i) => {
        const bone = bones[`${m.part}:${r.m_PathID}`];
        if (bone && inv[i]) {
          bindTargets.set(bone, sourceMatrix(inv[i]).invert());
        }
      });
    }

    root.traverse((obj) => {
      const bone = obj as THREE.Bone;
      const target = bindTargets.get(bone);
      if (target && bone.parent) {
        const local = new THREE.Matrix4().copy(bone.parent.matrixWorld).invert().multiply(target);
        local.decompose(bone.position, bone.quaternion, bone.scale);
      }
      bone.updateMatrixWorld(true);
    });

    const hips = bodyBones.Hips;
    const clothBind = new Map<THREE.Bone, THREE.Matrix4>(
      Object.values(bodyBones)
        .filter((b) => b.name.endsWith("Skirt1_S") || /Jacket[2-9]_S/.test(b.name))
        .sort(
          (a, b) =>
            Number(a.name.match(/Jacket([2-9])/)?.[1] ?? 0) -
            Number(b.name.match(/Jacket([2-9])/)?.[1] ?? 0),
        )
        .map((b) => [
          b,
          new THREE.Matrix4().copy(hips.matrixWorld).invert().multiply(b.matrixWorld),
        ]),
    );

    const rest = new Map(
      Object.values(bones).map((b) => [
        b,
        {
          position: b.position.clone(),
          quaternion: b.quaternion.clone(),
          scale: b.scale.clone(),
        },
      ]),
    );

    const fingerRig: Record<string, FingerJointRig> = {};
    const worldPos = (b: THREE.Bone) => b.getWorldPosition(new THREE.Vector3());
    for (const side of ["Left", "Right"] as const) {
      const hand = bodyBones[`${side}Hand`];
      if (!hand) continue;
      const wrist = worldPos(hand);
      const index = worldPos(bodyBones[`${side}HandIndex1`]).sub(wrist);
      const pinky = worldPos(bodyBones[`${side}HandPinky1`]).sub(wrist);
      const palm = index.clone().cross(pinky).normalize();
      if (palm.y > 0) palm.negate();

      const fingers = ["Thumb", "Index", "Middle", "Ring", "Pinky"] as const;
      for (const [fi, finger] of fingers.entries()) {
        for (const joint of [1, 2, 3] as const) {
          const bone = bodyBones[`${side}Hand${finger}${joint}`];
          if (!bone) continue;
          const direction = (
            joint < 3
              ? worldPos(bodyBones[`${side}Hand${finger}${joint + 1}`]).sub(worldPos(bone))
              : worldPos(bone).sub(worldPos(bodyBones[`${side}Hand${finger}2`]))
          ).normalize();
          const inverse = bone.getWorldQuaternion(new THREE.Quaternion()).invert();
          const toward =
            finger === "Thumb"
              ? worldPos(bodyBones[`${side}HandPinky1`]).sub(worldPos(bone)).normalize()
              : palm.clone();
          const middle = worldPos(bodyBones[`${side}HandMiddle1`]);
          const away = worldPos(
            bodyBones[`${side}Hand${finger === "Middle" ? "Index" : finger}1`],
          ).sub(middle);
          away
            .addScaledVector(palm, -away.dot(palm))
            .addScaledVector(direction, -away.dot(direction))
            .normalize();
          const spread = direction.clone().cross(away).normalize().applyQuaternion(inverse);
          fingerRig[bone.name] = {
            bone,
            axis: direction.clone().cross(toward).normalize().applyQuaternion(inverse),
            spread,
            side,
            finger,
            joint,
            attribute: (side === "Left" ? 97 : 117) + fi * 4 + (joint === 1 ? 0 : joint),
            spreadAttribute: (side === "Left" ? 98 : 118) + fi * 4,
          };
        }
      }
    }

    const loader = new THREE.TextureLoader();
    const textures: THREE.Texture[] = [];
    const materials: THREE.Material[] = [];
    const matMap: Record<string, THREE.Material> = {};

    await Promise.all(
      Object.entries(data.materials).map(async ([key, m]) => {
        const tex = await loader.loadAsync(resolveAssetUrl(outfitUrl, m.baseMap));
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.wrapS = THREE.RepeatWrapping;
        tex.wrapT = THREE.RepeatWrapping;
        tex.repeat.set(m.scale.x, m.scale.y);
        tex.offset.set(m.offset.x, m.offset.y);
        tex.anisotropy = 4;
        textures.push(tex);

        const isEyeHighlight = m.name === "m_ehl";
        const mat = new THREE.MeshBasicMaterial({
          map: tex,
          side: THREE.DoubleSide,
          alphaTest: isEyeHighlight ? 0.01 : 0,
          transparent: isEyeHighlight,
          depthWrite: !isEyeHighlight,
          blending: isEyeHighlight ? THREE.AdditiveBlending : THREE.NormalBlending,
        });
        materials.push(mat);
        matMap[key] = mat;
      }),
    );

    const meshes: THREE.SkinnedMesh[] = [];
    let faceMesh: THREE.SkinnedMesh | null = null;
    let faceSource: MeshEntry | null = null;
    const shapeByName = new Map<string, BlendShapeEntry>();

    for (const m of data.meshes) {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute(
        "position",
        new THREE.Float32BufferAttribute(
          m.vertices.flatMap((v) => [-v[0], v[1], v[2]]),
          3,
        ),
      );
      geometry.setAttribute("uv", new THREE.Float32BufferAttribute(m.uv.flat(), 2));
      geometry.setAttribute("skinIndex", new THREE.Uint16BufferAttribute(m.boneIndices.flat(), 4));
      geometry.setAttribute(
        "skinWeight",
        new THREE.Float32BufferAttribute(
          m.boneWeights.flatMap((w) => {
            const sum = w.reduce((a, b) => a + b, 0) || 1;
            return w.map((v) => v / sum);
          }),
          4,
        ),
      );

      const indices: number[] = [];
      for (let i = 0; i < m.indices.length; i += 3) {
        indices.push(m.indices[i], m.indices[i + 2], m.indices[i + 1]);
      }
      geometry.setIndex(indices);
      geometry.computeVertexNormals();
      m.groups.forEach((group, i) => geometry.addGroup(group.start, group.count, i));

      const refs = m.renderer.m_Bones ?? m.renderer.bones ?? [];
      const meshBones = refs.map((r) => bones[`${m.part}:${r.m_PathID}`]);
      const inverse = ((m.part === "face" ? m.renderer.bindposes : m.meshBindPoses) ?? []).map(
        sourceMatrix,
      );
      const skeleton = new THREE.Skeleton(meshBones, inverse);
      const mesh = new THREE.SkinnedMesh(
        geometry,
        m.groups.map((gr) => matMap[gr.material]),
      );
      mesh.name = m.name;
      mesh.frustumCulled = false;
      root.add(mesh);
      mesh.bind(skeleton, new THREE.Matrix4());
      meshes.push(mesh);

      if (m.part === "face") {
        faceMesh = mesh;
        faceSource = m;
        for (const shape of m.shapes ?? []) {
          shapeByName.set(shape.blendShapeName, shape);
        }
      }
    }

    return {
      url: outfitUrl,
      root,
      bones,
      bodyBones,
      rest,
      clothBind,
      fingerRig,
      meshes,
      textures,
      materials,
      faceMesh,
      faceSource,
      shapeByName,
      clips: animationData.clips ?? [],
    };
  }

  private applyPose(
    rig: LoadedRig,
    clip: AnimationClipData | null,
    pose: Stand3DPoseState,
  ): void {
    for (const [bone, r] of rig.rest) {
      bone.position.copy(r.position);
      bone.quaternion.copy(r.quaternion);
      bone.scale.copy(r.scale);
    }

    if (clip && clip.times.length > 0) {
      const clampedTime = THREE.MathUtils.clamp(pose.clipTime, 0, clip.duration);
      const frame = Math.min(clampedTime * clip.sampleRate, clip.times.length - 1);
      const i = Math.floor(frame);
      const j = Math.min(i + 1, clip.times.length - 1);
      const f = frame - i;
      const a: Record<number, number> = {};
      for (const track of clip.tracks) {
        if (track.binding.typeID === 95) {
          a[track.binding.attribute] = THREE.MathUtils.lerp(
            track.samples[i][0],
            track.samples[j][0],
            f,
          );
        }
      }
      this.retargetBody(rig, a);
    }

    if (pose.headPitchDeg !== 0 || pose.headYawDeg !== 0) {
      this.rotateBone(rig.bodyBones, "Neck", pose.headPitchDeg * 0.35, pose.headYawDeg * 0.35, 0);
      this.rotateBone(rig.bodyBones, "Head", pose.headPitchDeg * 0.65, pose.headYawDeg * 0.65, 0);
    }

    this.applyFaceShapes(rig, pose);

    rig.root.updateMatrixWorld(true);
    for (const mesh of rig.meshes) {
      mesh.skeleton.update();
    }
  }

  private rotateBone(
    bodyBones: Record<string, THREE.Bone>,
    name: string,
    x = 0,
    y = 0,
    z = 0,
  ): void {
    const bone = bodyBones[name];
    if (!bone) return;
    bone.quaternion.multiply(
      new THREE.Quaternion().setFromEuler(
        new THREE.Euler((x * Math.PI) / 180, (y * Math.PI) / 180, (z * Math.PI) / 180, "YXZ"),
      ),
    );
  }

  private solveLimb(
    rig: LoadedRig,
    upperName: string,
    lowerName: string,
    endName: string,
    target: THREE.Vector3,
    pole: THREE.Vector3,
  ): void {
    const upper = rig.bodyBones[upperName];
    const lower = rig.bodyBones[lowerName];
    const end = rig.bodyBones[endName];
    if (!upper || !lower || !end) return;
    rig.root.updateMatrixWorld(true);

    const start = upper.getWorldPosition(new THREE.Vector3());
    const mid = lower.getWorldPosition(new THREE.Vector3());
    const tip = end.getWorldPosition(new THREE.Vector3());
    const l1 = start.distanceTo(mid);
    const l2 = mid.distanceTo(tip);
    const dir = target.clone().sub(start);
    const distance = THREE.MathUtils.clamp(dir.length(), Math.abs(l1 - l2) + 1e-5, l1 + l2 - 1e-5);
    dir.normalize();

    const bend = pole.clone().sub(dir.clone().multiplyScalar(pole.dot(dir))).normalize();
    const along = (l1 * l1 - l2 * l2 + distance * distance) / (2 * distance);
    const height = Math.sqrt(Math.max(0, l1 * l1 - along * along));
    const elbow = start.clone().addScaledVector(dir, along).addScaledVector(bend, height);

    const aim = (bone: THREE.Bone, from: THREE.Vector3, to: THREE.Vector3) => {
      if (!bone.parent) return;
      const delta = new THREE.Quaternion().setFromUnitVectors(from.normalize(), to.normalize());
      const world = bone.getWorldQuaternion(new THREE.Quaternion()).premultiply(delta);
      bone.quaternion.copy(
        bone.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(world),
      );
      rig.root.updateMatrixWorld(true);
    };

    aim(upper, mid.clone().sub(start), elbow.clone().sub(start));
    const newMid = lower.getWorldPosition(new THREE.Vector3());
    const newTip = end.getWorldPosition(new THREE.Vector3());
    aim(lower, newTip.sub(newMid), target.clone().sub(newMid));
  }

  private retargetBody(rig: LoadedRig, a: Record<number, number>): void {
    const v = (i: number) => a[42 + i] ?? 0;
    const spineOffsets: ReadonlyArray<readonly [string, number]> = [
      ["Spine", 0],
      ["Spine1", 3],
      ["Spine2", 6],
      ["Neck", 9],
      ["Head", 12],
    ];
    for (const [name, i] of spineOffsets) {
      this.rotateBone(rig.bodyBones, name, -v(i) * 30, v(i + 2) * 45, -v(i + 1) * 30);
    }

    const hips = rig.bodyBones.Hips;
    if (hips && a[8] !== undefined) {
      hips.position.set(-(a[7] ?? 0), a[8], a[9] ?? 0);
      hips.quaternion.set(a[10] ?? 0, -(a[11] ?? 0), -(a[12] ?? 0), a[13] ?? 1).normalize();
    }

    const sides: ReadonlyArray<readonly ["Left" | "Right", number, number, number, number]> = [
      ["Left", 1, 21, 37, 39],
      ["Right", -1, 29, 46, 48],
    ];
    for (const [side, s, leg, shoulder, arm] of sides) {
      this.rotateBone(rig.bodyBones, `${side}UpLeg`, -(v(leg) - 0.5) * 60, -s * v(leg + 2) * 30, s * v(leg + 1) * 35);
      this.rotateBone(rig.bodyBones, `${side}Leg`, (1 - v(leg + 3)) * 70, -s * v(leg + 4) * 30, 0);
      this.rotateBone(rig.bodyBones, `${side}Foot`, -v(leg + 5) * 35, -s * v(leg + 6) * 30, 0);
      this.rotateBone(rig.bodyBones, `${side}ToeBase`, -v(leg + 7) * 30, 0, 0);
      this.rotateBone(rig.bodyBones, `${side}Shoulder`, 0, s * v(shoulder + 1) * 25, s * v(shoulder) * 25);
      this.rotateBone(rig.bodyBones, `${side}Arm`, s * v(arm + 2) * 35, -s * v(arm + 1) * 60, s * v(arm) * 90);
      this.rotateBone(rig.bodyBones, `${side}ForeArm`, s * v(arm + 4) * 45, -s * (1 - v(arm + 3)) * 75, 0);
      this.rotateBone(rig.bodyBones, `${side}Hand`, s * v(arm + 5) * 45, -s * v(arm + 6) * 30, 0);
    }

    this.applyFingers(rig, a);

    if (!hips) return;
    rig.root.updateMatrixWorld(true);
    const hipWorld = hips.getWorldPosition(new THREE.Vector3());
    const hipQ = hips.getWorldQuaternion(new THREE.Quaternion());

    for (const [side, s, offset] of [
      ["Left", 1, 28],
      ["Right", -1, 35],
    ] as const) {
      const target = new THREE.Vector3(-(a[offset] ?? 0), a[offset + 1] ?? 0, a[offset + 2] ?? 0)
        .applyQuaternion(hipQ)
        .add(hipWorld);
      this.solveLimb(
        rig,
        `${side}Arm`,
        `${side}ForeArm`,
        `${side}Hand`,
        target,
        new THREE.Vector3(s, -0.15, -0.35),
      );
    }

    for (const [side, offset] of [
      ["Left", 14],
      ["Right", 21],
    ] as const) {
      const target = new THREE.Vector3(-(a[offset] ?? 0), a[offset + 1] ?? 0, a[offset + 2] ?? 0)
        .applyQuaternion(hipQ)
        .add(hipWorld);
      target.y += 0.098;
      this.solveLimb(
        rig,
        `${side}UpLeg`,
        `${side}Leg`,
        `${side}Foot`,
        target,
        new THREE.Vector3(0, 0, 1),
      );
    }

    rig.root.updateMatrixWorld(true);
    for (const [bone, relative] of rig.clothBind) {
      if (!bone.parent) continue;
      const adjusted = relative.clone();
      if (bone.name.includes("Jacket")) {
        adjusted.elements[12] *= 1.08;
        adjusted.elements[14] *= 1.08;
      }
      const desired = new THREE.Matrix4().multiplyMatrices(hips.matrixWorld, adjusted);
      const local = new THREE.Matrix4().copy(bone.parent.matrixWorld).invert().multiply(desired);
      local.decompose(bone.position, bone.quaternion, bone.scale);
      bone.updateMatrixWorld(true);
    }
  }

  private applyFingers(rig: LoadedRig, a: Record<number, number>): void {
    for (const r of Object.values(rig.fingerRig)) {
      const curl = -Math.expm1(-Math.LN2 * Math.max(0, 1 - (a[r.attribute] ?? 1)));
      const limit = r.finger === "Thumb" ? [25, 50, 50][r.joint - 1] : [65, 85, 65][r.joint - 1];
      if (r.joint === 1) {
        const fan = r.finger === "Middle" || r.finger === "Ring" ? 0.35 : 1;
        r.bone.quaternion.multiply(
          new THREE.Quaternion().setFromAxisAngle(
            r.spread,
            (THREE.MathUtils.clamp(a[r.spreadAttribute] ?? 0, -1, 1) * fan * 12 * Math.PI) / 180,
          ),
        );
      }
      r.bone.quaternion.multiply(
        new THREE.Quaternion().setFromAxisAngle(r.axis, (curl * limit * Math.PI) / 180),
      );
    }
  }

  private applyFaceShapes(rig: LoadedRig, pose: Stand3DPoseState): void {
    const { faceMesh, faceSource, shapeByName } = rig;
    if (!faceMesh || !faceSource) return;

    const active: Array<[BlendShapeEntry, number]> = [];
    if (pose.mouthOpen > 1e-3) {
      const mouthShape = shapeByName.get("b_mouth.mouth_001");
      if (mouthShape) active.push([mouthShape, pose.mouthOpen]);
    }
    const mouthAttenuation = 1 - pose.mouthOpen * 0.7;
    for (const [name, rawWeight] of Object.entries(pose.shapeWeights)) {
      const weight = name.startsWith("b_mouth.") ? rawWeight * mouthAttenuation : rawWeight;
      if (weight > 1e-3) {
        const shape = shapeByName.get(name);
        if (shape) active.push([shape, weight]);
      }
    }

    const signature = active.map(([s, w]) => `${s.blendShapeName}:${w.toFixed(3)}`).join("|");
    if (signature === this.lastShapeSignature) return;
    this.lastShapeSignature = signature;

    const posAttr = faceMesh.geometry.attributes.position as THREE.BufferAttribute;
    const array = posAttr.array as Float32Array;
    const baseVertices = faceSource.vertices;
    for (let i = 0; i < baseVertices.length; i++) {
      const base = baseVertices[i];
      const offset = i * 3;
      array[offset] = -base[0];
      array[offset + 1] = base[1];
      array[offset + 2] = base[2];
    }

    for (const [shape, weight] of active) {
      for (const v of shape.blendShapeVertices) {
        const offset = v.vertIndex * 3;
        array[offset] -= v.position.x * weight;
        array[offset + 1] += v.position.y * weight;
        array[offset + 2] += v.position.z * weight;
      }
    }
    posAttr.needsUpdate = true;
    faceMesh.geometry.computeVertexNormals();
  }

  private disposeRig(rig: LoadedRig): void {
    this.scene.remove(rig.root);
    for (const mesh of rig.meshes) {
      mesh.geometry.dispose();
    }
    for (const mat of rig.materials) {
      mat.dispose();
    }
    for (const tex of rig.textures) {
      tex.dispose();
    }
  }
}
