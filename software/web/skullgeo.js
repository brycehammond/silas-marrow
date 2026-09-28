// Procedural skull for the virtual Silas.
//
// The cranium and the jaw are each described as a signed distance function
// (a sum of soft blobs with cavities carved out), meshed once at load with
// naive surface nets. Teeth are separate little meshes set along the dental arch.
//
// Units: 1 = 10 cm. The skull faces +Z, Y is up, and the ear holes sit near z = 0.

import * as THREE from 'three';

// Points the viewer needs.
export const ANCHORS = {
  hinge: [0, -0.10, 0.06],          // jaw axis, through both jaw joints
  tilt: [0, -0.42, -0.05],          // tilt axis, where the cradle holds the skull
  eyes: [[-0.33, 0.17, 0.50], [0.33, 0.17, 0.50]],
};
const OCCLUSAL_Y = -0.53;           // where upper and lower teeth meet

// ---------------------------------------------------------------- SDF pieces
const smin = (a, b, k) => {
  const h = Math.max(k - Math.abs(a - b), 0) / k;
  return Math.min(a, b) - h * h * k * 0.25;
};
const smax = (a, b, k) => -smin(-a, -b, k);

function ellipsoid(x, y, z, cx, cy, cz, rx, ry, rz) {
  const ax = (x - cx) / rx, ay = (y - cy) / ry, az = (z - cz) / rz;
  const k0 = Math.sqrt(ax * ax + ay * ay + az * az);
  if (k0 < 1e-6) return -Math.min(rx, ry, rz);
  const bx = ax / rx, by = ay / ry, bz = az / rz;
  return k0 * (k0 - 1) / Math.sqrt(bx * bx + by * by + bz * bz);
}

function capsule(x, y, z, ax, ay, az, bx, by, bz, r) {
  const px = x - ax, py = y - ay, pz = z - az;
  const ex = bx - ax, ey = by - ay, ez = bz - az;
  let h = (px * ex + py * ey + pz * ez) / (ex * ex + ey * ey + ez * ez);
  h = Math.max(0, Math.min(1, h));
  const dx = px - ex * h, dy = py - ey * h, dz = pz - ez * h;
  return Math.sqrt(dx * dx + dy * dy + dz * dz) - r;
}

function roundBox(x, y, z, cx, cy, cz, hx, hy, hz, r) {
  const qx = Math.abs(x - cx) - hx + r, qy = Math.abs(y - cy) - hy + r,
        qz = Math.abs(z - cz) - hz + r;
  const ox = Math.max(qx, 0), oy = Math.max(qy, 0), oz = Math.max(qz, 0);
  return Math.sqrt(ox * ox + oy * oy + oz * oz) + Math.min(Math.max(qx, qy, qz), 0) - r;
}

// Horizontal distance to a dental arch: half an ellipse in front, straight legs behind.
function archDistance(x, z, a, b, z0, legs) {
  const ax = Math.abs(x);
  if (z >= z0) {
    const qx = ax / a, qz = (z - z0) / b;
    const r = Math.sqrt(qx * qx + qz * qz);
    if (r < 1e-6) return -Math.min(a, b);
    // scale the radial error back to world units along this direction
    return (r - 1) * Math.sqrt((ax * ax + (z - z0) * (z - z0))) / r;
  }
  const dz = Math.max(0, (z0 - legs) - z);
  const dx = ax - a;
  return dz > 0 ? Math.sign(dx || 1) * Math.sqrt(dx * dx + dz * dz) : dx;
}

const UPPER_ARCH = { a: 0.300, b: 0.400, z0: 0.43, legs: 0.10 };
const LOWER_ARCH = { a: 0.285, b: 0.375, z0: 0.43, legs: 0.10 };

function orbit(x, y, z) {
  return ellipsoid(x, y, z, 0.33, 0.17, 0.76, 0.205, 0.175, 0.36);
}
function noseHole(x, y, z) {                       // narrow on top, two lobes at the bottom
  const top = ellipsoid(x, y, z, 0, -0.05, 0.86, 0.055, 0.13, 0.30);
  return smin(top, ellipsoid(x, y, z, 0.062, -0.205, 0.86, 0.085, 0.095, 0.30), 0.05);
}
// How far inside an eye socket or the nose a point is. 0 outside.
function hollow(x0, y, z) {
  const x = Math.abs(x0);
  return Math.max(0, -orbit(x, y, z), -noseHole(x, y, z));
}

function craniumSDF(x0, y, z) {
  const x = Math.abs(x0);
  // braincase
  let d = ellipsoid(x, y, z, 0, 0.40, -0.10, 0.70, 0.65, 0.86);
  d = smin(d, ellipsoid(x, y, z, 0, 0.43, 0.24, 0.60, 0.50, 0.58), 0.16);      // forehead
  d = smin(d, ellipsoid(x, y, z, 0, 0.16, -0.62, 0.50, 0.42, 0.42), 0.22);     // back of the head
  // middle of the face
  d = smin(d, roundBox(x, y, z, 0, -0.06, 0.55, 0.40, 0.40, 0.25, 0.17), 0.12);
  // temples pinch in behind the eyes
  d = smax(d, -ellipsoid(x, y, z, 0.83, 0.10, 0.34, 0.22, 0.36, 0.34), 0.12);
  // brow
  d = smin(d, capsule(x, y, z, 0, 0.395, 0.795, 0.50, 0.35, 0.65, 0.075), 0.08);
  // outer rim of the eye socket, running down into the cheekbone
  d = smin(d, capsule(x, y, z, 0.545, 0.33, 0.62, 0.555, -0.04, 0.61, 0.068), 0.06);
  d = smin(d, ellipsoid(x, y, z, 0.49, -0.13, 0.63, 0.18, 0.13, 0.15), 0.08);
  // cheekbone arch back to the ear
  d = smin(d, capsule(x, y, z, 0.60, -0.11, 0.56, 0.655, -0.085, 0.24, 0.042), 0.05);
  d = smin(d, capsule(x, y, z, 0.655, -0.085, 0.24, 0.60, -0.07, -0.04, 0.042), 0.05);
  d = smin(d, ellipsoid(x, y, z, 0.52, -0.07, -0.08, 0.13, 0.09, 0.15), 0.09);  // where it roots
  d = smin(d, ellipsoid(x, y, z, 0.57, -0.22, -0.15, 0.085, 0.15, 0.11), 0.08);  // behind the ear
  // upper jaw: a ridge that follows the teeth
  const ua = archDistance(x, z, UPPER_ARCH.a - 0.01, UPPER_ARCH.b - 0.01, UPPER_ARCH.z0, 0.16);
  const uy = (y + 0.335) * 0.55;
  d = smin(d, Math.sqrt(ua * ua + uy * uy) - 0.062, 0.09);
  d = smin(d, ellipsoid(x, y, z, 0, -0.30, 0.50, 0.30, 0.13, 0.30), 0.08);      // palate roof
  // bridge of the nose
  d = smin(d, capsule(x, y, z, 0, 0.27, 0.815, 0, 0.03, 0.895, 0.055), 0.06);

  d = smax(d, -orbit(x, y, z), 0.05);
  d = smax(d, -noseHole(x, y, z), 0.03);
  // hollow under the cheekbone
  d = smax(d, -ellipsoid(x, y, z, 0.58, -0.40, 0.30, 0.20, 0.22, 0.34), 0.08);
  // room for the mouth and throat underneath
  d = smax(d, -ellipsoid(x, y, z, 0, -0.60, 0.36, 0.235, 0.24, 0.36), 0.05);
  return d;
}

function jawSDF(x0, y, z) {
  const x = Math.abs(x0);
  // ridge that carries the lower teeth
  const la = archDistance(x, z, LOWER_ARCH.a, LOWER_ARCH.b, LOWER_ARCH.z0, 0.14);
  const ly = (y + 0.745) * 0.50;
  let d = Math.sqrt(la * la + ly * ly) - 0.058;
  // lower border, flaring out to the corner of the jaw
  const yy = 0.62;                                  // squash: tall, thin bone
  const c = (ax, ay, az, bx, by, bz, r) =>
    capsule(x, y * yy, z, ax, ay * yy, az, bx, by * yy, bz, r);
  let body = c(0, -0.86, 0.760, 0.15, -0.85, 0.725, 0.050);
  body = smin(body, c(0.15, -0.85, 0.725, 0.32, -0.80, 0.50, 0.048), 0.08);
  body = smin(body, c(0.32, -0.80, 0.50, 0.43, -0.74, 0.22, 0.046), 0.08);
  body = smin(body, c(0.43, -0.74, 0.22, 0.485, -0.68, 0.04, 0.046), 0.08);
  d = smin(d, body, 0.075);
  // chin
  d = smin(d, ellipsoid(x, y, z, 0, -0.85, 0.785, 0.10, 0.055, 0.05), 0.07);
  // the upright part that reaches the jaw joint
  const zz = 0.36;                                  // squash: wide front to back
  const r = (ax, ay, az, bx, by, bz, rad) =>
    capsule(x, y, z * zz, ax, ay, az * zz, bx, by, bz * zz, rad);
  let ramus = r(0.50, -0.64, 0.12, 0.535, -0.20, 0.13, 0.042);
  d = smin(d, ramus, 0.07);
  d = smin(d, ellipsoid(x, y, z, 0.49, -0.68, 0.06, 0.05, 0.09, 0.10), 0.06);   // corner
  d = smin(d, capsule(x, y, z, 0.535, -0.22, 0.07, 0.545, -0.12, 0.06, 0.05), 0.04); // joint knob
  d = smin(d, capsule(x, y, z, 0.53, -0.26, 0.24, 0.53, -0.10, 0.30, 0.03), 0.04);   // front prong
  return d;
}

// ------------------------------------------------------------- surface nets
function surfaceNets(sdf, min, max, h) {
  const n = [0, 1, 2].map(i => Math.ceil((max[i] - min[i]) / h) + 1);
  const [nx, ny, nz] = n;
  const grid = new Float32Array(nx * ny * nz);
  const at = (i, j, k) => i + nx * (j + ny * k);
  for (let k = 0; k < nz; k++) {
    const z = min[2] + k * h;
    for (let j = 0; j < ny; j++) {
      const y = min[1] + j * h;
      for (let i = 0; i < nx; i++) grid[at(i, j, k)] = sdf(min[0] + i * h, y, z);
    }
  }

  const index = new Int32Array(nx * ny * nz).fill(-1);
  const pos = [];
  const corner = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0],
                  [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
  const edges = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3],
                 [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];
  const v = new Float32Array(8);
  for (let k = 0; k < nz - 1; k++) for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
    let inside = 0;
    for (let c = 0; c < 8; c++) {
      v[c] = grid[at(i + corner[c][0], j + corner[c][1], k + corner[c][2])];
      if (v[c] < 0) inside++;
    }
    if (inside === 0 || inside === 8) continue;
    let sx = 0, sy = 0, sz = 0, count = 0;
    for (const [a, b] of edges) {
      if ((v[a] < 0) === (v[b] < 0)) continue;
      const t = v[a] / (v[a] - v[b]);
      sx += corner[a][0] + (corner[b][0] - corner[a][0]) * t;
      sy += corner[a][1] + (corner[b][1] - corner[a][1]) * t;
      sz += corner[a][2] + (corner[b][2] - corner[a][2]) * t;
      count++;
    }
    index[at(i, j, k)] = pos.length / 3;
    pos.push(min[0] + (i + sx / count) * h, min[1] + (j + sy / count) * h,
             min[2] + (k + sz / count) * h);
  }

  const tris = [];
  const step = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  for (let k = 1; k < nz - 1; k++) for (let j = 1; j < ny - 1; j++) for (let i = 1; i < nx - 1; i++) {
    const v0 = grid[at(i, j, k)];
    for (let a = 0; a < 3; a++) {
      const v1 = grid[at(i + step[a][0], j + step[a][1], k + step[a][2])];
      if ((v0 < 0) === (v1 < 0)) continue;
      const u = step[(a + 1) % 3], w = step[(a + 2) % 3];
      const c0 = index[at(i, j, k)];
      const c1 = index[at(i - u[0], j - u[1], k - u[2])];
      const c2 = index[at(i - u[0] - w[0], j - u[1] - w[1], k - u[2] - w[2])];
      const c3 = index[at(i - w[0], j - w[1], k - w[2])];
      if (c0 < 0 || c1 < 0 || c2 < 0 || c3 < 0) continue;
      if (v0 < 0) tris.push(c0, c1, c2, c0, c2, c3);
      else tris.push(c0, c2, c1, c0, c3, c2);
    }
  }
  return { pos: new Float32Array(pos), tris };
}

// Cheap repeatable noise for bone mottling.
function hash(i, j, k) {
  let n = (i * 374761393 + j * 668265263 + k * 1274126177) | 0;
  n = Math.imul(n ^ (n >>> 13), 1274126177);
  return ((n ^ (n >>> 16)) >>> 0) / 4294967295;
}
function noise(x, y, z) {
  const i = Math.floor(x), j = Math.floor(y), k = Math.floor(z);
  const fx = x - i, fy = y - j, fz = z - k;
  const s = t => t * t * (3 - 2 * t);
  const ux = s(fx), uy = s(fy), uz = s(fz);
  const l = (a, b, t) => a + (b - a) * t;
  return l(l(l(hash(i, j, k), hash(i + 1, j, k), ux), l(hash(i, j + 1, k), hash(i + 1, j + 1, k), ux), uy),
           l(l(hash(i, j, k + 1), hash(i + 1, j, k + 1), ux), l(hash(i, j + 1, k + 1), hash(i + 1, j + 1, k + 1), ux), uy), uz);
}

const BONE = [0.86, 0.80, 0.66], UMBER = [0.17, 0.11, 0.06];

function boneGeometry(sdf, min, max, h, occluder = sdf, hollow = null) {
  const { pos, tris } = surfaceNets(sdf, min, max, h);
  const count = pos.length / 3;
  const normal = new Float32Array(pos.length), color = new Float32Array(pos.length);
  const e = h * 0.5;
  for (let i = 0; i < count; i++) {
    const x = pos[3 * i], y = pos[3 * i + 1], z = pos[3 * i + 2];
    let nx = sdf(x + e, y, z) - sdf(x - e, y, z);
    let ny = sdf(x, y + e, z) - sdf(x, y - e, z);
    let nz = sdf(x, y, z + e) - sdf(x, y, z - e);
    const len = Math.hypot(nx, ny, nz) || 1;
    nx /= len; ny /= len; nz /= len;
    // (the smooth normal is kept for the occlusion test below)
    const f = 46, b = 0.055;
    const rx = nx + b * (noise(x * f + 0.5, y * f, z * f) - noise(x * f - 0.5, y * f, z * f));
    const ry = ny + b * (noise(x * f, y * f + 0.5, z * f) - noise(x * f, y * f - 0.5, z * f));
    const rz = nz + b * (noise(x * f, y * f, z * f + 0.5) - noise(x * f, y * f, z * f - 0.5));
    const rl = Math.hypot(rx, ry, rz) || 1;
    normal.set([rx / rl, ry / rl, rz / rl], 3 * i);
    // How boxed in is this spot? Dirt settles in the hollows.
    let occ = 0, weight = 1;
    for (let s = 1; s <= 5; s++) {
      const dist = 0.035 * s;
      occ += weight * Math.max(0, dist - occluder(x + nx * dist, y + ny * dist, z + nz * dist));
      weight *= 0.62;
    }
    const open = Math.max(0, Math.min(1, 1 - 7.0 * occ));
    const mottle = 0.80 + 0.20 * noise(x * 9, y * 9, z * 9) * (0.6 + 0.4 * noise(x * 31, y * 31, z * 31));
    const stain = 0.88 + 0.12 * noise(x * 2.3 + 7, y * 2.3, z * 2.3);
    let t = Math.pow(open, 1.3);
    if (hollow) t *= 1 - 0.9 * Math.min(1, hollow(x, y, z) / 0.10);   // sockets go dark inside
    for (let c = 0; c < 3; c++)
      color[3 * i + c] = (UMBER[c] + (BONE[c] - UMBER[c]) * t) * mottle * stain;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.BufferAttribute(normal, 3));
  g.setAttribute('color', new THREE.BufferAttribute(color, 3));
  g.setIndex(tris);
  g.computeBoundingSphere();
  return g;
}

// -------------------------------------------------------------------- teeth
// [width, height, thickness] from the middle outward
const TEETH = [
  [0.090, 0.135, 0.052], [0.072, 0.122, 0.050], [0.076, 0.140, 0.068],
  [0.068, 0.110, 0.080], [0.068, 0.106, 0.082],
  [0.102, 0.100, 0.102], [0.098, 0.096, 0.100],
];

function toothGeometry() {
  const g = new THREE.SphereGeometry(0.5, 14, 10);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const boxy = v => Math.sign(v) * Math.pow(Math.abs(v) * 2, 0.55) / 2;
    p.setXYZ(i, boxy(p.getX(i)), boxy(p.getY(i)), boxy(p.getZ(i)));
  }
  g.computeVertexNormals();
  return g;
}

function archPoint(arch, s) {
  // s is distance along the arch from the middle, signed
  const { a, b, z0 } = arch;
  const quarter = archPoint.len(arch);
  const side = Math.sign(s) || 1, dist = Math.abs(s);
  if (dist > quarter) return { x: side * a, z: z0 - (dist - quarter) };   // straight leg
  // walk the ellipse
  let t = 0, run = 0;
  const dt = 0.002;
  while (run < dist) {
    run += Math.hypot(a * Math.cos(t), b * Math.sin(t)) * dt;
    t += dt;
  }
  return { x: side * a * Math.sin(t), z: z0 + b * Math.cos(t), t };
}
archPoint.len = ({ a, b }) => {
  let run = 0;
  for (let t = 0; t < Math.PI / 2; t += 0.002) run += Math.hypot(a * Math.cos(t), b * Math.sin(t)) * 0.002;
  return run;
};

function teeth(arch, upper, material) {
  const group = new THREE.Group();
  const geo = toothGeometry();
  const scale = upper ? 1 : 0.94;
  for (const side of [-1, 1]) {
    let s = 0;
    TEETH.forEach(([w, hgt, thick], n) => {
      w *= scale; thick *= scale;
      const c = archPoint(arch, side * (s + w / 2));
      s += w * 0.97;
      // outward direction of the arch at this tooth
      let ox, oz;
      if (c.t === undefined) { ox = side; oz = 0; }
      else {
        ox = side * Math.sin(c.t) / arch.a; oz = Math.cos(c.t) / arch.b;
        const l = Math.hypot(ox, oz); ox /= l; oz /= l;
      }
      const m = new THREE.Mesh(geo, material);
      const lean = upper ? 0.10 : 0.06;                    // front teeth lean out a little
      const front = Math.max(0, 1 - n / 3);
      const h = hgt * (upper ? 1 : 0.92);
      const cy = upper ? OCCLUSAL_Y + h * 0.5 - 0.004 : OCCLUSAL_Y - h * 0.5 + 0.004;
      m.position.set(c.x, cy, c.z);
      const out = new THREE.Vector3(ox, 0, oz);
      const up = new THREE.Vector3(0, 1, 0).addScaledVector(out, (upper ? -1 : 1) * lean * front).normalize();
      const along = new THREE.Vector3().crossVectors(up, out).normalize();
      const out2 = new THREE.Vector3().crossVectors(along, up);
      m.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(along, up, out2));
      m.scale.set(w * 0.98, h, thick);
      m.castShadow = m.receiveShadow = true;
      group.add(m);
    });
  }
  return group;
}

// -------------------------------------------------------------------- build
export function buildSkull() {
  const bone = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.82, metalness: 0 });
  const ivory = new THREE.MeshStandardMaterial({ color: 0xd9cba6, roughness: 0.5, metalness: 0 });

  const both = (x, y, z) => Math.min(craniumSDF(x, y, z), jawSDF(x, y, z));
  const cranium = new THREE.Mesh(
    boneGeometry(craniumSDF, [-0.86, -0.64, -1.10], [0.86, 1.12, 0.98], 0.0165, both, hollow), bone);
  const jaw = new THREE.Mesh(
    boneGeometry(jawSDF, [-0.66, -1.02, -0.12], [0.66, 0.02, 0.92], 0.0140, both), bone);
  for (const m of [cranium, jaw]) m.castShadow = m.receiveShadow = true;

  const head = new THREE.Group();
  head.add(cranium, teeth(UPPER_ARCH, true, ivory));

  // The jaw swings about the hinge, so its parts live in hinge-relative space.
  const jawPivot = new THREE.Group();
  jawPivot.position.fromArray(ANCHORS.hinge);
  const jawParts = new THREE.Group();
  jawParts.position.fromArray(ANCHORS.hinge).negate();
  jawParts.add(jaw, teeth(LOWER_ARCH, false, ivory));
  jawPivot.add(jawParts);
  head.add(jawPivot);

  return { head, jawPivot, eyes: ANCHORS.eyes.map(e => new THREE.Vector3(...e)) };
}
