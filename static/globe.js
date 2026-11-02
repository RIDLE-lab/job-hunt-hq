/* Home: the Radar | Map switch, and the map itself – a dotted globe that turns to the country you live in and zooms
   in, with your best matches at the places they're based and the radar still sweeping over them. */
(() => {
  const fig = document.querySelector('.radar');
  const pane = fig && fig.querySelector('.globe-scope');
  if (!pane) return;
  const buttons = [...fig.querySelectorAll('.scope-switch button')];
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const G = JSON.parse(pane.dataset.globe || '{}');
  const canvas = pane.querySelector('canvas');
  const ctx = canvas.getContext('2d');
  const blips = [...pane.querySelectorAll('.blip')];
  const pin = pane.querySelector('.home-pin');
  const D = Math.PI / 180;
  const target = { lat: G.lat, lon: G.lon, k: 0.85 / Math.sin(G.reach / 6371) };
  let view = { lat: 18, lon: G.lon + 110, k: 1 };
  let world = null, detail = null, size = 0, loaded = false, started = false;

  function show(which, remember) {
    buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.view === which)));
    fig.querySelectorAll('[data-view-pane]').forEach((p) => { p.hidden = p.dataset.viewPane !== which; });
    fig.querySelectorAll('[data-view-note]').forEach((p) => { p.hidden = p.dataset.viewNote !== which; });
    fig.classList.toggle('on-map', which === 'map');
    if (remember) try { localStorage.setItem('jhq-home-view', which); } catch (e) { /* private window */ }
    if (which === 'map') start();
  }
  buttons.forEach((b) => b.addEventListener('click', () => show(b.dataset.view, true)));

  function start() {
    fit();
    if (started) return;
    started = true;
    Promise.all([fetch(pane.dataset.world).then((r) => r.json()), fetch(pane.dataset.detail).then((r) => r.json())])
      .then(([w, d]) => { world = w; detail = d; loaded = true; still ? land() : fly(); })
      .catch(() => { loaded = true; land(); });
  }

  function land() { view = { ...target }; draw(); pane.classList.add('arrived'); }

  function fit() {
    const w = pane.clientWidth;
    if (!w || w === size) return;
    size = w;
    const r = devicePixelRatio || 1;
    canvas.width = canvas.height = Math.round(w * r);
    ctx.setTransform(r, 0, 0, r, 0, 0);
    draw();
  }
  new ResizeObserver(fit).observe(pane);

  /* orthographic projection: where a place sits on screen, and whether it's on the side facing us */
  function project(lat, lon) {
    const S = size * 0.48, R = S * view.k, p = lat * D, l = (lon - view.lon) * D, p0 = view.lat * D;
    const cp = Math.cos(p);
    const x = R * cp * Math.sin(l);
    const y = R * (Math.cos(p0) * Math.sin(p) - Math.sin(p0) * cp * Math.cos(l));
    const z = Math.sin(p0) * Math.sin(p) + Math.cos(p0) * cp * Math.cos(l);
    return [size / 2 + x, size / 2 - y, z, Math.hypot(x, y) <= S];
  }

  function draw() {
    if (!size || !loaded) return;
    const c = size / 2, S = size * 0.48;
    ctx.clearRect(0, 0, size, size);
    ctx.save();
    ctx.beginPath(); ctx.arc(c, c, S, 0, 7); ctx.clip();
    const edge = S * view.k;                                   /* the globe's own outline, until we're zoomed past it */
    if (edge < S * 1.02) { ctx.beginPath(); ctx.arc(c, c, edge, 0, 7); ctx.fillStyle = 'rgba(59,227,204,.05)'; ctx.fill(); }
    const mix = Math.max(0, Math.min(1, (view.k - 1.4) / Math.max(0.3, target.k - 1.4)));
    const dot = Math.max(1, Math.min(1.7, size / 260));
    if (world && mix < 1) {
      for (let i = 0; i < world.length; i += 2) {
        const [x, y, z, inside] = project(world[i], world[i + 1]);
        if (z <= 0 || !inside) continue;
        ctx.fillStyle = `rgba(255,255,255,${((0.12 + z * 0.4) * (1 - mix)).toFixed(3)})`;
        ctx.fillRect(x - dot / 2, y - dot / 2, dot, dot);
      }
    }
    if (detail && mix > 0) {
      for (let i = 0; i < detail.length; i += 3) {
        const [x, y, z, inside] = project(detail[i], detail[i + 1]);
        if (z <= 0 || !inside) continue;
        ctx.fillStyle = detail[i + 2] ? `rgba(59,227,204,${(0.75 * mix).toFixed(3)})` : `rgba(255,255,255,${(0.2 * mix).toFixed(3)})`;
        ctx.beginPath(); ctx.arc(x, y, dot * 0.95, 0, 7); ctx.fill();
      }
    }
    ctx.restore();
    if (pin && G.home) place(pin, project(G.home[0], G.home[1]), -1);
    /* jobs in the same town would sit on top of each other: fan them out round it, best match in the middle */
    const groups = [];
    blips.forEach((b, i) => {
      const at = project(+b.dataset.lat, +b.dataset.lon);
      const g = groups.find((q) => Math.hypot(q.x - at[0], q.y - at[1]) < 10);
      if (!g) { groups.push({ x: at[0], y: at[1], n: 1 }); place(b, at, i); return; }
      const n = g.n++, ring = n <= 6 ? 1 : n <= 18 ? 2 : 3, slots = ring * 6, a = (n * 360 / slots + ring * 20) * D;
      place(b, [g.x + Math.cos(a) * ring * 11, g.y + Math.sin(a) * ring * 11, at[2], at[3]], i);
    });
  }

  function place(el, [x, y, z, inside], i) {
    const seen = z > 0 && inside;
    el.style.visibility = seen ? '' : 'hidden';
    if (!seen) return;
    el.style.left = (x / size * 100) + '%';
    el.style.top = (y / size * 100) + '%';
    if (i < 0) return;
    const compass = (Math.atan2(x - size / 2, size / 2 - y) / D + 360) % 360;   /* clockwise from the top, like the sweep */
    const fit = Math.max(0, Math.min(1, ((+el.dataset.score || 0) - 40) / 55));
    el.style.setProperty('--sync', (compass / 360 * 6 - 6).toFixed(2) + 's');
    el.style.setProperty('--ring', (1.8 + fit * 1.6).toFixed(2));
    el.style.setProperty('--glow', (0.15 + fit * 0.5).toFixed(2));
  }

  /* one orchestrated moment: the globe turns to your country, then zooms in on it */
  function fly() {
    const from = { ...view }, t0 = performance.now(), turn = 1500, zoom = 1300;
    const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
    (function step(now) {
      const a = Math.min(1, (now - t0) / turn), b = Math.max(0, Math.min(1, (now - t0 - turn * 0.6) / zoom));
      view.lat = from.lat + (target.lat - from.lat) * ease(a);
      view.lon = from.lon + (target.lon - from.lon) * ease(a);
      view.k = Math.exp(Math.log(from.k) + (Math.log(target.k) - Math.log(from.k)) * ease(b));
      draw();
      if (b > 0.75) pane.classList.add('arrived');
      if (b < 1) requestAnimationFrame(step);
    })(t0);
  }

  /* drag to look around; it springs back to your country when you let go */
  let drag = null;
  pane.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.blip') || !loaded) return;
    drag = { x: e.clientX, y: e.clientY, lat: view.lat, lon: view.lon };
    pane.setPointerCapture(e.pointerId);
  });
  pane.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const per = 1 / (size * 0.48 * view.k) / D;
    view.lon = drag.lon - (e.clientX - drag.x) * per;
    view.lat = Math.max(-80, Math.min(80, drag.lat + (e.clientY - drag.y) * per));
    draw();
  });
  const release = () => {
    if (!drag) return;
    drag = null;
    if (still) { view = { ...target }; draw(); return; }
    const from = { ...view }, t0 = performance.now();
    (function back(now) {
      const t = Math.min(1, (now - t0) / 600), e = 1 - Math.pow(1 - t, 3);
      view.lat = from.lat + (target.lat - from.lat) * e;
      view.lon = from.lon + (target.lon - from.lon) * e;
      draw();
      if (t < 1 && !drag) requestAnimationFrame(back);
    })(t0);
  };
  pane.addEventListener('pointerup', release);
  pane.addEventListener('pointercancel', release);

  let saved = 'radar';
  try { saved = localStorage.getItem('jhq-home-view') || 'radar'; } catch (e) { /* private window */ }
  if (saved === 'map') show('map', false);
})();
