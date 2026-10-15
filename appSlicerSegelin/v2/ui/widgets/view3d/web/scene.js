// Studio-style 3D viewport driven from Python (see view3d/three_backend.py).
// Z is up, units are millimetres. Python sends batches of commands through S.run([...]).
import * as THREE from 'three';
import { Line2 } from './vendor/lines/Line2.js';
import { LineGeometry } from './vendor/lines/LineGeometry.js';
import { LineMaterial } from './vendor/lines/LineMaterial.js';
import { LineSegments2 } from './vendor/lines/LineSegments2.js';
import { LineSegmentsGeometry } from './vendor/lines/LineSegmentsGeometry.js';
import { createNavigation, FEEL } from './navigation.js';

const FOV = 35;
const stage = document.getElementById('stage');

let renderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  if (!renderer.getContext()) throw new Error('no WebGL context');
} catch (e) {
  document.title = 'fail:' + (e && e.message ? e.message : e);
  throw e;
}
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
stage.appendChild(renderer.domElement);
renderer.domElement.addEventListener('webglcontextlost', () => { document.title = 'fail:context lost'; });

const scene = new THREE.Scene();
const hemi = new THREE.HemisphereLight(0xffffff, 0x7b8da0, 1.7);
hemi.position.set(0, 0, 1);
scene.add(hemi);
const sun = new THREE.DirectionalLight(0xffffff, 2.6);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.bias = -0.00012;
sun.shadow.normalBias = 0.6;
sun.shadow.radius = 3;
scene.add(sun, sun.target);

const floor = new THREE.Mesh(new THREE.PlaneGeometry(1, 1),
  new THREE.ShadowMaterial({ color: 0x0b1018, opacity: 0.32, transparent: true, depthWrite: false }));
floor.receiveShadow = true;
floor.renderOrder = -2;
scene.add(floor);

const content = new THREE.Group();
scene.add(content);
const groups = new Map([['', content]]);
const objects = new Map();

const persp = new THREE.PerspectiveCamera(FOV, 1, 0.5, 20000);
const ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, -20000, 20000);
persp.up.set(0, 0, 1);
ortho.up.set(0, 0, 1);

let needs = true;
let boundsDirty = true;
const bounds = new THREE.Box3();

// ── helpers ───────────────────────────────────────────────────────────
function f32(b64) { return b64 ? new Float32Array(Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer) : null; }
function u32(b64) { return b64 ? new Uint32Array(Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer) : null; }
function group(name) {
  name = name || '';
  if (!groups.has(name)) { const g = new THREE.Group(); groups.set(name, g); content.add(g); }
  return groups.get(name);
}
function dispose(o) {
  o.traverse(n => {
    if (n.geometry) n.geometry.dispose();
    if (n.material) (Array.isArray(n.material) ? n.material : [n.material]).forEach(m => m.dispose());
  });
}
function remove(id) {
  const o = objects.get(id);
  if (!o) return;
  o.parent && o.parent.remove(o);
  dispose(o);
  objects.delete(id);
}
function put(id, grp, obj) {
  remove(id);
  obj.name = id;
  objects.set(id, obj);
  group(grp).add(obj);
  boundsDirty = true;
}
let dotTexture = null;
function dot() {
  if (dotTexture) return dotTexture;
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d'); g.beginPath(); g.arc(32, 32, 29, 0, Math.PI * 2); g.fillStyle = '#fff'; g.fill();
  dotTexture = new THREE.CanvasTexture(c);
  return dotTexture;
}

// ── objects ───────────────────────────────────────────────────────────
function mesh(a) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(f32(a.pos), 3));
  const idx = u32(a.idx);
  if (idx) geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.computeVertexNormals();
  const see = a.opacity < 1;
  const mat = new THREE.MeshStandardMaterial({
    color: a.color, roughness: a.roughness ?? 0.55, metalness: a.metalness ?? 0.08, flatShading: a.flat !== false,
    transparent: see, opacity: a.opacity, depthWrite: !see, side: THREE.DoubleSide,
    emissive: a.emissive || '#000000', emissiveIntensity: a.emissive ? 1 : 0,
    polygonOffset: !!a.edges, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  });
  const m = new THREE.Mesh(geo, mat);
  m.castShadow = a.shadow !== false && !see;
  m.receiveShadow = !see;
  if (see) m.renderOrder = 1;
  if (a.edges) {
    const e = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 28),
      new THREE.LineBasicMaterial({ color: a.edgeColor || '#000000', transparent: true, opacity: a.edgeOpacity ?? 0.28 }));
    e.raycast = () => {};
    m.add(e);
  }
  put(a.id, a.group, m);
}

function lineMaterial(a) {
  return new LineMaterial({
    color: a.colors ? 0xffffff : a.color, linewidth: a.width || 1.5, vertexColors: !!a.colors,
    transparent: (a.opacity ?? 1) < 1, opacity: a.opacity ?? 1, worldUnits: false, depthWrite: (a.opacity ?? 1) >= 1,
  });
}

function lines(a) {
  const pos = f32(a.pos);
  const strip = a.mode !== 'segments';
  const geo = strip ? new LineGeometry() : new LineSegmentsGeometry();
  if (pos.length >= 6) geo.setPositions(pos); else geo.setPositions(new Float32Array(6));
  if (a.colors) geo.setColors(f32(a.colors));
  const obj = strip ? new Line2(geo, lineMaterial(a)) : new LineSegments2(geo, lineMaterial(a));
  obj.userData = { full: pos, strip, a };
  if (pos.length < 6) obj.visible = false;
  if ((a.opacity ?? 1) < 1) obj.renderOrder = 2;
  put(a.id, a.group, obj);
}

// Draw only the first n points (strip) or n segments, plus a moving head point joined to the last one.
function progress(a) {
  const o = objects.get(a.id);
  if (!o) return;
  const { full, strip } = o.userData;
  const per = strip ? 3 : 6;
  const total = strip ? full.length / 3 : full.length / 6;
  const n = Math.max(0, Math.min(a.n, total));
  const count = strip ? Math.max(0, n - 1) : n;
  o.geometry.instanceCount = count;
  o.visible = count > 0 || !!a.head;
  let h = o.userData.head;
  if (a.head && full.length >= 3) {
    const last = n === 0 ? full.subarray(0, 3) : strip ? full.subarray((n - 1) * 3, n * 3) : full.subarray(n * 6 - 3, n * 6);
    if (!h) {
      const ga = new LineSegmentsGeometry();
      ga.setPositions(new Float32Array(6));
      h = new LineSegments2(ga, lineMaterial({ ...o.userData.a, colors: null }));
      o.userData.head = h;
      o.add(h);
    }
    h.geometry.setPositions(new Float32Array([last[0], last[1], last[2], a.head[0], a.head[1], a.head[2]]));
    h.visible = true;
  } else if (h) h.visible = false;
  void per;
}

function points(a) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(f32(a.pos), 3));
  const cols = f32(a.colors);
  if (cols) geo.setAttribute('color', new THREE.BufferAttribute(cols, 4));
  const mat = new THREE.PointsMaterial({
    size: a.size || 3, sizeAttenuation: false, map: dot(), alphaTest: 0.4, transparent: true,
    vertexColors: !!cols, color: cols ? 0xffffff : (a.color || '#ffffff'), opacity: a.opacity ?? 1,
  });
  put(a.id, a.group, new THREE.Points(geo, mat));
}

function setColor(a) {
  const o = objects.get(a.id);
  if (!o || !o.material) return;
  const m = o.material;
  if (a.color) m.color.set(a.color);
  if (a.opacity !== undefined) {
    m.opacity = a.opacity;
    m.transparent = a.opacity < 1;
    m.depthWrite = a.opacity >= 1;
    o.visible = a.opacity > 0.001;
    m.needsUpdate = true;
  }
}

// ── camera (navigation.js: Topolabs-style damped orbit + gizmo) ─────────
function sizeOf() { return [Math.max(1, stage.clientWidth), Math.max(1, stage.clientHeight)]; }
function updateBounds() {
  bounds.makeEmpty();
  content.traverseVisible(o => { if (o.isMesh || o.isLine2 || o.isLineSegments2 || o.isPoints) bounds.expandByObject(o); });
  boundsDirty = false;
  if (bounds.isEmpty()) { floor.visible = false; return; }
  const c = bounds.getCenter(new THREE.Vector3()), s = bounds.getSize(new THREE.Vector3());
  const ext = Math.max(s.x, s.y, s.z, 1) * 1.2;
  floor.visible = true;
  floor.position.set(c.x, c.y, bounds.min.z - 0.05);
  floor.scale.set(ext * 4, ext * 4, 1);
  sun.target.position.copy(c);
  sun.position.copy(c).add(new THREE.Vector3(-0.55, -0.75, 1.5).normalize().multiplyScalar(ext * 2.2));
  const sc = sun.shadow.camera;
  sc.left = -ext; sc.right = ext; sc.top = ext; sc.bottom = -ext; sc.near = ext * 0.05; sc.far = ext * 5;
  sc.updateProjectionMatrix();
  sun.shadow.needsUpdate = true;
  persp.near = Math.max(ext / 400, 0.05); persp.far = ext * 60; persp.updateProjectionMatrix();
  ortho.near = -ext * 30; ortho.far = ext * 30; ortho.updateProjectionMatrix();
}
const nav = createNavigation({
  renderer, stage, persp, ortho, fov: FOV,
  getBounds: () => { if (boundsDirty) updateBounds(); return bounds; },
  gizmo: document.getElementById('gizmo'),
  buttons: { ortho: document.getElementById('cam-ortho'), reset: document.getElementById('cam-reset') },
  feedback: document.getElementById('feedback'),
});

// ── loop ──────────────────────────────────────────────────────────────
function resize() {
  const [w, h] = sizeOf();
  renderer.setSize(w, h);
  nav.resize();
  needs = true;
}
new ResizeObserver(resize).observe(stage);
resize();
let prev = performance.now();
renderer.setAnimationLoop(() => {
  const now = performance.now(), dt = Math.min((now - prev) / 1000, 0.05);
  prev = now;
  if (boundsDirty) { updateBounds(); needs = true; }
  if (nav.update(dt)) needs = true;
  if (!needs) return;
  needs = false;
  renderer.render(scene, nav.camera);
  nav.drawGizmo();
});
// ── command dispatch ─────────────────────────────────────────────────
function applyTheme(t) {
  nav.setTheme(t);
  const r = document.documentElement.style;
  for (const k of ['bg', 'bg2', 'text', 'muted', 'surface', 'border', 'accent']) if (t[k]) r.setProperty('--' + k, t[k]);
  floor.material.opacity = t.dark ? 0.42 : 0.2;
  hemi.groundColor.set(t.dark ? 0x5b6b7d : 0x9aa8b8);
}
const OPS = {
  theme: applyTheme,
  mesh, lines, points, progress,
  remove: a => { remove(a.id); boundsDirty = true; },
  clear: a => {
    for (const [id, o] of [...objects]) {
      if (a.group === undefined || o.parent === groups.get(a.group)) remove(id);
    }
    boundsDirty = true;
  },
  offset: a => { group(a.group).position.set(...a.xyz); },
  color: setColor,
  visible: a => { const o = objects.get(a.id); if (o) o.visible = a.on; boundsDirty = true; },
  camera: a => nav.lookFrom(a.center, a.distance, a.elevation, a.azimuth, a.animate ? FEEL.framingSeconds : 0),
  fit: a => {
    const s = a.animate === false ? 0 : FEEL.framingSeconds;
    if (a.elevation !== undefined) nav.fitFrom(a.elevation, a.azimuth, s); else nav.fit(undefined, undefined, s);
  },
};
window.S = {
  run(cmds) {
    for (const [op, a] of cmds) {
      try { OPS[op](a || {}); } catch (e) { console.error('scene op', op, e); }
    }
    needs = true;
    return true;
  },
  snapshot() {
    nav.update(0);
    renderer.render(scene, nav.camera);
    const src = renderer.domElement, out = document.createElement('canvas');
    out.width = src.width; out.height = src.height;
    const g = out.getContext('2d');
    const css = getComputedStyle(document.documentElement);
    g.fillStyle = css.getPropertyValue('--bg') || '#000'; g.fillRect(0, 0, out.width, out.height);
    g.drawImage(src, 0, 0);
    return out.toDataURL('image/png');
  },
  debug() {
    if (boundsDirty) updateBounds();
    return JSON.stringify({ size: sizeOf(), ...nav.debug(),
      bmin: bounds.min.toArray(), bmax: bounds.max.toArray() });
  },
  info() {
    const gl = renderer.getContext(), ext = gl.getExtension('WEBGL_debug_renderer_info');
    return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
  },
};
document.title = 'ready';
