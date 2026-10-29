/** Framing shared by the 3D renderer and its React canvas. */
export type Framing = "knees" | "waist" | "full";

/** The browser cannot render a stand on this device. */
export class StandUnavailable extends Error {}
