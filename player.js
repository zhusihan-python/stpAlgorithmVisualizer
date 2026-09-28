/* Step-animation player for the STP visualizer.
 *
 * Expects the host page to contain the shell markup (see template.html):
 * #title #subtitle #tabs #stage #btn-first/prev/play/next/last #speed
 * #btn-concept #counter #desc #events #concept-modal #concept-body.
 *
 * Boot with `bootPlayer(document)`; calling it again swaps the story
 * (the editor does this after each /generate call). Pages that embed a
 * finished document just set window.PLAYER_DATA before loading this file.
 */
(function () {
  'use strict';

  const W = 960, H = 640, R = Math.min(W, H) / 2 - 115;
  const CX = W / 2, CY = H / 2 + 6;
  const NODE_R = 26;
  const PACKET_MS = 1300, HOLD_MS = 900;
  const INST_COLORS = ['#22c55e', '#38bdf8', '#f472b6'];

  const $ = id => document.getElementById(id);

  // Mutable player state, rebuilt by bootPlayer().
  const S = { ready: false };
  let rafHandle = null;
  let keysBound = false;

  function packetInfo(e) {
    if (e.kind === 'proposal') return { color: '#fbbf24', ring: '#92400e', label: '提案' };
    if (e.kind === 'agreement') return { color: '#2dd4bf', ring: '#134e4a', label: '同意' };
    return { color: '#f59e0b', ring: '#78350f', label: e.root + '/' + e.cost };
  }

  function setStep(i, keepPlaying) {
    if (!S.ready) return;
    if (!keepPlaying) { S.playing = false; }
    S.cur = Math.max(0, Math.min(S.steps.length - 1, i));
    S.enterTime = performance.now();
    const st = S.steps[S.cur];
    if (st.kind === 'round' || st.kind === 'handshake' ||
        st.kind === 'switch-online') {
      S.packets = st.events.map(e => ({
        from: S.pos[e.from], to: S.pos[e.to],
        delay: e.delay || 0, ...packetInfo(e),
      }));
    } else {
      S.packets = [];
    }
    renderPanels();
    updateButtons();
  }

  function portLine(sid, st) {
    if (st.kind !== 'final') {
      const info = st.switches[sid];
      return '根:' + info.root + ' 成本:' + info.cost +
             (info.root_port ? ' →' + info.root_port : '');
    }
    const p = st.roles.ports[sid];
    const blockedTerm = S.DATA.protocol === 'rstp' ? '备用' : '阻塞';
    if (sid === st.roles.root) return '根桥 · 全端口指定';
    let line = '根端口→' + p.root_port;
    if (p.blocked.length) line += '；' + blockedTerm + '→' + p.blocked.join(',');
    return line;
  }

  function renderPanels() {
    const st = S.steps[S.cur];
    if (S.overlayMode) {
      $('counter').textContent = '叠加对比视图';
      const first = JSON.stringify(S.INSTANCES[0].link_roles);
      const sameTrees = S.INSTANCES.every(
        inst => JSON.stringify(inst.link_roles) === first);
      $('desc').textContent =
        '同一物理拓扑上所有实例收敛后的生成树叠加：每种颜色是一个实例的树；' +
        '并行双色线 = 多个实例都在该链路转发；红 ✕ = 对所有实例都是冗余链路。' +
        (sameTrees
          ? '本拓扑各实例的树相同，链路未被分担。'
          : '不同实例的树使用不同链路——冗余链路为部分实例转发，实现负载分担。');
      const list = $('events');
      list.innerHTML = '';
      S.INSTANCES.forEach(inst => {
        const li = document.createElement('li');
        li.textContent = inst.id +
          (inst.vlans.length > 1 ? '（VLAN ' + inst.vlans.join(',') + '）' : '') +
          ' 根桥：' + inst.root_id;
        list.appendChild(li);
      });
      S.topo.links.forEach(l => {
        const parts = S.INSTANCES.map(inst =>
          inst.link_roles[l.id] === 'tree' ? inst.id + ' 转发' : inst.id + ' 阻塞');
        const trees = S.INSTANCES.filter(
          inst => inst.link_roles[l.id] === 'tree').length;
        const li = document.createElement('li');
        li.textContent = l.id.replace('-', '–') + '：' + parts.join('；');
        if (trees === S.INSTANCES.length) li.style.color = '#86efac';
        if (trees === 0) li.style.color = '#fca5a5';
        list.appendChild(li);
      });
      return;
    }
    $('counter').textContent = '第 ' + (S.cur + 1) + ' / ' + S.steps.length + ' 步';
    $('desc').textContent = st.description +
      (S.cur === 0 && S.DATA.concept ? '（💡 可先点右上角「📖 原理」了解核心思路。）' : '');
    const list = $('events');
    list.innerHTML = '';
    if (st.kind === 'round' || st.kind === 'handshake') {
      st.events.forEach(e => {
        const li = document.createElement('li');
        if (e.kind === 'proposal') {
          li.textContent = e.from + ' → ' + e.to + '：提案 Proposal';
          li.style.color = '#fcd34d';
        } else if (e.kind === 'agreement') {
          li.textContent = e.from + ' → ' + e.to + '：同意 Agreement';
          li.style.color = '#5eead4';
        } else {
          li.textContent = e.from + ' → ' + e.to + '：根=' + e.root + '，成本=' + e.cost;
        }
        list.appendChild(li);
      });
    } else if (st.kind === 'final') {
      Object.entries(st.roles.blocked_ends).forEach(([linkId, blockedSw]) => {
        const li = document.createElement('li');
        li.textContent = linkId.replace('-', '–') + '：' + blockedSw + ' 侧端口阻塞（备用端口）';
        li.style.color = '#fca5a5';
        list.appendChild(li);
      });
      if (!Object.keys(st.roles.blocked_ends).length) {
        const li = document.createElement('li');
        li.textContent = '无冗余链路，没有端口被阻塞';
        list.appendChild(li);
      }
    } else {
      const li = document.createElement('li');
      li.textContent = '尚未开始 BPDU 交换';
      list.appendChild(li);
    }
  }

  function updateButtons() {
    const off = S.overlayMode;
    $('btn-first').disabled = $('btn-prev').disabled = off || S.cur === 0;
    $('btn-next').disabled = $('btn-last').disabled =
      off || S.cur === S.steps.length - 1;
    $('btn-play').disabled = off;
    $('btn-play').textContent = S.playing ? '⏸' : '▶';
  }

  function lerp(p1, p2, t) {
    return { x: p1.x + (p2.x - p1.x) * t, y: p1.y + (p2.y - p1.y) * t };
  }

  function drawArrow(ctx, at, toward, color) {
    const angle = Math.atan2(toward.y - at.y, toward.x - at.x);
    ctx.save();
    ctx.translate(at.x, at.y);
    ctx.rotate(angle);
    ctx.beginPath();
    ctx.moveTo(8, 0); ctx.lineTo(-6, 6); ctx.lineTo(-6, -6); ctx.closePath();
    ctx.fillStyle = color; ctx.fill();
    ctx.restore();
  }

  function drawX(ctx, at, color) {
    ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(at.x - 7, at.y - 7); ctx.lineTo(at.x + 7, at.y + 7);
    ctx.moveTo(at.x + 7, at.y - 7); ctx.lineTo(at.x - 7, at.y + 7);
    ctx.stroke();
  }

  function instColor(idx) {
    return INST_COLORS[idx % INST_COLORS.length];
  }

  function drawOverlay(ctx) {
    const st = S.steps[S.cur];
    for (const l of S.topo.links) {
      if (l.appear_at !== undefined && S.cur < l.appear_at) continue;
      const p1 = S.pos[l.a], p2 = S.pos[l.b];
      const fwdIdx = [];
      S.INSTANCES.forEach((inst, i) => {
        if (inst.link_roles[l.id] === 'tree') fwdIdx.push(i);
      });
      if (fwdIdx.length === 0) {
        ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 2.5; ctx.setLineDash([9, 7]);
        ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
        ctx.setLineDash([]);
        drawX(ctx, { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 }, '#ef4444');
      } else {
        const dx = p2.x - p1.x, dy = p2.y - p1.y;
        const len = Math.hypot(dx, dy);
        const nx = -dy / len, ny = dx / len;
        fwdIdx.slice(0, 2).forEach((idx, k) => {
          const off = fwdIdx.length === 1 ? 0 : (k === 0 ? 3.5 : -3.5);
          ctx.strokeStyle = instColor(idx);
          ctx.lineWidth = fwdIdx.length === 1 ? 4 : 3;
          ctx.beginPath();
          ctx.moveTo(p1.x + nx * off, p1.y + ny * off);
          ctx.lineTo(p2.x + nx * off, p2.y + ny * off);
          ctx.stroke();
        });
      }
      drawCostLabel(ctx, l, p1, p2, 'alternate-worst');
    }
    for (const s of S.topo.switches) {
      if (s.appear_at !== undefined && S.cur < s.appear_at) continue;
      const p = S.pos[s.id];
      ctx.beginPath(); ctx.arc(p.x, p.y, NODE_R, 0, 2 * Math.PI);
      ctx.fillStyle = '#3b82f6'; ctx.fill();
      ctx.fillStyle = '#fff'; ctx.font = 'bold 14px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(s.id, p.x, p.y + 5);
      ctx.fillStyle = '#94a3b8'; ctx.font = '11px sans-serif';
      ctx.fillText(s.bridge_id, p.x, p.y + NODE_R + 16);
      let badge = 0;
      S.INSTANCES.forEach((inst, i) => {
        if (inst.root_id !== s.id) return;
        const y = p.y - 32 - badge * 16;
        ctx.fillStyle = instColor(i); ctx.font = 'bold 11px sans-serif';
        ctx.fillText('★ ' + inst.id, p.x, y);
        badge++;
      });
    }
    drawOverlayLegend(ctx);
  }

  function drawOverlayLegend(ctx) {
    const lx = 16, ly = 14, lw = 200, lh = 30 + (S.INSTANCES.length + 2) * 20;
    ctx.fillStyle = 'rgba(15,23,42,.85)';
    ctx.strokeStyle = '#334155'; ctx.lineWidth = 1;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(lx, ly, lw, lh, 8); else ctx.rect(lx, ly, lw, lh);
    ctx.fill(); ctx.stroke();
    let yy = ly + 24;
    ctx.textAlign = 'left'; ctx.font = '11.5px sans-serif';
    S.INSTANCES.forEach((inst, i) => {
      ctx.strokeStyle = instColor(i); ctx.lineWidth = 4;
      ctx.beginPath(); ctx.moveTo(lx + 12, yy - 4); ctx.lineTo(lx + 40, yy - 4); ctx.stroke();
      ctx.fillStyle = '#e2e8f0';
      ctx.fillText(inst.id + '（单色=仅此实例转发）', lx + 48, yy);
      yy += 20;
    });
    ctx.strokeStyle = instColor(0); ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(lx + 12, yy - 7); ctx.lineTo(lx + 40, yy - 7); ctx.stroke();
    ctx.strokeStyle = instColor(1); ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(lx + 12, yy - 1); ctx.lineTo(lx + 40, yy - 1); ctx.stroke();
    ctx.fillStyle = '#e2e8f0';
    ctx.fillText('并行双色=多实例转发', lx + 48, yy);
    yy += 20;
    ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 2.5; ctx.setLineDash([6, 5]);
    ctx.beginPath(); ctx.moveTo(lx + 12, yy - 4); ctx.lineTo(lx + 40, yy - 4); ctx.stroke();
    ctx.setLineDash([]);
    drawX(ctx, { x: lx + 26, y: yy - 4 }, '#ef4444');
    ctx.fillStyle = '#e2e8f0';
    ctx.fillText('全实例冗余（阻塞）', lx + 48, yy);
  }

  function drawCostLabel(ctx, l, p1, p2, role) {
    const mid = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 - 7 };
    const costText = '成本 ' + l.cost;
    ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
    const costW = ctx.measureText(costText).width;
    ctx.fillStyle = 'rgba(30,41,59,.92)';
    ctx.fillRect(mid.x - costW / 2 - 3, mid.y - 11, costW + 6, 15);
    ctx.fillStyle = role === 'down' ? '#7f1d1d' : '#94a3b8';
    ctx.fillText(costText, mid.x, mid.y);
  }

  function draw(now) {
    if (!S.ready) return;
    const ctx = S.ctx;
    ctx.clearRect(0, 0, W, H);
    const st = S.steps[S.cur];
    if (S.overlayMode) {
      drawOverlay(ctx);
      rafHandle = requestAnimationFrame(draw);
      return;
    }
    const isFinal = st.kind === 'final';
    const stateMap = st.links || (isFinal && st.roles ? st.roles.links : null);
    const blockedEnds = st.blocked_ends ||
      (isFinal && st.roles ? st.roles.blocked_ends : null);

    for (const l of S.topo.links) {
      if (l.appear_at !== undefined && S.cur < l.appear_at) continue;
      const p1 = S.pos[l.a], p2 = S.pos[l.b];
      const role = stateMap ? stateMap[l.id] : null;
      let color = '#475569', width = 2, dash = [];
      if (role === 'tree' || role === 'forwarding') { color = '#22c55e'; width = 4; }
      if (role === 'blocked' || role === 'alternate') { color = '#ef4444'; width = 2.5; dash = [9, 7]; }
      if (role === 'down') { color = '#b91c1c'; width = 4; dash = [3, 6]; }
      ctx.strokeStyle = color; ctx.lineWidth = width; ctx.setLineDash(dash);
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
      ctx.setLineDash([]);
      drawCostLabel(ctx, l, p1, p2, role === 'down' ? 'down' : null);
      if (role === 'down') {
        drawX(ctx, { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 }, '#ef4444');
      } else if ((role === 'blocked' || role === 'alternate') &&
                 blockedEnds && blockedEnds[l.id]) {
        const blockedSw = blockedEnds[l.id];
        const other = S.pos[blockedSw === l.a ? l.b : l.a];
        drawX(ctx, lerp(S.pos[blockedSw], other, 0.3), '#ef4444');
      }
    }

    for (const h of S.hosts) {
      const s = S.pos[h.attached_to], p = S.hpos[h.id];
      ctx.strokeStyle = '#64748b'; ctx.lineWidth = 2; ctx.setLineDash([5, 5]);
      ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(p.x, p.y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#64748b'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText('边缘', (s.x + p.x) / 2, (s.y + p.y) / 2 - 6);
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(p.x - 24, p.y - 16, 48, 32, 6);
      else ctx.rect(p.x - 24, p.y - 16, 48, 32);
      ctx.fillStyle = '#475569'; ctx.fill();
      ctx.fillStyle = '#e2e8f0'; ctx.font = 'bold 12px sans-serif';
      ctx.fillText(h.id, p.x, p.y + 4);
    }

    if (st.kind === 'round') {
      for (const sid in st.switches) {
        const rp = st.switches[sid].root_port;
        if (rp) drawArrow(ctx, lerp(S.pos[sid], S.pos[rp], 0.58), S.pos[rp], '#22c55e');
      }
    }

    for (const s of S.topo.switches) {
      if (s.appear_at !== undefined && S.cur < s.appear_at) continue;
      if (!st.switches[s.id]) continue;
      const p = S.pos[s.id];
      const info = st.switches[s.id];
      const isRoot = isFinal && st.roles.root === s.id;
      ctx.beginPath(); ctx.arc(p.x, p.y, NODE_R, 0, 2 * Math.PI);
      ctx.fillStyle = isRoot ? '#f59e0b' : '#3b82f6'; ctx.fill();
      if (!isFinal && info.root === s.id) {
        ctx.lineWidth = 4; ctx.strokeStyle = '#facc15'; ctx.stroke();
      }
      ctx.fillStyle = '#fff'; ctx.font = 'bold 14px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(s.id, p.x, p.y + 5);
      if (isRoot) {
        ctx.fillStyle = '#fde68a'; ctx.font = 'bold 16px sans-serif';
        ctx.fillText('★', p.x, p.y - 34);
      }
      ctx.fillStyle = '#94a3b8'; ctx.font = '11px sans-serif';
      ctx.fillText(s.bridge_id, p.x, p.y + NODE_R + 16);
      ctx.fillStyle = isFinal ? '#86efac' : '#cbd5e1'; ctx.font = '11.5px sans-serif';
      ctx.fillText(portLine(s.id, st), p.x, p.y + NODE_R + 32);
    }

    if (st.kind === 'round' || st.kind === 'handshake' ||
        st.kind === 'switch-online') {
      let maxDelay = 0;
      for (const pk of S.packets) maxDelay = Math.max(maxDelay, pk.delay);
      ctx.font = '10px sans-serif';
      for (const pk of S.packets) {
        const t = Math.min(1, Math.max(0,
          (now - S.enterTime) / (PACKET_MS / S.speed) - pk.delay));
        if (t <= 0 && pk.delay > 0) continue;
        const q = lerp(pk.from, pk.to, t);
        ctx.beginPath(); ctx.arc(q.x, q.y, 7, 0, 2 * Math.PI);
        ctx.fillStyle = pk.color; ctx.fill();
        ctx.strokeStyle = pk.ring; ctx.lineWidth = 1.5; ctx.stroke();
        ctx.fillStyle = '#fde68a'; ctx.textAlign = 'center';
        ctx.fillText(pk.label, q.x, q.y - 11);
      }
      if (S.playing &&
          now > S.enterTime + ((1 + maxDelay) * PACKET_MS + HOLD_MS) / S.speed) {
        advance();
      }
    } else if (S.playing && now > S.enterTime + 500 / S.speed) {
      advance();
    }
    rafHandle = requestAnimationFrame(draw);
  }

  function advance() {
    if (S.cur < S.steps.length - 1) setStep(S.cur + 1, true);
    else { S.playing = false; updateButtons(); }
  }

  function buildConceptModal() {
    const modal = $('concept-modal');
    if (!S.DATA.concept) { $('btn-concept').style.display = 'none'; return; }
    $('btn-concept').style.display = '';
    const c = S.DATA.concept;
    let html = '<h2>' + c.title + '</h2>';
    if (c.scenario) html += '<p class="scenario">' + c.scenario + '</p>';
    html += '<h3>要解决的问题</h3><p>' + c.problem + '</p>';
    html += '<h3>核心思路</h3><p>' + c.idea + '</p>';
    if (c.rules) {
      html += '<h3>关键规则</h3><ul>' +
              c.rules.map(r => '<li>' + r + '</li>').join('') + '</ul>';
    }
    if (c.glossary) {
      html += '<h3>术语速查</h3><dl>' +
              c.glossary.map(g => '<dt>' + g[0] + '</dt><dd>' + g[1] + '</dd>')
                        .join('') + '</dl>';
    }
    $('concept-body').innerHTML = html;
    modal.classList.remove('open');
  }

  function buildTabs() {
    const holder = $('tabs');
    holder.innerHTML = '';
    if (!S.INSTANCES) { holder.style.display = 'none'; return; }
    holder.style.display = 'flex';
    S.INSTANCES.forEach((inst, i) => {
      const btn = document.createElement('button');
      btn.textContent = inst.id +
        (inst.vlans.length > 1 ? '（VLAN ' + inst.vlans.join(',') + '）' : '');
      btn.onclick = () => switchInstance(i);
      holder.appendChild(btn);
    });
    const overlayBtn = document.createElement('button');
    overlayBtn.className = 'overlay';
    overlayBtn.textContent = '叠加对比';
    overlayBtn.onclick = () => switchInstance(S.INSTANCES.length);
    holder.appendChild(overlayBtn);
    updateTabs();
  }

  function updateTabs() {
    if (!S.INSTANCES) return;
    [...$('tabs').children].forEach((btn, i) =>
      btn.classList.toggle('active', S.overlayMode ? i === S.INSTANCES.length
                                                   : i === S.instIdx));
  }

  function switchInstance(i) {
    if (!S.INSTANCES) return;
    if (i === S.INSTANCES.length) {
      S.cursors[S.instIdx] = S.cur;
      S.overlayMode = true;
      S.playing = false;
      S.enterTime = performance.now();
      S.packets = [];
      renderPanels();
      updateButtons();
      updateTabs();
      return;
    }
    if (i === S.instIdx && !S.overlayMode) return;
    S.cursors[S.instIdx] = S.cur;
    S.overlayMode = false;
    S.instIdx = i;
    S.steps = S.INSTANCES[i].steps;
    S.playing = false;
    setStep(S.cursors[i]);
    updateTabs();
  }

  function bindControls() {
    if (keysBound) return;
    keysBound = true;
    $('btn-first').onclick = () => setStep(0);
    $('btn-prev').onclick = () => setStep(S.cur - 1);
    $('btn-next').onclick = () => setStep(S.cur + 1);
    $('btn-last').onclick = () => setStep(S.steps.length - 1);
    $('btn-play').onclick = () => {
      if (!S.playing && S.cur === S.steps.length - 1) setStep(0);
      S.playing = !S.playing; S.enterTime = performance.now(); updateButtons();
    };
    $('speed').onchange = e => { S.speed = parseFloat(e.target.value); };
    $('btn-concept').onclick = () => $('concept-modal').classList.add('open');
    $('concept-modal').onclick = e => {
      if (e.target === $('concept-modal')) $('concept-modal').classList.remove('open');
    };
    $('concept-close').onclick = () => $('concept-modal').classList.remove('open');
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') $('concept-modal').classList.remove('open');
      if (!S.ready || S.overlayMode) return;
      if (e.key === 'ArrowLeft') { setStep(S.cur - 1); e.preventDefault(); }
      else if (e.key === 'ArrowRight') { setStep(S.cur + 1); e.preventDefault(); }
      else if (e.key === ' ') { $('btn-play').click(); e.preventDefault(); }
      else if (e.key === 'Home') { setStep(0); e.preventDefault(); }
      else if (e.key === 'End') { setStep(S.steps.length - 1); e.preventDefault(); }
    });
  }

  function bootPlayer(data) {
    if (rafHandle !== null) cancelAnimationFrame(rafHandle);
    const canvas = $('stage');
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.aspectRatio = W + ' / ' + H;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    S.DATA = data;
    S.topo = data.topology;
    S.INSTANCES = data.instances || null;
    S.cursors = S.INSTANCES ? S.INSTANCES.map(() => 0) : null;
    S.instIdx = 0;
    S.overlayMode = false;
    S.steps = S.INSTANCES ? S.INSTANCES[0].steps : data.steps;
    S.cur = 0;
    S.playing = false;
    S.speed = parseFloat(($('speed') && $('speed').value) || '1');
    S.enterTime = performance.now();
    S.packets = [];
    S.ctx = ctx;

    const topo = S.topo;
    const N = topo.switches.length;
    S.pos = {};
    const deferredPos = [];
    topo.switches.forEach((s, i) => {
      const custom = data.positions && data.positions[s.id];
      if (custom) {
        S.pos[s.id] = { x: 70 + custom.x * (W - 140), y: 60 + custom.y * (H - 120) };
      } else if (s.appear_at !== undefined) {
        deferredPos.push(s.id);
      } else {
        const a = -Math.PI / 2 + 2 * Math.PI * i / N;
        S.pos[s.id] = { x: CX + R * Math.cos(a), y: CY + R * Math.sin(a) };
      }
    });
    deferredPos.forEach(sid => {
      const link = topo.links.find(l =>
        (l.a === sid || l.b === sid) && S.pos[l.a === sid ? l.b : l.a]);
      if (!link) { S.pos[sid] = { x: CX, y: CY }; return; }
      const anchor = S.pos[link.a === sid ? link.b : link.a];
      const dx = anchor.x - CX, dy = anchor.y - CY;
      const len = Math.hypot(dx, dy) || 1;
      S.pos[sid] = { x: anchor.x + dx / len * 95, y: anchor.y + dy / len * 95 };
    });
    S.hosts = topo.hosts || [];
    S.hpos = {};
    S.hosts.forEach(h => {
      const s = S.pos[h.attached_to];
      const dx = s.x - CX, dy = s.y - CY;
      const len = Math.hypot(dx, dy) || 1;
      S.hpos[h.id] = { x: s.x + dx / len * 95, y: s.y + dy / len * 95 };
    });

    bindControls();
    $('title').textContent = data.title;
    $('subtitle').textContent = data.subtitle;
    buildConceptModal();
    buildTabs();
    S.ready = true;
    setStep(0);
    rafHandle = requestAnimationFrame(draw);
  }

  window.bootPlayer = bootPlayer;
  // Small test/debug hook (mirrors window.EDITOR in the editor page).
  window.PLAYER = { setStep: i => setStep(i) };
  if (window.PLAYER_DATA) bootPlayer(window.PLAYER_DATA);
})();
