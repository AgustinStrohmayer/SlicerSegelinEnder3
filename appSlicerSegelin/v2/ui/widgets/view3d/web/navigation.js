// Camera navigation + orientation gizmo, ported from the Topolabs Aero studio viewer
// (frontend/src/lib/studioNavigation.ts). Same model and the same feel numbers:
//  - the camera is an orbit (azimuth around world Z, elevation, distance, ortho zoom, centre), so
//    the horizon can never roll; elevation has no stop, past the zenith the view goes upside down;
//  - a gesture moves a *wanted* orbit at once and the camera chases it with exponential damping;
//  - view changes (gizmo axis, fit, reset) are fixed-length smoothstep flights;
//  - the gizmo is a sphere with the six axis handles: drag it to orbit, click a handle to look
//    along that axis (snaps when released within 7° of one).
import * as THREE from 'three';

export const FEEL = {
  azimuthSpeed: 0.18,        // full turns per viewport height, horizontal drag
  polarSpeed: 0.18,          // same, vertical drag
  truckSpeed: 0.55,          // pan, relative to 1:1 with the pointer
  rotateSpeedGizmo: 0.5,     // dragging the gizmo sphere
  dollyToCursor: true,       // wheel zooms towards the point under the pointer
  draggingSmoothTime: 0.15,  // lag while a button is held (s)
  smoothTime: 0.32,          // lag settling after release (s)
  settleEpsilon: 1e-4,
  settleMs: 140,
  zoomPerNotch: 0.045,       // log-zoom per wheel notch
  zoomPixelsPerNotch: 120,
  zoomMaxPixelsPerEvent: 180,
  touchRotateMultiplier: 1.55,
  touchPanMultiplier: 1.35,
  touchPinchPerPixel: 0.006,
  snapDegrees: 7,            // gizmo drag snaps to an axis within this angle
  orientSeconds: 0.34,       // flight to an axis view
  framingSeconds: 0.52,      // flight when fitting / resetting
  fitMargin: 1.12,
  gizmoHandleReach: 1.3 / 3.6, // handle distance from the gizmo centre, in gizmo widths
  gizmoHandleRadius: 0.16,     // hit radius, in gizmo widths
};

const TAU = Math.PI * 2;
const HALF_PI = Math.PI / 2;
const AXES = [
  { axis: 'x', sign: 1, label: 'X' }, { axis: 'y', sign: 1, label: 'Y' }, { axis: 'z', sign: 1, label: 'Z' },
  { axis: 'x', sign: -1, label: '−X' }, { axis: 'y', sign: -1, label: '−Y' }, { axis: 'z', sign: -1, label: '−Z' },
];
const AXIS_COLOR = {
  x: ['#ee7182', '#4c1320'], y: ['#a1cf75', '#284413'], z: ['#6caefa', '#133961'],
  nx: ['#f3bac3', '#4c1320'], ny: ['#cee4b5', '#284413'], nz: ['#b7d5fa', '#133961'],
};

/** Direction from the centre towards the camera. */
function orbitDir(az, el, out) {
  const c = Math.cos(el);
  return out.set(c * Math.cos(az), c * Math.sin(az), Math.sin(el));
}
/** Screen right: always horizontal and defined, even looking straight down. */
function orbitRight(az, out) { return out.set(-Math.sin(az), Math.cos(az), 0); }
/** The equivalent of `a` closest to `ref`, so turns always take the short way. */
function shortest(a, ref) { return a + TAU * Math.round((ref - a) / TAU); }
function cloneOrbit(o) { return { ...o, center: o.center.clone() }; }
function axisVec(axis, sign) { return new THREE.Vector3(axis === 'x' ? sign : 0, axis === 'y' ? sign : 0, axis === 'z' ? sign : 0); }

export function createNavigation({ renderer, stage, persp, ortho, fov, getBounds, gizmo, buttons, feedback }) {
  let camera = persp;
  const tanHalf = Math.tan(THREE.MathUtils.degToRad(fov / 2));
  let orthoHalf = 100;                       // ortho frustum half-height at zoom 1 (mm)
  let home = { az: THREE.MathUtils.degToRad(-58), el: THREE.MathUtils.degToRad(28) };
  const actual = { az: home.az, el: home.el, dist: 600, zoom: 1, center: new THREE.Vector3() };
  const wanted = cloneOrbit(actual);
  let flight = null;
  let changed = true;                        // camera or gizmo needs a redraw
  let theme = { dark: true };

  const vDir = new THREE.Vector3(), vRight = new THREE.Vector3(), vUp = new THREE.Vector3(), basis = new THREE.Matrix4();
  const canvas = renderer.domElement;
  const gctx = gizmo.getContext('2d');

  function size() { return [Math.max(1, stage.clientWidth), Math.max(1, stage.clientHeight)]; }

  // ── camera ──────────────────────────────────────────────────────────
  function frustum() {
    const [w, h] = size();
    persp.aspect = w / h; persp.updateProjectionMatrix();
    ortho.top = orthoHalf; ortho.bottom = -orthoHalf; ortho.left = -orthoHalf * w / h; ortho.right = orthoHalf * w / h;
    ortho.updateProjectionMatrix();
  }
  /** Rebuild the camera from the orbit. The only place the camera moves. */
  function writeCamera(o) {
    orbitDir(o.az, o.el, vDir);
    orbitRight(o.az, vRight);
    vUp.crossVectors(vDir, vRight);
    camera.position.copy(o.center).addScaledVector(vDir, o.dist);
    camera.up.set(0, 0, Math.cos(o.el) >= 0 ? 1 : -1);
    camera.quaternion.setFromRotationMatrix(basis.makeBasis(vRight, vUp, vDir));
    camera.zoom = camera === ortho ? o.zoom : 1;
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld();
  }
  function sync() { Object.assign(wanted, { az: actual.az, el: actual.el, dist: actual.dist, zoom: actual.zoom }); wanted.center.copy(actual.center); }
  function moving() {
    if (flight) return true;
    const e = FEEL.settleEpsilon;
    return Math.abs(wanted.az - actual.az) > e || Math.abs(wanted.el - actual.el) > e
      || Math.abs(wanted.dist - actual.dist) > e * Math.max(actual.dist, 1)
      || Math.abs(wanted.zoom - actual.zoom) > e * Math.max(actual.zoom, 1)
      || wanted.center.distanceToSquared(actual.center) > e * e;
  }
  function stopFlight() { flight = null; }
  function fly(to, seconds) {
    stopFlight();
    const az = shortest(to.az, actual.az), el = shortest(to.el, actual.el);
    Object.assign(wanted, { az, el, dist: to.dist, zoom: to.zoom });
    wanted.center.copy(to.center);
    if (seconds <= 0) { Object.assign(actual, { az, el, dist: to.dist, zoom: to.zoom }); actual.center.copy(to.center); changed = true; return; }
    flight = { from: cloneOrbit(actual), to: cloneOrbit(wanted), t: 0, T: seconds };
  }

  // ── feedback (cursor + status pill) ─────────────────────────────────
  let state = 'idle', settleTimer = 0;
  const LABEL = { rotate: 'Rotating', pan: 'Panning', 'zoom-in': 'Zooming in', 'zoom-out': 'Zooming out', zoom: 'Zoom' };
  function notify(s) {
    clearTimeout(settleTimer);
    if (s !== state) {
      state = s;
      feedback.textContent = LABEL[s] || '';
      feedback.classList.toggle('on', s !== 'idle');
      if (s !== 'idle') document.body.classList.add('used');
    }
    canvas.style.cursor = s === 'idle' ? 'grab' : s === 'pan' ? 'move' : s === 'zoom-in' ? 'zoom-in'
      : s === 'zoom-out' ? 'zoom-out' : s === 'zoom' ? 'ns-resize' : 'grabbing';
    gizmo.style.cursor = s === 'rotate' ? 'grabbing' : 'pointer';
  }
  function settle() {
    clearTimeout(settleTimer);
    settleTimer = setTimeout(() => {
      if (pointers.size) return;
      if (moving()) settle(); else notify('idle');
    }, FEEL.settleMs);
  }

  // ── gestures ────────────────────────────────────────────────────────
  function unitsPerPixel(o) {
    const h = size()[1];
    return camera === ortho ? 2 * orthoHalf / Math.max(o.zoom, 1e-6) / h : 2 * o.dist * tanHalf / h;
  }
  function pan(dx, dy, scale) {
    const u = unitsPerPixel(actual) * scale;
    orbitRight(actual.az, vRight);
    vUp.crossVectors(orbitDir(actual.az, actual.el, vDir), vRight);
    wanted.center.addScaledVector(vRight, -dx * u).addScaledVector(vUp, dy * u);
  }
  /** Log zoom; positive zooms out. With a client point, that point stays put under the pointer. */
  function dolly(step, clientX, clientY) {
    const s = Math.exp(step);
    let k;
    if (camera === ortho) {
      const z = Math.min(1000, Math.max(0.02, wanted.zoom / s));
      k = wanted.zoom / z; wanted.zoom = z;
    } else {
      const d = Math.min(persp.far * 0.4, Math.max(persp.near * 4, wanted.dist * s));
      k = d / wanted.dist; wanted.dist = d;
    }
    if (!FEEL.dollyToCursor || clientX === undefined) return;
    const r = canvas.getBoundingClientRect();
    const nx = ((clientX - r.left) / r.width) * 2 - 1, ny = 1 - ((clientY - r.top) / r.height) * 2;
    // Point under the pointer on the plane through the centre, facing the camera (before the zoom).
    const halfH = camera === ortho ? orthoHalf / (wanted.zoom * k) : (wanted.dist / k) * tanHalf;
    const halfW = halfH * r.width / r.height;
    orbitRight(wanted.az, vRight);
    vUp.crossVectors(orbitDir(wanted.az, wanted.el, vDir), vRight);
    const p = wanted.center.clone().addScaledVector(vRight, nx * halfW).addScaledVector(vUp, ny * halfH);
    wanted.center.sub(p).multiplyScalar(k).add(p);
  }

  /**
   * Look along an axis without rolling (Topolabs docs/gizmo-orientacion.md): carry the current
   * screen up/right along the shortest arc to the axis and pick the orbit that matches them best.
   */
  function view(axis, sign = 1) {
    const d0 = orbitDir(actual.az, actual.el, new THREE.Vector3());
    const right0 = orbitRight(actual.az, new THREE.Vector3());
    const up0 = new THREE.Vector3().crossVectors(d0, right0);
    const d1 = axisVec(axis, sign);
    const turn = d0.dot(d1) < -0.9999 ? new THREE.Quaternion().setFromAxisAngle(up0, Math.PI)
      : new THREE.Quaternion().setFromUnitVectors(d0, d1);
    const upT = up0.applyQuaternion(turn), rightT = right0.applyQuaternion(turn);
    const cands = [];
    if (axis === 'z') for (let k = 0; k < 4; k++) cands.push({ az: k * HALF_PI, el: sign > 0 ? HALF_PI : -HALF_PI });
    else {
      const a = axis === 'x' ? (sign > 0 ? 0 : Math.PI) : (sign > 0 ? HALF_PI : -HALF_PI);
      cands.push({ az: a, el: 0 }, { az: a + Math.PI, el: Math.PI });
    }
    const r = new THREE.Vector3(), u = new THREE.Vector3(), d = new THREE.Vector3();
    let best = null;
    for (const c of cands) {
      const az = shortest(c.az, actual.az), el = shortest(c.el, actual.el);
      orbitRight(az, r);
      u.crossVectors(orbitDir(az, el, d), r);
      const path = Math.abs(az - actual.az) + Math.abs(el - actual.el);
      const score = u.dot(upT) + r.dot(rightT) - path * 1e-3 + (Math.cos(el) > 0 ? 1e-4 : 0);
      if (!best || score > best.score) best = { az, el, score };
    }
    fly({ ...cloneOrbit(actual), az: best.az, el: best.el }, FEEL.orientSeconds);
    notify('rotate'); settle();
  }
  function snapToNearestAxis() {
    orbitDir(wanted.az, wanted.el, vDir);
    const lim = Math.cos(THREE.MathUtils.degToRad(FEEL.snapDegrees));
    let best = null;
    for (const a of AXES) {
      const dot = a.sign * vDir[a.axis];
      if (dot > lim && (!best || dot > best.dot)) best = { ...a, dot };
    }
    if (best) view(best.axis, best.sign);
    return !!best;
  }

  /** Frame the bounds' 8 corners tightly from (az, el) — the current view if omitted. */
  function fit(az, el, seconds = FEEL.framingSeconds) {
    const b = getBounds();
    if (!b || b.isEmpty()) return;
    if (az === undefined) { az = wanted.az; el = wanted.el; }
    const look = orbitDir(az, el, new THREE.Vector3());
    const right = orbitRight(az, new THREE.Vector3());
    const up = new THREE.Vector3().crossVectors(look, right);
    const c = b.getCenter(new THREE.Vector3());
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity, near = -Infinity;
    for (let i = 0; i < 8; i++) {
      const p = new THREE.Vector3(i & 1 ? b.max.x : b.min.x, i & 2 ? b.max.y : b.min.y, i & 4 ? b.max.z : b.min.z).sub(c);
      const px = p.dot(right), py = p.dot(up);
      x0 = Math.min(x0, px); x1 = Math.max(x1, px); y0 = Math.min(y0, py); y1 = Math.max(y1, py);
      near = Math.max(near, p.dot(look));
    }
    const center = c.addScaledVector(right, (x0 + x1) / 2).addScaledVector(up, (y0 + y1) / 2);
    const [w, h] = size();
    const span = Math.max((y1 - y0) * FEEL.fitMargin, (x1 - x0) * FEEL.fitMargin / (w / h), 1e-3);
    const dist = span / 2 / tanHalf + near * 0.5;
    const zoom = camera === ortho ? orthoHalf / (span / 2) : 1;
    fly({ az, el, dist, zoom, center }, seconds);
    if (seconds > 0) { notify('rotate'); settle(); }
  }
  function reset() { fit(home.az, home.el); }

  /** Switch projection keeping the centre and the apparent size, as a short dolly-zoom: the
   *  perspective camera narrows its field of view while backing off (or the reverse), so the
   *  view flattens smoothly into the orthographic one instead of jumping. */
  let morph = null;
  const MORPH_S = 0.45, TAN_FLAT = Math.tan(THREE.MathUtils.degToRad(0.6));
  function setProjection(toOrtho) {
    if (morph ? toOrtho === morph.toOrtho : toOrtho === (camera === ortho)) return;
    stopFlight();
    sync();
    let H;                                   // visible half-height at the centre (kept all along)
    if (morph) { H = morph.H; }
    else if (camera === ortho) { H = orthoHalf / Math.max(actual.zoom, 1e-6); camera = persp; actual.zoom = 1; frustum(); }
    else H = actual.dist * tanHalf;
    const from = morph ? morph.s : (toOrtho ? 0 : 1);
    morph = { toOrtho, H, s: from, from, t: 0, T: MORPH_S * Math.abs((toOrtho ? 1 : 0) - from), far: morph ? morph.far : persp.far,
      near: morph ? morph.near : persp.near };
    buttons.ortho.setAttribute('aria-pressed', String(toOrtho));
    buttons.ortho.title = toOrtho ? 'Switch to perspective (O)' : 'Switch to orthographic (O)';
    changed = true;
  }
  /** One morph frame: s = 0 is the normal perspective, s = 1 nearly flat (then the ortho camera). */
  function stepMorph(dt) {
    const m = morph;
    m.t += dt;
    const a = Math.min(m.t / Math.max(m.T, 1e-6), 1), e = a * a * (3 - 2 * a);
    m.s = m.from + ((m.toOrtho ? 1 : 0) - m.from) * e;
    const tanCur = Math.exp(Math.log(tanHalf) + (Math.log(TAN_FLAT) - Math.log(tanHalf)) * m.s);
    actual.dist = wanted.dist = m.H / tanCur;
    persp.fov = THREE.MathUtils.radToDeg(2 * Math.atan(tanCur));
    persp.far = Math.max(m.far, actual.dist * 4);
    // keep the depth range tight while backing off: nothing nearer than the normal camera position matters
    persp.near = m.near + Math.max(0, actual.dist - m.H / tanHalf);
    persp.updateProjectionMatrix();
    if (a < 1) return;
    persp.fov = fov; persp.far = m.far; persp.near = m.near;
    actual.dist = m.H / tanHalf;
    if (m.toOrtho) { orthoHalf = m.H; camera = ortho; }
    actual.zoom = 1;
    morph = null;
    sync();
    frustum();
  }

  // ── pointer input (canvas + gizmo) ──────────────────────────────────
  const pointers = new Map();
  let multi = false, pinchDist = 0;
  const pinchMid = { x: 0, y: 0 };
  let hover = null;   // gizmo handle under the pointer

  function start(ev) {
    const onGizmo = ev.target === gizmo, onCanvas = ev.target === canvas;
    if (!onGizmo && !onCanvas) return;
    if (ev.pointerType === 'mouse') { for (const [id, p] of pointers) if (p.type === 'mouse') pointers.delete(id); pinchDist = 0; }
    if (!pointers.size) { stopFlight(); sync(); multi = false; }
    pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY, el: onGizmo ? gizmo : canvas, button: ev.button,
      type: ev.pointerType, moved: false, pan: ev.shiftKey && ev.button === 0 });
    multi ||= pointers.size > 1;
    notify(pointers.size > 1 || ev.button === 1 ? 'zoom' : ev.button === 2 || (ev.shiftKey && ev.button === 0) ? 'pan' : 'rotate');
  }
  function move(ev) {
    const p = pointers.get(ev.pointerId);
    if (!p) {
      if (ev.target === gizmo) setHover(handleAt(ev.clientX, ev.clientY));
      return;
    }
    if (ev.pointerType === 'mouse' && ev.buttons === 0) { end(ev); return; }  // lost pointerup
    const dx = ev.clientX - p.x, dy = ev.clientY - p.y;
    if (!p.moved && Math.hypot(dx, dy) > 3) p.moved = true;
    if (!p.moved) return;
    if (pointers.size === 1) {
      if ((p.button === 0 || p.button === -1) && !p.pan) {
        const h = Math.max(p.el.clientHeight, 1), touch = p.type === 'touch' ? FEEL.touchRotateMultiplier : 1;
        const g = p.el === gizmo;
        wanted.az -= TAU * (g ? FEEL.rotateSpeedGizmo : FEEL.azimuthSpeed) * touch * dx / h;
        wanted.el += TAU * (g ? FEEL.rotateSpeedGizmo : FEEL.polarSpeed) * touch * dy / h;
      } else if (p.button === 2 || p.pan) pan(dx, dy, FEEL.truckSpeed);
      else if (p.button === 1) dolly(dy / FEEL.zoomPixelsPerNotch * FEEL.zoomPerNotch);
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y), mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      if (pinchDist > 0) {
        dolly(-(dist - pinchDist) * FEEL.touchPinchPerPixel);
        pan(mx - pinchMid.x, my - pinchMid.y, FEEL.touchPanMultiplier);
      }
      pinchDist = dist; pinchMid.x = mx; pinchMid.y = my;
    }
    p.x = ev.clientX; p.y = ev.clientY;
  }
  function end(ev) {
    const p = pointers.get(ev.pointerId);
    if (!p) return;
    pointers.delete(ev.pointerId);
    if (pointers.size < 2) pinchDist = 0;
    const up = ev.type === 'pointerup';
    const click = p.el === gizmo && !p.moved && !multi && up && ev.button === 0;
    const dragGizmo = p.el === gizmo && p.moved && !multi && up;
    queueMicrotask(() => {
      if (click) {
        const hit = handleAt(ev.clientX, ev.clientY);
        if (hit) { view(hit.axis, hit.sign); return; }
        settle();
      } else if (ev.type === 'pointercancel') { pointers.clear(); notify('idle'); }
      else if (!pointers.size) {
        if (dragGizmo && snapToNearestAxis()) return;
        notify('idle'); settle();
      }
    });
  }
  function wheel(ev) {
    if (ev.target !== canvas && ev.target !== gizmo) return;
    if (ev.deltaY === 0) return;
    ev.preventDefault();
    if (flight) { stopFlight(); sync(); }
    const unit = ev.deltaMode === 1 ? 16 : ev.deltaMode === 2 ? 100 : 1;
    const lim = FEEL.zoomMaxPixelsPerEvent;
    const px = Math.max(-lim, Math.min(lim, ev.deltaY * unit));
    dolly(px / FEEL.zoomPixelsPerNotch * FEEL.zoomPerNotch, ev.clientX, ev.clientY);
    notify(ev.deltaY < 0 ? 'zoom-in' : 'zoom-out');
    settle();
  }
  function setHover(h) {
    const k = h ? h.axis + h.sign : null;
    if (k !== (hover ? hover.axis + hover.sign : null)) { hover = h; changed = true; }
  }

  // ── gizmo ───────────────────────────────────────────────────────────
  let handles = [];
  function handleAt(clientX, clientY) {
    const r = gizmo.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const reach = r.width * FEEL.gizmoHandleReach, lim = r.width * FEEL.gizmoHandleRadius;
    const inv = camera.quaternion.clone().invert();
    let best = null;
    for (const a of AXES) {
      const v = axisVec(a.axis, a.sign).applyQuaternion(inv);
      const d = Math.hypot(clientX - (cx + v.x * reach), clientY - (cy - v.y * reach));
      if (d > lim) continue;
      if (!best || d < best.d - 2 || (Math.abs(d - best.d) <= 2 && v.z > best.z)) best = { ...a, d, z: v.z };
    }
    return best;
  }
  function drawGizmo() {
    const dpr = Math.min(devicePixelRatio || 1, 2), css = gizmo.clientWidth || 116;
    const W = Math.round(css * dpr);
    if (gizmo.width !== W) { gizmo.width = gizmo.height = W; }
    const c = W / 2, reach = W * FEEL.gizmoHandleReach;
    gctx.clearRect(0, 0, W, W);
    const over = gizmoOver || state === 'rotate' && [...pointers.values()].some(p => p.el === gizmo);
    gctx.beginPath(); gctx.arc(c, c, c - 1, 0, TAU);
    gctx.fillStyle = theme.dark ? (over ? 'rgba(255,255,255,0.16)' : 'rgba(255,255,255,0.08)')
      : (over ? 'rgba(220,236,245,0.9)' : 'rgba(234,242,247,0.65)');
    gctx.fill();
    const inv = camera.quaternion.clone().invert();
    handles = AXES.map(a => {
      const v = axisVec(a.axis, a.sign).applyQuaternion(inv);
      return { ...a, x: c + v.x * reach, y: c - v.y * reach, z: v.z };
    }).sort((p, q) => p.z - q.z);
    const font = `600 ${Math.round(W * 0.1)}px "Segoe UI", system-ui, sans-serif`;
    for (const hd of handles) {
      const [fill, ink] = AXIS_COLOR[(hd.sign < 0 ? 'n' : '') + hd.axis];
      const isHover = hover && hover.axis === hd.axis && hover.sign === hd.sign;
      gctx.globalAlpha = 0.55 + 0.45 * (hd.z + 1) / 2;
      if (hd.sign > 0) {
        gctx.strokeStyle = fill; gctx.lineWidth = Math.max(2, W * 0.018);
        gctx.beginPath(); gctx.moveTo(c, c); gctx.lineTo(hd.x, hd.y); gctx.stroke();
      }
      const rad = W * (hd.sign > 0 ? 0.105 : 0.09) * (isHover ? 1.14 : 1);
      gctx.beginPath(); gctx.arc(hd.x, hd.y, rad, 0, TAU);
      gctx.fillStyle = fill; gctx.fill();
      if (isHover) { gctx.lineWidth = Math.max(1.5, W * 0.014); gctx.strokeStyle = theme.dark ? '#ffffff' : '#101a29'; gctx.stroke(); }
      gctx.globalAlpha = 1;
      gctx.fillStyle = ink; gctx.font = font; gctx.textAlign = 'center'; gctx.textBaseline = 'middle';
      gctx.fillText(hd.label, hd.x, hd.y + W * 0.006);
    }
  }
  let gizmoOver = false;
  gizmo.addEventListener('pointerenter', () => { gizmoOver = true; changed = true; });
  gizmo.addEventListener('pointerleave', () => { gizmoOver = false; setHover(null); changed = true; });
  gizmo.addEventListener('dblclick', ev => ev.stopPropagation());

  stage.parentElement.addEventListener('pointerdown', start, true);
  stage.parentElement.addEventListener('wheel', wheel, { capture: true, passive: false });
  addEventListener('contextmenu', ev => ev.preventDefault());
  document.addEventListener('pointermove', move, true);
  document.addEventListener('pointerup', end, true);
  document.addEventListener('pointercancel', end, true);
  addEventListener('blur', () => { pointers.clear(); stopFlight(); sync(); notify('idle'); });
  canvas.addEventListener('dblclick', () => fit());
  buttons.ortho.addEventListener('click', () => setProjection(camera !== ortho));
  buttons.reset.addEventListener('click', reset);
  addEventListener('keydown', ev => {
    if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
    const k = ev.key.toLowerCase();
    if (k === 'f') fit();
    else if (k === 'h' || ev.key === 'Home') reset();
    else if (k === 'o') setProjection(camera !== ortho);
    else if (k === 'x' || k === 'y' || k === 'z') view(k, ev.shiftKey ? -1 : 1);
  });
  notify('idle');

  return {
    get camera() { return camera; },
    fit, reset, view, setProjection,
    setTheme(t) { theme = t; changed = true; },
    /** Python's `fit(elevation, azimuth)` also sets where the reset button goes. */
    fitFrom(elevDeg, azimDeg, seconds) {
      const az = THREE.MathUtils.degToRad(azimDeg), el = THREE.MathUtils.degToRad(elevDeg);
      home = { az, el };
      fit(az, el, seconds);
    },
    /** Python's `camera(center, distance, elevation, azimuth)`. */
    lookFrom(center, dist, elevDeg, azimDeg, seconds) {
      const zoom = camera === ortho ? orthoHalf / (dist * tanHalf) : 1;
      fly({ az: THREE.MathUtils.degToRad(azimDeg), el: THREE.MathUtils.degToRad(elevDeg), dist, zoom,
        center: new THREE.Vector3(...center) }, seconds);
    },
    resize() { frustum(); changed = true; },
    /** Advance damping / flights; true when something must be redrawn. */
    update(dt) {
      const was = changed || moving() || !!morph;
      if (morph) {
        stepMorph(dt);
      } else if (flight) {
        flight.t += dt;
        const a = Math.min(flight.t / Math.max(flight.T, 1e-6), 1), s = a * a * (3 - 2 * a);
        const f = flight.from, t = flight.to;
        actual.az = f.az + (t.az - f.az) * s; actual.el = f.el + (t.el - f.el) * s;
        actual.dist = f.dist + (t.dist - f.dist) * s; actual.zoom = f.zoom + (t.zoom - f.zoom) * s;
        actual.center.lerpVectors(f.center, t.center, s);
        if (a === 1) { flight = null; settle(); }
      } else {
        // Exponential chase: each frame covers the same fraction of what is left.
        const tau = pointers.size ? FEEL.draggingSmoothTime : FEEL.smoothTime;
        const k = tau <= 0 ? 1 : 1 - Math.exp(-Math.min(dt, 0.05) / tau);
        actual.az += (wanted.az - actual.az) * k; actual.el += (wanted.el - actual.el) * k;
        actual.dist += (wanted.dist - actual.dist) * k; actual.zoom += (wanted.zoom - actual.zoom) * k;
        actual.center.lerp(wanted.center, k);
        if (!pointers.size && !moving()) {  // unwind accumulated turns once at rest
          const n = Math.floor(actual.az / TAU); if (n) { actual.az -= n * TAU; wanted.az -= n * TAU; }
          const m = Math.floor(actual.el / TAU); if (m) { actual.el -= m * TAU; wanted.el -= m * TAU; }
        }
      }
      if (!was) return false;
      writeCamera(actual);
      changed = false;
      return true;
    },
    drawGizmo,
    debug() { return { az: actual.az, el: actual.el, dist: actual.dist, zoom: actual.zoom, ortho: camera === ortho, morph: !!morph,
      target: actual.center.toArray(), cam: camera.position.toArray() }; },
  };
}
