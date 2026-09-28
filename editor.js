/* Topology editor for the STP visualizer.
 *
 * Canvas interactions build a topology (switches with priority + position,
 * links with cost);「生成动画」POSTs it to serve.py /generate and boots the
 * player below. window.EDITOR exposes the state and actions so the page is
 * testable end-to-end without real mouse events.
 */
(function () {
  'use strict';

  const W = 960, H = 640, NODE_R = 26;
  const $ = id => document.getElementById(id);
  const canvas = $('ed-stage');
  const ctx = canvas.getContext('2d');
  (function setup() {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.aspectRatio = W + ' / ' + H;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  })();

  const ED = {
    switches: [],   // {id, priority, x, y}  x/y in canvas px
    links: [],      // {a, b, cost}
    tool: 'select',
    linkFrom: null,
    selected: null, // {type:'switch', id} | {type:'link', index}
    drag: null,
    mouse: { x: 0, y: 0 },
  };

  function nextId() {
    let n = 1;
    const used = new Set(ED.switches.map(s => s.id));
    while (used.has('S' + n)) n++;
    return 'S' + n;
  }

  function macFor(num) {
    return '00:00:00:00:' +
      String(Math.floor(num / 256)).padStart(2, '0') + ':' +
      String(num % 256).padStart(2, '0');
  }

  function setStatus(text, cls) {
    const el = $('ed-status');
    el.textContent = text || '';
    el.className = cls || '';
  }

  // ---------- model actions (also the E2E test API) ----------
  const API = {
    state: ED,
    addSwitch(x, y, priority) {
      const sw = { id: nextId(), priority: priority || 32768, x, y };
      ED.switches.push(sw);
      redraw(); return sw.id;
    },
    addLink(a, b, cost) {
      if (a === b) throw new Error('不能连接到自身');
      const dup = ED.links.some(l =>
        (l.a === a && l.b === b) || (l.a === b && l.b === a));
      if (dup) throw new Error('两台交换机之间已有链路');
      ED.links.push({ a, b, cost: cost || 4 });
      redraw();
    },
    setPriority(id, priority) {
      const sw = ED.switches.find(s => s.id === id);
      if (sw) { sw.priority = Math.max(0, Math.round(priority)); redraw(); }
    },
    setCost(index, cost) {
      if (ED.links[index]) {
        ED.links[index].cost = Math.max(1, Math.round(cost)); redraw();
      }
    },
    removeSwitch(id) {
      ED.switches = ED.switches.filter(s => s.id !== id);
      ED.links = ED.links.filter(l => l.a !== id && l.b !== id);
      if (ED.selected && ED.selected.id === id) ED.selected = null;
      redraw();
    },
    removeLink(index) {
      ED.links.splice(index, 1);
      if (ED.selected && ED.selected.index === index) ED.selected = null;
      redraw();
    },
    loadSample() {
      ED.switches = [
        { id: 'S1', priority: 32768, x: W / 2, y: 90 },
        { id: 'S2', priority: 32768, x: W / 2 - 210, y: H - 110 },
        { id: 'S3', priority: 8192, x: W / 2 + 210, y: H - 110 },
      ];
      ED.links = [
        { a: 'S1', b: 'S2', cost: 4 },
        { a: 'S1', b: 'S3', cost: 4 },
        { a: 'S2', b: 'S3', cost: 4 },
      ];
      ED.selected = null;
      redraw();
    },
    clear() {
      ED.switches = []; ED.links = []; ED.selected = null; redraw();
    },
    payload() {
      return {
        topology: {
          switches: ED.switches.map(s => ({
            id: s.id, priority: s.priority, mac: macFor(+s.id.slice(1) || 1),
            x: +(s.x / W).toFixed(4), y: +(s.y / H).toFixed(4),
          })),
          links: ED.links.map(l => ({ a: l.a, b: l.b, cost: l.cost })),
        },
        protocol: $('ed-protocol').value,
        seed: parseInt($('ed-seed').value || '42', 10),
      };
    },
    validate() {
      if (ED.switches.length < 2) return '至少需要 2 台交换机';
      const ids = new Set(ED.switches.map(s => s.id));
      if (ED.links.length < ED.switches.length - 1) return '链路太少，无法连通';
      // connectivity (flood fill)
      const adj = {};
      ED.switches.forEach(s => { adj[s.id] = []; });
      ED.links.forEach(l => { adj[l.a].push(l.b); adj[l.b].push(l.a); });
      const seen = new Set([ED.switches[0].id]);
      const queue = [ED.switches[0].id];
      while (queue.length) {
        const u = queue.shift();
        for (const v of adj[u]) if (!seen.has(v)) { seen.add(v); queue.push(v); }
      }
      if (seen.size !== ids.size) return '拓扑不连通';
      return null;
    },
    async generate() {
      const problem = API.validate();
      if (problem) { setStatus('✕ ' + problem, 'error'); throw new Error(problem); }
      setStatus('生成中…');
      try {
        const res = await fetch('/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(API.payload()),
        });
        const data = await res.json();
        if (!res.ok) {
          setStatus('✕ ' + (data.error || res.status), 'error');
          throw new Error(data.error || 'generate failed');
        }
        window.bootPlayer(data);
        setStatus(`✓ ${data.steps ? data.steps.length : data.instances.length} 个视图就绪，下方播放`, 'ok');
        document.querySelector('header.player').scrollIntoView({ behavior: 'smooth' });
        return data;
      } catch (err) {
        if (!$('ed-status').className) setStatus('✕ 无法连接服务：' + err, 'error');
        throw err;
      }
    },
  };
  window.EDITOR = API;

  // ---------- rendering ----------
  function switchAt(x, y) {
    for (let i = ED.switches.length - 1; i >= 0; i--) {
      const s = ED.switches[i];
      if (Math.hypot(s.x - x, s.y - y) <= NODE_R + 4) return s;
    }
    return null;
  }
  function linkAt(x, y) {
    for (let i = 0; i < ED.links.length; i++) {
      const l = ED.links[i];
      const a = ED.switches.find(s => s.id === l.a);
      const b = ED.switches.find(s => s.id === l.b);
      const dx = b.x - a.x, dy = b.y - a.y;
      const t = Math.max(0, Math.min(1,
        ((x - a.x) * dx + (y - a.y) * dy) / (dx * dx + dy * dy)));
      if (Math.hypot(a.x + t * dx - x, a.y + t * dy - y) < 9) return i;
    }
    return -1;
  }

  function redraw() {
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#162032';
    for (let gx = 0; gx <= W; gx += 40) {
      for (let gy = 0; gy <= H; gy += 40) ctx.fillRect(gx, gy, 1, 1);
    }
    ED.links.forEach((l, i) => {
      const a = ED.switches.find(s => s.id === l.a);
      const b = ED.switches.find(s => s.id === l.b);
      if (!a || !b) return;
      const sel = ED.selected && ED.selected.type === 'link' &&
                  ED.selected.index === i;
      ctx.strokeStyle = sel ? '#facc15' : '#64748b';
      ctx.lineWidth = sel ? 4 : 2;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      ctx.fillStyle = '#94a3b8'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText('成本 ' + l.cost, (a.x + b.x) / 2, (a.y + b.y) / 2 - 6);
    });
    if (ED.tool === 'link' && ED.linkFrom) {
      const a = ED.switches.find(s => s.id === ED.linkFrom);
      if (a) {
        ctx.strokeStyle = '#22c55e'; ctx.lineWidth = 2; ctx.setLineDash([6, 6]);
        ctx.beginPath(); ctx.moveTo(a.x, a.y);
        ctx.lineTo(ED.mouse.x, ED.mouse.y); ctx.stroke();
        ctx.setLineDash([]);
      }
    }
    ED.switches.forEach(s => {
      const sel = ED.selected && ED.selected.type === 'switch' &&
                  ED.selected.id === s.id;
      ctx.beginPath(); ctx.arc(s.x, s.y, NODE_R, 0, 2 * Math.PI);
      ctx.fillStyle = sel ? '#f59e0b' : '#3b82f6'; ctx.fill();
      if (ED.linkFrom === s.id) {
        ctx.lineWidth = 4; ctx.strokeStyle = '#22c55e'; ctx.stroke();
      }
      ctx.fillStyle = '#fff'; ctx.font = 'bold 14px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(s.id, s.x, s.y + 5);
      ctx.fillStyle = '#94a3b8'; ctx.font = '11px sans-serif';
      ctx.fillText(String(s.priority), s.x, s.y + NODE_R + 16);
    });
    renderProps();
  }

  function renderProps() {
    const box = $('ed-props');
    if (!ED.selected) {
      box.innerHTML = '点击画布中的交换机或链路。';
      return;
    }
    if (ED.selected.type === 'switch') {
      const s = ED.switches.find(x => x.id === ED.selected.id);
      if (!s) { ED.selected = null; return; }
      box.innerHTML =
        `<div>交换机 <b>${s.id}</b></div>` +
        `<div style="color:#94a3b8;font-size:12px">MAC ${macFor(+s.id.slice(1) || 1)}</div>` +
        `<div style="margin-top:8px">优先级</div>` +
        `<input type="number" id="ed-prop-priority" value="${s.priority}" step="4096">` +
        `<button class="danger" id="ed-prop-delete">删除此交换机</button>`;
      $('ed-prop-priority').oninput = e =>
        API.setPriority(s.id, parseInt(e.target.value || '0', 10));
      $('ed-prop-delete').onclick = () => API.removeSwitch(s.id);
    } else {
      const i = ED.selected.index;
      const l = ED.links[i];
      if (!l) { ED.selected = null; return; }
      box.innerHTML =
        `<div>链路 <b>${l.a} – ${l.b}</b></div>` +
        `<div style="margin-top:8px">成本</div>` +
        `<input type="number" id="ed-prop-cost" value="${l.cost}" min="1">` +
        `<button class="danger" id="ed-prop-delete">删除此链路</button>`;
      $('ed-prop-cost').oninput = e =>
        API.setCost(i, parseInt(e.target.value || '1', 10));
      $('ed-prop-delete').onclick = () => API.removeLink(i);
    }
  }

  // ---------- interactions ----------
  function canvasPoint(ev) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (ev.clientX - rect.left) * W / rect.width,
      y: (ev.clientY - rect.top) * H / rect.height,
    };
  }

  canvas.addEventListener('mousedown', ev => {
    const p = canvasPoint(ev);
    ED.mouse = p;
    const sw = switchAt(p.x, p.y);
    if (ED.tool === 'add') {
      if (!sw) API.addSwitch(p.x, p.y);
      return;
    }
    if (ED.tool === 'link') {
      if (!sw) return;
      if (!ED.linkFrom) { ED.linkFrom = sw.id; }
      else if (ED.linkFrom === sw.id) { ED.linkFrom = null; }
      else {
        try { API.addLink(ED.linkFrom, sw.id); ED.linkFrom = null; setStatus(''); }
        catch (err) { setStatus('✕ ' + err.message, 'error'); }
      }
      redraw();
      return;
    }
    if (ED.tool === 'delete') {
      if (sw) API.removeSwitch(sw.id);
      else { const i = linkAt(p.x, p.y); if (i >= 0) API.removeLink(i); }
      return;
    }
    // select tool
    if (sw) {
      ED.selected = { type: 'switch', id: sw.id };
      ED.drag = { id: sw.id, dx: sw.x - p.x, dy: sw.y - p.y };
    } else {
      const i = linkAt(p.x, p.y);
      ED.selected = i >= 0 ? { type: 'link', index: i } : null;
    }
    redraw();
  });
  canvas.addEventListener('mousemove', ev => {
    const p = canvasPoint(ev);
    ED.mouse = p;
    if (ED.drag) {
      const s = ED.switches.find(x => x.id === ED.drag.id);
      if (s) {
        s.x = Math.max(NODE_R + 4, Math.min(W - NODE_R - 4, p.x + ED.drag.dx));
        s.y = Math.max(NODE_R + 4, Math.min(H - NODE_R - 4, p.y + ED.drag.dy));
        redraw();
      }
    } else if (ED.tool === 'link' && ED.linkFrom) {
      redraw();
    }
  });
  window.addEventListener('mouseup', () => { ED.drag = null; });

  // toolbar
  const tools = ['select', 'add', 'link', 'delete'];
  tools.forEach(t => {
    $('ed-tool-' + t).onclick = () => {
      ED.tool = t; ED.linkFrom = null;
      tools.forEach(x =>
        $('ed-tool-' + x).classList.toggle('active', x === t));
      redraw();
    };
  });
  $('ed-sample').onclick = () => { API.loadSample(); setStatus(''); };
  $('ed-clear').onclick = () => { API.clear(); setStatus(''); };
  $('ed-io').onclick = () => {
    const box = $('ed-io-box');
    box.hidden = !box.hidden;
    if (!box.hidden) $('ed-io-text').value = JSON.stringify(API.payload().topology, null, 1);
  };
  $('ed-io-apply').onclick = () => {
    try {
      const topo = JSON.parse($('ed-io-text').value);
      ED.switches = topo.switches.map(s => ({
        id: s.id, priority: s.priority || 32768,
        x: s.x * W, y: s.y * H,
      }));
      ED.links = topo.links.map(l =>
        ({ a: l.a, b: l.b, cost: l.cost || 4 }));
      ED.selected = null;
      redraw();
      setStatus('✓ 已应用 JSON', 'ok');
    } catch (err) {
      setStatus('✕ JSON 解析失败：' + err.message, 'error');
    }
  };
  $('ed-generate').onclick = () => API.generate().catch(() => {});

  API.loadSample();
})();
