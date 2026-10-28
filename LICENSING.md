# Licensing

Eidolon-SC is free software: you can redistribute it and/or modify it under the
terms of the GNU Affero General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. The full text of the license is in the [LICENSE](LICENSE) file.

## Additional permission under GNU AGPL version 3 section 7

If you modify this Program, or any covered work, by linking or combining it
with the Spine Runtimes of Esoteric Software (or a modified version of that
library), containing parts covered by the terms of the Spine Runtimes License,
the licensors of this Program grant you additional permission to convey the
resulting work. Corresponding Source for a non-source form of such a
combination shall include the source code for the parts of the Spine Runtimes
used as well as that of the covered work.

The Spine Runtimes included in `frontend/public/vendor/spine-3.6/` are not part
of this Program and are not covered by the GNU Affero General Public License;
they are distributed under their own license, found in that directory.

## Open Swing Dynamics

The hair/cloth integration and angular projection in `Stand3DSwing.ts`, and the
capsule/line collider conversion and contact projection in `Stand3DCollision.ts`,
the force/coupling calculation in `Stand3DSlide.ts`, and the Quartz hair root
conversion and rotation calculation in `Stand3DQuartzHair.ts`, are adapted from
[Open Swing Dynamics](https://github.com/Arin3000/unity-hair-skirt-dynamics/tree/4d1fa5492961eb09d8f7c5620d9a060f6074caca),
Copyright (c) 2026 Arin3000, under the MIT License. The full notice is preserved in
[`Stand3DSwing.LICENSE`](frontend/src/components/conversations/stand/Stand3DSwing.LICENSE).
