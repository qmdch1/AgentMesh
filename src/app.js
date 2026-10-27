import { nodes, scenarios, allEdges, edgeKey, advance } from './flows.js';

const $ = id => document.getElementById(id);
const ns = 'http://www.w3.org/2000/svg';
let scenario = scenarios[2];
let state = { index: 0, status: 'paused' };
let animation = null;
let selectedNode = 'router';
let raf = null;
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const paths = new Map();

function svgElement(tag, attrs) {
  const el = document.createElementNS(ns, tag);
  Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
  return el;
}
function pathFor(from, to) {
  const a = nodes[from], b = nodes[to];
  if (to === 'omp') return `M ${a.x + 80} ${a.y + 86} C ${a.x + 80} 476, 108 476, 108 ${b.y + 86}`;
  if (a.x === b.x) {
    const down = b.y > a.y;
    return `M ${a.x + 160} ${a.y + 43} C ${a.x + 215} ${a.y + 43}, ${b.x + 215} ${b.y + 43}, ${b.x + 160} ${b.y + 43}`;
  }
  const right = b.x > a.x;
  const x1 = a.x + (right ? 160 : 0), y1 = a.y + 43;
  const x2 = b.x + (right ? 0 : 160), y2 = b.y + 43;
  const bend = (x1 + x2) / 2;
  const offset = right ? 0 : 24;
  return `M ${x1} ${y1} C ${bend} ${y1 + offset}, ${bend} ${y2 + offset}, ${x2} ${y2}`;
}
for (const edge of allEdges()) {
  const path = svgElement('path', { d: pathFor(edge.from, edge.to), class: 'connection', 'data-edge': edgeKey(edge.from, edge.to) });
  $('connections').append(path);
  paths.set(edgeKey(edge.from, edge.to), path);
}
const packet = svgElement('g', { class: 'packet', visibility: 'hidden' });
packet.append(svgElement('circle', { r: 12, fill: 'currentColor', opacity: '.15' }), svgElement('circle', { r: 5, fill: 'currentColor' }), svgElement('circle', { r: 2, fill: '#fff' }));
$('connections').append(packet);
Object.entries(nodes).forEach(([id, node]) => {
  const button = document.createElement('button');
  button.className = `node ${node.color}`;
  button.id = `node-${id}`;
  button.style.left = `${node.x / 9.2}%`;
  button.style.top = `${node.y / 4.9}%`;
  button.innerHTML = `<span class="node-tag">${node.tag}<i></i></span><strong>${node.name}</strong><span class="node-role">${node.role}</span>`;
  button.addEventListener('click', () => showNode(id));
  $('nodes').append(button);
});
scenarios.forEach(item => {
  const button = document.createElement('button');
  button.className = 'scenario';
  button.dataset.scenario = item.id;
  button.innerHTML = `<span class="scenario-icon">${item.icon}</span><span><strong>${item.title}</strong><small>${item.subtitle}</small></span><span class="scenario-arrow">↗</span>`;
  button.addEventListener('click', () => { scenario = item; reset(); });
  $('scenarios').append(button);
});
function showNode(id) {
  selectedNode = id;
  const node = nodes[id];
  document.querySelectorAll('.node').forEach(el => { el.classList.toggle('selected', el.id === `node-${id}`); el.setAttribute('aria-pressed', el.id === `node-${id}` ? 'true' : 'false'); });
  $('node-detail').innerHTML = `<div class="detail-title"><span class="detail-icon ${node.color}">◈</span><div><h2>${node.name}</h2><span>${node.role}</span></div><span class="badge">${node.tag}</span></div><p>${node.description}</p>`;
}
function render() {
  document.querySelectorAll('.scenario').forEach(el => { const active = el.dataset.scenario === scenario.id; el.classList.toggle('selected', active); el.setAttribute('aria-pressed', String(active)); });
  $('prompt').textContent = scenario.prompt;
  $('flow-title').textContent = scenario.title;
  $('run-badge').textContent = state.status === 'playing' ? '● 이동 중' : state.status === 'complete' ? '✓ 검증 완료' : state.index ? '일시정지' : '준비됨';
  $('play').textContent = state.status === 'playing' ? 'Ⅱ 일시정지' : state.status === 'complete' ? '↻ 다시 실행' : state.index ? '▶ 이어서 실행' : '▶ 흐름 실행';
  $('progress-label').textContent = `${state.index} / ${scenario.steps.length} 단계`;
  $('step').disabled = state.status === 'playing' || state.status === 'complete';
  const used = new Set(scenario.steps.map(s => edgeKey(s.from, s.to)));
  const done = new Set(scenario.steps.slice(0, state.index).map(s => edgeKey(s.from, s.to)));
  paths.forEach((path, key) => { path.classList.toggle('on-route', used.has(key)); path.classList.toggle('done', done.has(key)); });
  document.querySelectorAll('.node').forEach(el => el.classList.remove('processing'));
  if (state.status === 'playing') $('node-' + scenario.steps[state.index].from).classList.add('processing');
  $('event-count').textContent = `${state.index} EVENTS`;
  $('timeline').replaceChildren();
  if (!state.index) { const li = document.createElement('li'); li.className = 'empty-event'; li.textContent = '흐름을 실행하면 요청의 이동 경로가 여기에 기록됩니다.'; $('timeline').append(li); }
  scenario.steps.slice(0, state.index).forEach((step, index) => {
    const li = document.createElement('li');
    li.className = step.kind;
    li.innerHTML = `<span class="event-number">${String(index + 1).padStart(2, '0')}</span><div><strong>${nodes[step.from].name} <span>→</span> ${nodes[step.to].name}</strong><small>${step.label}</small></div><span class="event-check">${step.kind === 'retry' ? '↻' : '✓'}</span>`;
    $('timeline').append(li);
  });
  $('timeline').scrollTop = $('timeline').scrollHeight;
}
function clearAnimation() {
  if (raf !== null) cancelAnimationFrame(raf);
  raf = null; animation = null;
  packet.setAttribute('visibility', 'hidden');
  paths.forEach(path => path.classList.remove('active', 'cloud', 'retry'));
}
function reset() {
  clearAnimation();
  state = { index: 0, status: 'paused' };
  render(); showNode(selectedNode);
}
function tick(time) {
  if (state.status !== 'playing') return;
  const step = scenario.steps[state.index];
  const path = paths.get(edgeKey(step.from, step.to));
  if (!animation) animation = { progress: 0, lastTime: time };
  const delta = Math.min(time - animation.lastTime, 100);
  animation.lastTime = time;
  animation.progress = Math.min(1, animation.progress + delta / 1500 * Number($('speed').value));
  path.classList.add('active', step.kind === 'retry' ? 'retry' : step.kind === 'cloud' ? 'cloud' : 'local');
  packet.style.color = step.kind === 'retry' ? '#f5b275' : step.kind === 'cloud' ? '#b4a1fa' : '#69dfc3';
  // Reduced motion retains discrete progress and timeline updates without moving packets.
  if (!reducedMotion) {
    const point = path.getPointAtLength(path.getTotalLength() * animation.progress);
    packet.setAttribute('transform', `translate(${point.x} ${point.y})`);
    packet.setAttribute('visibility', 'visible');
  }
  if (animation.progress === 1) {
    clearAnimation();
    state = advance(state, scenario.steps.length);
    if (state.status !== 'complete') state.status = 'playing';
    render();
  }
  if (state.status === 'playing') raf = requestAnimationFrame(tick);
}
$('play').addEventListener('click', () => {
  if (state.status === 'playing') {
    state.status = 'paused';
    if (raf !== null) cancelAnimationFrame(raf);
    raf = null;
    render(); return;
  }
  if (state.status === 'complete') reset();
  state.status = 'playing';
  if (animation) animation.lastTime = performance.now();
  render(); raf = requestAnimationFrame(tick);
});
$('step').addEventListener('click', () => { clearAnimation(); state = advance(state, scenario.steps.length); render(); });
$('reset').addEventListener('click', reset);
reset();
