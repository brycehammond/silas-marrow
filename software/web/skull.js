// The on-screen Silas. Draws the skull and moves it from the /api/pose event
// stream, which carries the same pan, tilt, jaw and eye state the Arduino would act on.
//
// Test switches (query string):
//   demo=1                 no server needed, the skull moves by itself
//   pose=pan,tilt,jaw,eyes hold one pose, in the same units as the serial protocol
//   cam=front|side|34|low  camera position

import * as THREE from 'three';
import { buildSkull, ANCHORS } from '/web/skullgeo.js';

const query = new URLSearchParams(location.search);
const token = query.get('t') || '';
const withToken = path => path + (token ? '?t=' + encodeURIComponent(token) : '');
const $ = id => document.getElementById(id);

const cfg = { pan_range_deg: 60, tilt_range_deg: 25, jaw_open_deg: 24,
              invert_pan: false, invert_tilt: false, model: null, camera_inset: true };
const pose = { pan: 0, tilt: 0, jaw: 0, eye_mode: 1, eye_rgb: [255, 32, 0], servos: true };

// ------------------------------------------------------------------- scene
const renderer = new THREE.WebGLRenderer({ canvas: $('view'), antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(26, 1, 0.1, 50);

scene.add(new THREE.HemisphereLight(0x8a7a6a, 0x120c08, 0.55));
const key = new THREE.DirectionalLight(0xffe2bd, 2.6);      // lamp light, up and to one side
key.position.set(-2.2, 3.0, 3.4);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
Object.assign(key.shadow.camera, { left: -1.8, right: 1.8, top: 1.8, bottom: -2.2, near: 0.5, far: 12 });
key.shadow.bias = -0.0004;
key.shadow.normalBias = 0.012;
scene.add(key);
const rim = new THREE.DirectionalLight(0x6f8fc0, 1.5);      // cold light from behind
rim.position.set(2.6, 1.4, -3.0);
scene.add(rim);
const fill = new THREE.DirectionalLight(0xc98a5a, 0.35);
fill.position.set(2.5, -0.5, 2.5);
scene.add(fill);

// Stand: a post on a dark wooden foot, like the printed base.
const wood = new THREE.MeshStandardMaterial({ color: 0x2a1a10, roughness: 0.7 });
const brass = new THREE.MeshStandardMaterial({ color: 0x8a6a3a, roughness: 0.45, metalness: 0.8 });
const foot = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.70, 0.16, 48), wood);
foot.position.y = -1.62;
foot.receiveShadow = true;
scene.add(foot);

const panPivot = new THREE.Group();
const tiltPivot = new THREE.Group();
tiltPivot.position.fromArray(ANCHORS.tilt);
const post = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.06, 1.16, 24), brass);
post.position.set(0, -1.0, ANCHORS.tilt[2]);
post.castShadow = true;
const collar = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.035, 32), brass);
collar.position.set(0, -1.53, ANCHORS.tilt[2]);
panPivot.add(post, collar, tiltPivot);
scene.add(panPivot);

const headHolder = new THREE.Group();                        // undoes the pivot offset
headHolder.position.fromArray(ANCHORS.tilt).negate();
tiltPivot.add(headHolder);

// ---------------------------------------------------------------- the skull
let jawPivot = null;
const eyes = [];

function glowTexture(stops) {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  for (const [at, alpha] of stops) grad.addColorStop(at, `rgba(255,255,255,${alpha})`);
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

function addEyes(parent, points) {
  const soft = glowTexture([[0, 1], [0.25, 0.45], [0.6, 0.10], [1, 0]]);
  const hot = glowTexture([[0, 1], [0.35, 0.9], [0.7, 0.25], [1, 0]]);
  const sprite = map => new THREE.Sprite(new THREE.SpriteMaterial({
    map, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: 0 }));
  points.forEach((p, n) => {
    // The unlit LED dome, a coal on it, and the glow around it.
    const dome = new THREE.Mesh(new THREE.SphereGeometry(0.075, 24, 16),
      new THREE.MeshStandardMaterial({ color: 0x1a1512, roughness: 0.6 }));
    dome.position.copy(p).add(new THREE.Vector3(0, 0, -0.10));
    const ember = sprite(hot);
    ember.position.copy(p);
    parent.add(dome);
    // Short reach: it should light the socket, not the inside of the mouth.
    const lamp = new THREE.PointLight(0xff2000, 0, 0.46, 2);
    lamp.position.copy(p).add(new THREE.Vector3(0, 0, 0.13));
    const halo = sprite(soft);
    halo.position.copy(p).add(new THREE.Vector3(0, 0, 0.12));
    parent.add(ember, lamp, halo);
    eyes.push({ ember, lamp, halo, first: n * 7 });
  });
}

async function loadModel() {
  // A sculpted model wins if one has been dropped in web/. See the README.
  try {
    if (!cfg.model) throw new Error('none');       // the server only names a file that exists
    const url = '/web/' + cfg.model;
    const { GLTFLoader } = await import('/web/vendor/loaders/GLTFLoader.js');
    const gltf = await new GLTFLoader().loadAsync(url);
    const find = name => gltf.scene.getObjectByName(name);
    const jaw = find('jaw'), cranium = find('cranium');
    if (!jaw || !cranium) throw new Error('model needs nodes named cranium and jaw');
    gltf.scene.updateMatrixWorld(true);
    // Fit it to the space the built-in skull takes: 2 units tall, chin at the same
    // height, face at the same depth, centered left to right.
    const box = new THREE.Box3().setFromObject(gltf.scene);
    const scale = 2.0 / (box.max.y - box.min.y);
    const holder = new THREE.Group();
    holder.scale.setScalar(scale);
    holder.position.set(-scale * (box.min.x + box.max.x) / 2,
                        -0.95 - scale * box.min.y, 0.88 - scale * box.max.z);
    holder.add(gltf.scene);
    gltf.scene.traverse(o => { if (o.isMesh) o.castShadow = o.receiveShadow = true; });
    headHolder.add(holder);
    holder.updateMatrixWorld(true);
    const points = ['eye_L', 'eye_R'].map((name, n) => {
      const node = find(name);
      return node ? headHolder.worldToLocal(node.getWorldPosition(new THREE.Vector3()))
                  : new THREE.Vector3(...ANCHORS.eyes[n]);
    });
    addEyes(headHolder, points);
    return jaw;
  } catch (e) {
    if (e.message !== 'none') console.warn('Using the built-in skull:', e.message);
    const built = buildSkull();
    headHolder.add(built.head);
    addEyes(built.head, built.eyes);
    return built.jawPivot;
  }
}

// ------------------------------------------------------------------ motion
const rad = THREE.MathUtils.degToRad;
const shown = { pan: 0, tilt: 0, jaw: 0, level: 0 };

// Same numbers as updateEyes() in the Arduino sketch.
function eyeLevel(mode, jaw, ms) {
  switch (mode) {
    case 0: return 0;
    case 1: return 0.18 + 0.12 * Math.sin(ms / 900);
    case 2: return 0.55;
    case 3: return 0.35 + 0.65 * jaw / 100 + 0.05 * Math.sin(ms / 37);
    case 4: return 0.40 + 0.15 * Math.sin(ms / 250);
    default: return 0.3;
  }
}
function flicker(first, ms) {                      // mean of one 7-LED jewel
  let sum = 0;
  for (let i = first; i < first + 7; i++) {
    const f = 0.85 + 0.15 * ((i * 73 + Math.floor(ms / 60)) % 17) / 16;
    sum += i % 7 === 0 ? Math.min(1, f * 1.2) : f;
  }
  return sum / 7;
}

const color = new THREE.Color(), white = new THREE.Color(1, 1, 1);
const X_AXIS = new THREE.Vector3(1, 0, 0), swing = new THREE.Quaternion();
let jawRest = new THREE.Quaternion();
function frame(ms, dt) {
  const ease = 1 - Math.exp(-dt * 28);             // hides network jitter, adds ~35 ms
  const jawEase = 1 - Math.exp(-dt * 60);
  shown.pan += (pose.pan - shown.pan) * ease;
  shown.tilt += (pose.tilt - shown.tilt) * ease;
  shown.jaw += (pose.jaw - shown.jaw) * jawEase;

  panPivot.rotation.y = -rad(shown.pan / 100 * cfg.pan_range_deg) * (cfg.invert_pan ? -1 : 1);
  tiltPivot.rotation.x = -rad(shown.tilt / 100 * cfg.tilt_range_deg) * (cfg.invert_tilt ? -1 : 1);
  if (jawPivot) {                                  // swing about the hinge, from its rest pose
    swing.setFromAxisAngle(X_AXIS, rad(shown.jaw / 100 * cfg.jaw_open_deg));
    jawPivot.quaternion.copy(jawRest).multiply(swing);
  }

  const level = Math.max(0, Math.min(1, eyeLevel(pose.eye_mode, shown.jaw, ms)));
  shown.level += (level - shown.level) * (1 - Math.exp(-dt * 20));
  color.setRGB(pose.eye_rgb[0] / 255, pose.eye_rgb[1] / 255, pose.eye_rgb[2] / 255, THREE.SRGBColorSpace);
  for (const eye of eyes) {
    const l = shown.level * flicker(eye.first, ms);
    eye.ember.material.color.copy(color).lerp(white, 0.55 * l);   // hotter means whiter
    eye.ember.material.opacity = Math.min(1, 0.25 + 1.6 * l) * (l > 0.001 ? 1 : 0);
    eye.ember.scale.setScalar(0.15 + 0.10 * l);
    eye.lamp.color.copy(color);
    eye.lamp.intensity = 0.11 * l;
    eye.halo.material.color.copy(color);
    eye.halo.material.opacity = Math.min(1, 0.8 * l);
    eye.halo.scale.setScalar(0.36 + 0.34 * l);
  }
}

// ------------------------------------------------------------------ camera
const VIEWS = {
  front: [0, -0.05, 1], '34': [0.62, 0.05, 0.78], side: [1, 0, 0.02], low: [0.35, -0.45, 0.85],
};
function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  // Keep the skull and its stand in view, in portrait as well.
  const halfHeight = 1.55, halfWidth = 1.05;
  const tan = Math.tan(rad(camera.fov / 2));
  const dist = Math.max(halfHeight / tan, halfWidth / (tan * camera.aspect));
  const dir = new THREE.Vector3(...(VIEWS[query.get('cam')] || VIEWS.front)).normalize();
  const target = new THREE.Vector3(0, -0.32, 0.05);
  camera.position.copy(target).addScaledVector(dir, dist);
  camera.lookAt(target);
  camera.updateProjectionMatrix();
}
addEventListener('resize', resize);

// ----------------------------------------------------------------- overlay
const ui = { chip: $('chip'), state: $('state'), line: $('line'), cam: $('cam'), keys: $('keys') };
let lineTimer = 0, status = {};

function showLine(text, heard) {
  if (!text) return;
  ui.line.textContent = heard ? '“' + text + '”' : text;
  ui.line.classList.toggle('heard', !!heard);
  ui.line.classList.add('on');
  clearTimeout(lineTimer);
  lineTimer = setTimeout(() => ui.line.classList.remove('on'), 2500 + 60 * text.length);
}
function setState(name, label) {
  ui.chip.dataset.state = name;
  ui.state.textContent = label || name;
}
function onStatus(s) {
  // The counters tick on every line, so a repeated sentence still shows.
  // Nothing is shown for lines from before this page connected.
  if (status.state) {
    if (s.said && s.said_n !== status.said_n) showLine(s.said, false);
    if (s.heard && s.heard_n !== status.heard_n) showLine(s.heard, true);
  }
  status = s;
  showState();
}
function showState() {
  if (!status.state) return;
  const resting = !pose.servos ? 'servos relaxed' : status.armed ? 'armed' : 'resting';
  setState(status.state, status.state === 'idle' ? resting : status.state);
}
function toggleCamera(on) {
  ui.cam.classList.toggle('on', on);
  ui.cam.src = on ? withToken('/stream') : '';      // dropping src closes the stream
}
addEventListener('keydown', e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === 'f') document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
  if (k === 'h') document.body.classList.toggle('bare');
  if (k === 'c') toggleCamera(!ui.cam.classList.contains('on'));
});
setTimeout(() => ui.keys.classList.add('gone'), 6000);

// -------------------------------------------------------------------- feed
function connect() {
  // Resolves once the settings are in, or after 2 s so a dead server still shows a skull.
  return new Promise(done => {
    const feed = new EventSource(withToken('/api/pose'));
    let first = true;
    feed.addEventListener('config', e => {
      Object.assign(cfg, JSON.parse(e.data));
      if (first) { toggleCamera(cfg.camera_inset); first = false; }
      done();
    });
    feed.addEventListener('pose', e => {
      const was = pose.servos;
      Object.assign(pose, JSON.parse(e.data));
      if (pose.servos !== was) showState();
    });
    feed.addEventListener('status', e => onStatus(JSON.parse(e.data)));
    feed.onerror = () => {                                 // EventSource retries by itself
      setState('offline', 'offline');
      status = {};
    };
    setTimeout(done, 2000);
  });
}

function demo(ms) {
  const t = ms / 1000;
  pose.pan = 70 * Math.sin(t * 0.5);
  pose.tilt = 40 * Math.sin(t * 0.31 + 1);
  const talking = (t % 8) < 5;
  pose.jaw = talking ? 100 * Math.abs(Math.sin(t * 13)) * (0.5 + 0.5 * Math.sin(t * 1.9) ** 2) : 0;
  pose.eye_mode = talking ? 3 : 1;
}

// --------------------------------------------------------------------- run
async function main() {
  resize();
  const fixed = query.get('pose');
  if (fixed) {
    const [pan, tilt, jaw, eye_mode = 2] = fixed.split(',').map(Number);
    Object.assign(pose, { pan, tilt, jaw, eye_mode });
    Object.assign(shown, { pan, tilt, jaw });
    setState('idle', 'posed');
  } else if (query.get('demo')) {
    setState('speaking', 'demo');
  } else {
    await connect();
  }
  await new Promise(r => setTimeout(r, 30));         // let "Raising the dead" paint first
  jawPivot = await loadModel();
  jawRest = jawPivot.quaternion.clone();
  $('wake').classList.add('gone');
  setTimeout(() => $('wake').remove(), 1000);
  document.body.dataset.ready = '1';
  window.silas = { pose, shown, cfg, eyes, scene, camera, renderer, panPivot, tiltPivot, jawPivot };   // for poking at it in the console

  let last = null;
  renderer.setAnimationLoop(now => {
    // Frame times can run backwards on the first frame. Never ease by a negative step.
    const dt = last === null ? 0 : Math.max(0, Math.min(0.1, (now - last) / 1000));
    last = now;
    if (query.get('demo')) demo(now);
    frame(now, dt);
    renderer.render(scene, camera);
  });
}
main();
