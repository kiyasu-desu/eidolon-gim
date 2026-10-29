// Three.js WebGL 3D stand engine for the call layer. Reuses the verified inverse-bind
// recovery and Head submodule attachment. Uses Unity-baked body motion when present;
// retains approximate Humanoid/IK playback for older private asset schemas.

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
import { StandUnavailable, type Framing } from "./standTypes";
import { Stand3DSwing, type SwingSetting } from "./Stand3DSwing";
import { createActorLighting, configureActorRim, loadActorMaterials, type ActorRimSettings, type ActorLighting, type Stand3DMaterialSource } from "./Stand3DMaterial";
import {createActorOutlineMaterial,type ActorOutlineSettings} from "./Stand3DOutline";
import {Stand3DActorShadow,validActorShadowSettings,type ActorShadowSettings} from "./Stand3DActorShadow";
import { blendActorFace, sampleActorFace } from "./Stand3DFace";
import { Stand3DBodyMotion, type SkeletalMotion } from "./Stand3DBodyMotion";
import { Stand3DSecondary, type SecondaryMotion } from "./Stand3DSecondary";
import { Stand3DCollision } from "./Stand3DCollision";
import { Stand3DGesture } from "./Stand3DGesture";
import { Stand3DHandContact } from "./Stand3DHandContact";
import { Stand3DSlide } from "./Stand3DSlide";
import { cameraFaceWeights, type FaceCorrection } from "./Stand3DFaceCorrection";
import { Stand3DColorPipeline, type ActorColorWorkflow } from "./Stand3DColorPipeline";
import { Stand3DBlink, type BlinkTiming } from "./Stand3DBlink";
import { Stand3DQuartzHair, type QuartzHairDriver } from "./Stand3DQuartzHair";
import type { ActorEnvironment } from "./Stand3DEnvironment";
import { loadActorColorLUT, type ActorColorLUT } from "./Stand3DColorLUT";
import { Stand3DExpression, type FacePresets } from "./Stand3DExpression";
import { Stand3DHandClearance, type HandClearanceSettings } from "./Stand3DHandClearance";

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

type MaterialEntry = Stand3DMaterialSource;

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
  normals?: [number, number, number][];
  outlineNormals?: [number, number, number][];
  colors?: [number, number, number, number][];
  colorFormat?: "unorm8" | "float";
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
  hairPhysics?: { version: number; bones: SwingSetting[] };
  secondaryMotion?: SecondaryMotion;
  faceCorrection?: FaceCorrection;
  faceBehavior?: {version:number;blink:BlinkTiming};
  quartzHair?: {version:number;drivers:QuartzHairDriver[]};
  environment?: ActorEnvironment;
  colorLUT?: ActorColorLUT;
  facePresets?: FacePresets;
  handClearance?: HandClearanceSettings;
  outline?:ActorOutlineSettings;
  actorShadow?:ActorShadowSettings;
  rim?:ActorRimSettings;
};

type ClipTrack = {
  shapeName?: string;
  shapeScale?: number;
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
  skeletal?: SkeletalMotion;
  role?: string;
  holdClipName?: string;
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
  outlines?:THREE.SkinnedMesh[];
  outlineMaterials?:THREE.Material[];
  actorShadow?:Stand3DActorShadow;
  textures: THREE.Texture[];
  materials: THREE.Material[];
  faceMesh: THREE.SkinnedMesh | null;
  faceSource: MeshEntry | null;
  shapeByName: Map<string, BlendShapeEntry>;
  clips: AnimationClipData[];
  swing: Stand3DSwing;
  bodyMotion: Stand3DBodyMotion;
  secondary: Stand3DSecondary;
  collision: Stand3DCollision;
  bodySwing: Stand3DSwing;
  gesture: Stand3DGesture<AnimationClipData>;
  activeBodyClip: string | null;
  handContact: Stand3DHandContact;
  handClearance: Stand3DHandClearance;
  slide: Stand3DSlide;
  faceCorrection?: FaceCorrection;
  blink: Stand3DBlink;
  expression: Stand3DExpression;
  quartzHair: Stand3DQuartzHair;
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
  physicsSegments: number;
  shadedMaterials: number;
  facialTracks: number;
  bakedBodyBones: number;
  auxiliaryBones: number;
  hairRootDrivers: number;
  clothSegments: number;
  collisionBodies: number;
  clothPenetration: number;
  bodyClipName: string | null;
  handGoals: number;
  handPenetrationBefore: number;
  handPenetrationAfter: number;
  slideSegments: number;
  collisionChains: number;
  chainPenetration: number;
  slideOffset: number;
  colorWorkflow: ActorColorWorkflow;
  hdrColorBuffer: boolean;
  reflectionCubes: number;
  colorLUTEnabled: boolean;
  sourceFacePresets: number;
  handClearanceGoals: number;
  handClearanceShift: number;
  dynamicLineSegments: number;
  dynamicLinePenetration: number;
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
  private actorLighting = createActorLighting();
  private readonly colorPipeline: Stand3DColorPipeline;

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
    colorWorkflow: ActorColorWorkflow = "linear",
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
        premultipliedAlpha: true,
        antialias: true,
        powerPreference: "high-performance",
      });
    } catch {
      this.listeners.abort();
      throw new StandUnavailable("浏览器不支持 WebGL");
    }

    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setClearColor(0x000000, 0);
    this.colorPipeline = new Stand3DColorPipeline(this.renderer, colorWorkflow);

    this.canvas.__stand3d = () => {
      const rig = this.rig;
      const clip = rig ? selectStand3DClip(rig.clips, this.reducedMotion) : null;
      const face = rig?.clips.find((c) => c.name === clip?.name.replace(/_b$/, "_f"));
      return {
        loaded: rig !== null,
        outfitUrl: rig?.url ?? null,
        clipName: clip?.name ?? null,
        clipTime: this.poseState.clipTime,
        mouthOpen: this.poseState.mouthOpen,
        mood: this.direction.mood,
        framing: this.framing,
        paused: this.paused,
        reducedMotion: this.reducedMotion,
        frameCount: this.frameCount,
        meshCount: rig?.meshes.length ?? 0,
        outlineMeshes: rig?.outlines?.length ?? 0,
        actorSelfShadow:rig?.actorShadow?.enabled??false,
        actorShadowFailure:rig?.actorShadow?.failure??null,
        actorRimStrength:this.actorLighting.actorRimStrength.value,
        physicsSegments: rig?.swing.segmentCount ?? 0,
        shadedMaterials: rig?.materials.filter((m) => m instanceof THREE.ShaderMaterial).length ?? 0,
        facialTracks: face?.tracks.filter((t) => t.shapeName).length ?? 0,
        bakedBodyBones: clip?.skeletal?.version === 1 ? clip.skeletal.tracks.length : 0,
        auxiliaryBones: rig?.secondary.count ?? 0,
        hairRootDrivers: rig?.quartzHair.count ?? 0,
        reflectionCubes: rig?.textures.filter(texture=>texture instanceof THREE.CubeTexture).length ?? 0,
        clothSegments: rig?.bodySwing.segmentCount ?? 0,
        collisionBodies: rig?.collision.count ?? 0,
        clothPenetration: rig?.bodySwing.maxPenetration ?? 0,
        bodyClipName: rig?.activeBodyClip ?? null,
        handGoals: rig?.handContact.count ?? 0,
        handPenetrationBefore: rig?.handContact.maxBefore ?? 0,
        handPenetrationAfter: rig?.handContact.maxAfter ?? 0,
        slideSegments: (rig?.bodySwing.slideCount ?? 0)+(rig?.slide.count ?? 0),
        collisionChains: (rig?.bodySwing.chainCount ?? 0)+(rig?.swing.chainCount ?? 0),
        chainPenetration: Math.max(rig?.bodySwing.maxEdgePenetration ?? 0,rig?.swing.maxEdgePenetration ?? 0),
        slideOffset: rig?.slide.maxOffset ?? 0,
        colorWorkflow: this.colorPipeline.mode,
        hdrColorBuffer: this.colorPipeline.hdr,
        colorLUTEnabled: this.colorPipeline.colorLUTEnabled,
        sourceFacePresets: rig?.expression.count ?? 0,
        handClearanceGoals: rig?.handClearance.count ?? 0,
        handClearanceShift: rig?.handClearance.maxCorrection ?? 0,
        dynamicLineSegments: (rig?.bodySwing.lineCount ?? 0)+(rig?.swing.lineCount ?? 0),
        clothClearanceJoints: rig?.bodySwing.clearanceCount ?? 0,
        speakingGestureClips: rig?.gesture.count ?? 0,
        speakingHoldClips: rig?.gesture.holdCount ?? 0,
        dynamicLinePenetration: Math.max(rig?.bodySwing.maxLinePenetration ?? 0,rig?.swing.maxLinePenetration ?? 0),
      };
    };
  }

  direct(direction: StandDirection, reducedMotion: boolean): void {
    const motionChanged = this.reducedMotion !== reducedMotion;
    this.direction = direction;
    this.reducedMotion = reducedMotion;
    if (motionChanged) { this.rig?.swing.reset(); this.rig?.bodySwing.reset(); this.rig?.slide.reset(); }
    if (this.rig && (motionChanged || this.paused || this.still)) {
      this.draw(this.rig, 0);
    }
  }

  setStill(still: boolean): void {
    this.still = still;
  }

  setPaused(paused: boolean): void {
    this.paused = paused;
    // Freeze the existing solve, including contact calibration and velocities.
    // start() clears the wall-clock reference so resume cannot accumulate time.
    if (paused) this.stop();
    else this.start();
  }

  async load(outfit: Outfit): Promise<void> {
    const { url } = outfit;
    const ticket = ++this.loads;
    if (this.rig?.url === url) return;

    const [modelRes, animRes] = await Promise.all([
      // Metadata carries versioned material/face bindings. Revalidate its ETag
      // so an old day-long cache cannot hide a newly deployed rendering upgrade.
      fetch(resolveAssetUrl(url, "model.json"), { cache: "no-cache" }),
      fetch(resolveAssetUrl(url, "animations.json"), { cache: "no-cache" }),
    ]);
    if (!modelRes.ok || !animRes.ok) {
      throw new Error(`3D 立绘素材 ${modelRes.status}/${animRes.status}`);
    }
    const [modelData, animData] = (await Promise.all([
      modelRes.json(),
      animRes.json(),
    ])) as [ModelData, AnimationData];

    if (this.disposed || ticket !== this.loads) return;

    // Each pending outfit owns its globals. A failed LUT request or an obsolete
    // load must not replace the displayed outfit's uniforms with disposed maps.
    const lighting = createActorLighting();
    const built = await this.buildRig(url, modelData, animData, lighting);
    if (this.disposed || ticket !== this.loads) {
      this.disposeRig(built);
      return;
    }
    let colorLUT: THREE.Data3DTexture | null;
    try {
      colorLUT = await loadActorColorLUT(modelData.colorLUT, path => resolveAssetUrl(url, path));
      if (colorLUT) built.textures.push(colorLUT);
    } catch (error) {
      this.disposeRig(built);
      throw error;
    }
    if (this.disposed || ticket !== this.loads) {
      this.disposeRig(built);
      return;
    }

    this.colorPipeline.setColorLUT(null);
    if (this.rig) {
      this.disposeRig(this.rig);
    }
    this.rig = built;
    this.actorLighting = lighting;
    this.colorPipeline.setColorLUT(colorLUT, modelData.colorLUT?.exposure ?? 1);
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
    this.colorPipeline.dispose();
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

    const body = rig.gesture.step(clip, this.poseState.clipTime, this.direction.speaking, step, this.reducedMotion);
    rig.activeBodyClip = body.clip?.name ?? null;
    const idleFace = clip ? rig.clips.find(c => c.name === clip.name.replace(/_b$/, "_f")) ?? null : null;
    this.applyPose(rig, body.clip, { ...this.poseState, clipTime: body.time }, step, { clip: idleFace, time: this.poseState.clipTime });
    this.presentScene();
    this.frameCount++;
  }

  private presentScene(): void {
    if(this.rig?.actorShadow)this.rig.actorShadow.render(this.renderer,this.scene,this.camera,this.rig.meshes,this.rig.outlines??[]);
    this.colorPipeline.render(this.scene, this.camera);
  }

  private async buildRig(
    outfitUrl: string,
    data: ModelData,
    animationData: AnimationData,
    lighting: ActorLighting,
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

    const { textures, materials, map: matMap } = await loadActorMaterials(
      data.materials, (path) => resolveAssetUrl(outfitUrl, path), lighting, this.colorPipeline.mode === "linear", data.environment,
    );
    configureActorRim(lighting,data.rim);

    const meshes: THREE.SkinnedMesh[] = [];
    const outlines:THREE.SkinnedMesh[]=[],outlineMaterials:THREE.Material[]=[],outlineMap=new Map<string,THREE.Material|null>();
    let hiddenOutline:THREE.Material|null=null;
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
      geometry.setAttribute("actorMask", new THREE.Float32BufferAttribute(
        m.colors?.flatMap((color) => color.map((v) => m.colorFormat === "unorm8" ? v / 255 : v)) ?? new Array(m.vertices.length * 4).fill(0), 4,
      ));
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
      if (m.normals?.length === m.vertices.length) {
        geometry.setAttribute("normal", new THREE.Float32BufferAttribute(m.normals.flatMap((n) => [-n[0], n[1], n[2]]), 3));
      } else geometry.computeVertexNormals();
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
      if(data.outline?.version===1&&m.outlineNormals?.length===m.vertices.length&&m.colors?.some(c=>((m.colorFormat==='unorm8'?c[2]:Math.round(c[2]*255))%16)>0)){
        geometry.setAttribute('actorOutlineNormal',new THREE.Float32BufferAttribute(m.outlineNormals.flatMap(n=>[-n[0],n[1],n[2]]),3));
        const pass=m.groups.map(g=>{
          if(!outlineMap.has(g.material)){const mat=createActorOutlineMaterial(data.materials[g.material],lighting,data.outline!);outlineMap.set(g.material,mat);if(mat)outlineMaterials.push(mat)}
          return outlineMap.get(g.material)??null;
        });
        if(pass.some(Boolean)){
          if(pass.some(m=>!m)&&!hiddenOutline){hiddenOutline=new THREE.MeshBasicMaterial();hiddenOutline.visible=false;outlineMaterials.push(hiddenOutline)}
          const shell=new THREE.SkinnedMesh(geometry,pass.map(m=>m??hiddenOutline!));shell.name=m.name+':outline';shell.frustumCulled=false;shell.renderOrder=10000;
          root.add(shell);shell.bind(skeleton,mesh.bindMatrix.clone());outlines.push(shell);
        }
      }

      if (m.part === "face") {
        faceMesh = mesh;
        faceSource = m;
        for (const shape of m.shapes ?? []) {
          shapeByName.set(shape.blendShapeName, shape);
        }
      }
    }

    const secondary = data.secondaryMotion?.version === 1 && animationData.clips.some(c => c.skeletal?.version === 1)
      ? data.secondaryMotion : null;
    const speakingClips=secondary?animationData.clips.filter(c=>c.role==="speakingGesture"&&c.skeletal?.version===1):[];
    const speakingHolds=new Map<AnimationClipData,AnimationClipData>();
    for(const source of speakingClips){const hold=animationData.clips.find(c=>c.name===source.holdClipName&&c.role==='speakingHold'&&c.skeletal?.version===1);if(hold)speakingHolds.set(source,hold);}
    const collision = new Stand3DCollision(secondary?.colliders ?? [], bones);
    const weighted = new Set<string>();
    for(const source of data.meshes.filter(m=>m.part==="body")) {
      const references=source.renderer.m_Bones??source.renderer.bones??[];
      source.boneIndices.forEach((indices,i)=>indices.forEach((index,j)=>{if(source.boneWeights[i][j]>0&&references[index])weighted.add(`body:${references[index].m_PathID}`)}));
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
      outlines,
      outlineMaterials,
      actorShadow:validActorShadowSettings(data.actorShadow)&&this.colorPipeline.mode==='linear'?new Stand3DActorShadow(data.actorShadow,lighting):undefined,
      textures,
      materials,
      faceMesh,
      faceSource,
      shapeByName,
      clips: animationData.clips ?? [],
      swing: new Stand3DSwing(data.hairPhysics?.version === 1 ? data.hairPhysics.bones : [], bones, secondary ? collision : undefined, secondary?.hairChains),
      bodyMotion: new Stand3DBodyMotion(bones),
      secondary: new Stand3DSecondary(secondary?.auxiliary ?? [], bones),
      expression: new Stand3DExpression(data.facePresets),
      quartzHair: new Stand3DQuartzHair(data.quartzHair?.version === 1 ? data.quartzHair.drivers : [],bones,bodyBones.Head,bodyBones.Neck),
      collision,
      bodySwing: new Stand3DSwing(secondary?.body ?? [], bones, secondary ? collision : undefined, secondary?.bodyChains,secondary?.clothClearance),
      gesture: new Stand3DGesture(speakingClips[0]??null,speakingClips.slice(1),speakingHolds),
      activeBodyClip: null,
      handContact: new Stand3DHandContact(secondary?.hands, bones),
      handClearance: new Stand3DHandClearance(data.handClearance, bones),
      slide: new Stand3DSlide(secondary?.body ?? [],bones,weighted),
      faceCorrection: data.faceCorrection,
      blink: new Stand3DBlink(data.faceBehavior?.version===1?data.faceBehavior.blink:null),
    };
  }

  private applyPose(
    rig: LoadedRig,
    clip: AnimationClipData | null,
    pose: Stand3DPoseState,
    step = 0,
    fallbackFace?: { clip: AnimationClipData | null; time: number },
  ): void {
    for (const [bone, r] of rig.rest) {
      bone.position.copy(r.position);
      bone.quaternion.copy(r.quaternion);
      bone.scale.copy(r.scale);
    }

    const baked = rig.bodyMotion.apply(clip, pose.clipTime, step, this.reducedMotion);
    if (baked) {
      rig.handContact.apply();
      rig.handClearance.apply(clip,step,this.reducedMotion,pose.clipTime);
      rig.handContact.measure();
      rig.secondary.apply();
      // The legacy Hips pin moves every coat joint and changes segment lengths.
      // Native-length chain dynamics instead retain each joint's bind translation.
      if (!rig.secondary.count) this.constrainCloth(rig);
    }
    if (!baked && clip && clip.times.length > 0) {
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
    if (rig.bodyBones.Head) {
      rig.bodyBones.Head.updateWorldMatrix(true,false);
      this.camera.updateMatrixWorld(true);
      this.actorLighting.actorHeadRightView.value.set(1,0,0)
        .applyQuaternion(rig.bodyBones.Head.getWorldQuaternion(new THREE.Quaternion()))
        .transformDirection(this.camera.matrixWorldInverse);
    }

    const faceClip = clip ? rig.clips.find((c) => c.name === clip.name.replace(/_b$/, "_f")) ?? null : null;
    const nativeFace=sampleActorFace(faceClip ?? fallbackFace?.clip ?? null, faceClip ? pose.clipTime : fallbackFace?.time ?? pose.clipTime);
    const authoredBlink=Math.max(nativeFace['b_eye.eye_001']??0,pose.shapeWeights['b_eye.eye_001']??0);
    const automaticBlink=rig.blink.step(step,authoredBlink,this.reducedMotion);
    nativeFace['b_eye.eye_001']=Math.max(nativeFace['b_eye.eye_001']??0,automaticBlink);
    this.applyFaceShapes(rig, pose, nativeFace, step);

    rig.quartzHair.apply();
    rig.root.updateMatrixWorld(true);
    rig.collision.capture();
    rig.bodySwing.update(step, !this.reducedMotion,clip?.name);
    rig.slide.update(step, !this.reducedMotion);
    rig.swing.update(step, !this.reducedMotion);
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

    this.constrainCloth(rig);
  }

  private constrainCloth(rig: LoadedRig): void {
    const hips = rig.bodyBones.Hips;
    if (!hips) return;
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

  private applyFaceShapes(rig: LoadedRig, pose: Stand3DPoseState, native: Record<string, number> = {}, step = 0): void {
    const { faceMesh, faceSource, shapeByName } = rig;
    if (!faceMesh || !faceSource) return;

    const active: Array<[BlendShapeEntry, number]> = [];
    const source=rig.expression.enabled?{...native,"b_eye.eye_001":Math.max(native["b_eye.eye_001"]??0,pose.shapeWeights["b_eye.eye_001"]??0)}:native;
    const expression=rig.expression.apply(source,this.direction.mood,step,this.reducedMotion);
    const weights = { ...blendActorFace(expression, rig.expression.enabled?{}:pose.shapeWeights, pose.mouthOpen), ...cameraFaceWeights(rig.faceCorrection,rig.bones,this.camera) };
    this.actorLighting.actorBlink.value = weights["b_eye.eye_001"] ?? 0;
    for (const [name, weight] of Object.entries(weights)) {
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
    // Source facial shapes contain position deltas only. Preserve the authored
    // normal field, as in the verified Unity reference (null normal deltas).
    // Legacy assets without normals still need geometric reconstruction.
    if (faceSource.normals?.length !== baseVertices.length) faceMesh.geometry.computeVertexNormals();
  }

  private disposeRig(rig: LoadedRig): void {
    this.scene.remove(rig.root);
    rig.actorShadow?.dispose();
    for (const mesh of rig.meshes) {
      mesh.geometry.dispose();
      mesh.skeleton?.dispose();
    }
    for (const mat of rig.materials) {
      mat.dispose();
    }
    for(const mat of rig.outlineMaterials??[])mat.dispose();
    for (const tex of rig.textures) {
      tex.dispose();
    }
  }
}
