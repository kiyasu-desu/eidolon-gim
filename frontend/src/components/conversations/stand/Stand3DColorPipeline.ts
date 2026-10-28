import * as THREE from "three";
import { ACTOR_LUT_GLSL } from "./Stand3DColorLUT";

export type ActorColorWorkflow = "linear" | "gamma-reference";

// Original PlayerSettings requests Linear, and color textures are marked sRGB.
// Composite actor passes in linear light and encode the completed image once.
// Gamma mode reproduces the old isolated reference, not the original client.
export class Stand3DColorPipeline {
  private target: THREE.WebGLRenderTarget | null = null;
  private outputScene: THREE.Scene | null = null;
  private outputCamera = new THREE.Camera();
  private quad: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial> | null = null;
  private size = new THREE.Vector2();
  readonly hdr: boolean;

  constructor(private renderer: THREE.WebGLRenderer, readonly mode: ActorColorWorkflow = "linear") {
    this.hdr = mode === "linear" && renderer.extensions.has("EXT_color_buffer_float");
    if (mode !== "linear") return;
    this.target = new THREE.WebGLRenderTarget(1, 1, {
      type: this.hdr ? THREE.HalfFloatType : THREE.UnsignedByteType,
      format: THREE.RGBAFormat, colorSpace: THREE.LinearSRGBColorSpace, depthBuffer: true,
    });
    // Some mobile GPUs expose float color buffers but fewer MSAA samples for
    // RGBA16F than for RGBA8. Query the actual format rather than MAX_SAMPLES.
    const context = renderer.getContext();
    if ("getInternalformatParameter" in context) {
      const supported = context.getInternalformatParameter(context.RENDERBUFFER,
        this.hdr ? context.RGBA16F : context.RGBA8, context.SAMPLES);
      if (supported instanceof Int32Array) this.target.samples = Math.max(0, ...Array.from(supported).filter(n => n <= 4));
    }
    const material = new THREE.ShaderMaterial({
      uniforms: { source: { value: this.target.texture }, actorLUT: { value: null }, actorLUTEnabled: { value: false }, actorLUTSize: { value: 4 }, actorExposure: { value: 1 } },
      vertexShader: `varying vec2 outputUV; void main() { outputUV=uv; gl_Position=vec4(position.xy,0.0,1.0); }`,
      fragmentShader: `
        uniform sampler2D source;
        uniform sampler3D actorLUT;
        uniform bool actorLUTEnabled;
        uniform float actorLUTSize, actorExposure;
        varying vec2 outputUV;
        ${ACTOR_LUT_GLSL}
        void main() {
          vec4 composed = texture2D(source, outputUV);
          // MSAA coverage is premultiplied. Encode straight color first to
          // avoid bright/dark fringes when compositing the transparent canvas.
          gl_FragColor = vec4(composed.a > 0.00001 ? composed.rgb / composed.a : vec3(0.0), composed.a);
          if (actorLUTEnabled) gl_FragColor.rgb = texture(actorLUT, actorLUTCoordinate(gl_FragColor.rgb, actorLUTSize, actorExposure)).rgb;
          #include <colorspace_fragment>
          gl_FragColor.rgb *= composed.a;
        }
      `,
      blending: THREE.NoBlending, depthTest: false, depthWrite: false, toneMapped: false,
    });
    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
    this.quad.frustumCulled = false;
    this.outputScene = new THREE.Scene();
    this.outputScene.add(this.quad);
  }

  // LUT ownership stays with the loaded rig. A clipped RGBA8 scene buffer
  // cannot preserve HDR grading inputs, so that fallback retains the old path.
  setColorLUT(texture: THREE.Data3DTexture | null, exposure = 1): void {
    if (!this.quad) return;
    const uniforms = this.quad.material.uniforms;
    uniforms.actorLUT.value = texture;
    uniforms.actorLUTEnabled.value = texture !== null && this.hdr;
    uniforms.actorLUTSize.value = texture?.image.width ?? 4;
    uniforms.actorExposure.value = exposure;
  }

  get colorLUTEnabled(): boolean { return this.quad?.material.uniforms.actorLUTEnabled.value === true; }

  render(scene: THREE.Scene, camera: THREE.Camera): void {
    if (!this.target || !this.outputScene) { this.renderer.render(scene, camera); return; }
    this.renderer.getDrawingBufferSize(this.size);
    if (this.target.width !== this.size.x || this.target.height !== this.size.y) this.target.setSize(this.size.x, this.size.y);
    const previous = this.renderer.getRenderTarget();
    try {
      this.renderer.setRenderTarget(this.target);
      this.renderer.render(scene, camera);
      this.renderer.setRenderTarget(previous);
      this.renderer.render(this.outputScene, this.outputCamera);
    } finally { this.renderer.setRenderTarget(previous); }
  }

  dispose(): void {
    this.quad?.geometry.dispose(); this.quad?.material.dispose();
    this.target?.dispose(); this.outputScene?.clear();
  }
}
