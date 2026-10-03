/* ==========================================================================
   Denki – Frontend-Logik (reines ES2020, keine Build-Schritte, keine Cloud)
   ========================================================================== */

const API = {
  health: () => fetch('/api/health').then(j),
  chat: (message, session_id) => post('/api/chat', { message, session_id }),
  facts: (status = 'active', q = '') =>
    fetch(`/api/facts?status=${encodeURIComponent(status)}${q ? `&q=${encodeURIComponent(q)}` : ''}`).then(j),
  stats: () => fetch('/api/stats').then(j),
  events: (limit = 30) => fetch(`/api/events?limit=${limit}`).then(j),
  sessions: () => fetch('/api/sessions').then(j),
  newSession: () => post('/api/sessions', {}),
  session: (id) => fetch(`/api/sessions/${id}`).then(j),
  deleteSession: (id) => del(`/api/sessions/${id}`),
  confirmFact: (id) => post(`/api/confirm/${id}`, {}),
  confirmAll: () => post('/api/confirm', {}),
  patchFact: (id, body) => fetch(`/api/facts/${id}`, { method: 'PATCH', headers: jsonHeaders(), body: JSON.stringify(body) }).then(j),
  deleteFact: (id) => del(`/api/facts/${id}`),
  reset: () => post('/api/memory/reset', {}),
};

const jsonHeaders = () => ({ 'Content-Type': 'application/json' });

async function j(res) {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}
const post = (url, body) => fetch(url, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body || {}) }).then(j);
const del = (url) => fetch(url, { method: 'DELETE' }).then(j);

/* ----------------------------- Zustand ----------------------------- */

const state = {
  sessionId: localStorage.getItem('denki.session') || null,
  health: null,
  facts: [],
  stats: null,
  busy: false,
  lastIntent: '–',
  highlight: new Set(),
};

const $ = (sel) => document.querySelector(sel);
const el = {
  messages: $('#messages'),
  chatScroll: $('#chatScroll'),
  welcome: $('#welcome'),
  typing: $('#typing'),
  input: $('#input'),
  composer: $('#composer'),
  sendBtn: $('#sendBtn'),
  sessionList: $('#sessionList'),
  factList: $('#factList'),
  eventList: $('#eventList'),
  factSearch: $('#factSearch'),
  statusFilter: $('#statusFilter'),
  topicCloud: $('#topicCloud'),
  toasts: $('#toasts'),
};

/* ----------------------------- Helpers ------------------------------ */

function escapeHtml(s = '') {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** Sehr kleiner Markdown-Renderer: Überschriften, Listen, fett, kursiv, code. */
function renderMarkdown(text = '') {
  const blocks = String(text).split(/\n{2,}/);
  return blocks.map((block) => {
    const lines = block.split('\n').filter((l) => l.trim() !== '');
    if (!lines.length) return '';
    const inline = (l) => escapeHtml(l)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
      .replace(/_([^_]+)_/g, '<em>$1</em>');

    if (/^#{1,6}\s/.test(lines[0])) {
      const level = Math.min(6, (lines[0].match(/^#+/) || ['#'])[0].length + 1);
      return `<h${level}>${inline(lines.map((l) => l.replace(/^#+\s*/, '')).join(' '))}</h${level}>`;
    }
    if (lines.every((l) => /^\s*(?:[-*•]\s|\d+[.)]\s)/.test(l))) {
      const ordered = /^\s*\d+[.)]\s/.test(lines[0]);
      const items = lines.map((l) => `<li>${inline(l.replace(/^\s*(?:[-*•]\s|\d+[.)]\s)/, ''))}</li>`).join('');
      return ordered ? `<ol>${items}</ol>` : `<ul>${items}</ul>`;
    }
    return `<p>${lines.map(inline).join('<br>')}</p>`;
  }).join('');
}

function toast(title, message = '', kind = 'info', ttl = 4200) {
  const node = document.createElement('div');
  node.className = `toast ${kind}`;
  node.innerHTML = `<strong>${escapeHtml(title)}</strong>${message ? `<p>${escapeHtml(message)}</p>` : ''}`;
  el.toasts.appendChild(node);
  setTimeout(() => {
    node.style.transition = 'opacity .3s, transform .3s';
    node.style.opacity = '0';
    node.style.transform = 'translateY(6px)';
    setTimeout(() => node.remove(), 320);
  }, ttl);
}

function scrollDown() {
  el.chatScroll.scrollTop = el.chatScroll.scrollHeight;
}

function fmtPct(v) { return `${Math.round((Number(v) || 0) * 100)} %`; }

function relTime(iso) {
  if (!iso) return '–';
  const then = new Date(iso);
  const diff = (Date.now() - then.getTime()) / 1000;
  if (diff < 60) return 'gerade eben';
  if (diff < 3600) return `vor ${Math.floor(diff / 60)} Min.`;
  if (diff < 86400) return `vor ${Math.floor(diff / 3600)} Std.`;
  if (diff < 86400 * 7) return `vor ${Math.floor(diff / 86400)} Tg.`;
  return then.toLocaleDateString('de-DE');
}

/* ------------------------------ Chat -------------------------------- */

function addMessage(role, content, meta = {}) {
  el.welcome.hidden = true;
  const wrap = document.createElement('div');
  wrap.className = `msg ${role}`;
  wrap.innerHTML = `
    <div class="avatar">${role === 'assistant' ? '⚡' : 'DU'}</div>
    <div class="bubble"><div class="content"></div><div class="msg-meta"></div></div>`;
  wrap.querySelector('.content').innerHTML = renderMarkdown(content);
  if (role === 'assistant') fillMeta(wrap.querySelector('.msg-meta'), meta);
  el.messages.appendChild(wrap);
  scrollDown();
  return wrap;
}

const INTENT_LABELS = {
  greeting: 'Begrüßung', farewell: 'Abschied', thanks: 'Danke', confirm: 'Bestätigung',
  deny: 'Widerspruch', forget: 'Vergessen', ask_memory: 'Frage ans Gedächtnis',
  list_memories: 'Gedächtnis-Liste', ask_profile: 'Wer bist du?', ask_identity: 'Herkunft',
  ask_capabilities: 'Fähigkeiten', ask_help: 'Hilfe', ask_time: 'Zeit/Datum',
  ask_mood: 'Befinden', ask_howdoing: 'Smalltalk', ask_local_privacy: 'Datenschutz',
  smalltalk: 'Smalltalk', statement: 'Aussage', question: 'Frage', fallback: 'Allgemein',
};

function fillMeta(node, meta) {
  if (!meta) return;
  const parts = [];
  if (meta.intent?.name) {
    parts.push(`<span class="tag intent" title="Erkannter Intent (Konfidenz ${meta.intent.confidence})">Intent: ${escapeHtml(INTENT_LABELS[meta.intent.name] || meta.intent.name)}</span>`);
  }
  (meta.recalled || []).forEach((f) => {
    parts.push(`<span class="tag recall" data-fact="${f.id}" title="Erinnerung mit Relevanz ${fmtPct(f.score)} · Vertrauen ${fmtPct(f.confidence)}">🧠 ${escapeHtml(f.label)}</span>`);
  });
  const events = meta.learning?.events || [];
  const kindIcon = { extracted: '✨', reinforced: '🔁', corrected: '✏️', forgotten: '🗑️', confirmed: '✅' };
  const kindLabel = { extracted: 'neu gelernt', reinforced: 'verstärkt', corrected: 'korrigiert', forgotten: 'vergessen', confirmed: 'bestätigt' };
  events.forEach((e) => {
    if (e.kind === 'nothing') return;
    parts.push(`<span class="tag ${e.kind}" title="${escapeHtml(e.detail || '')}">${kindIcon[e.kind] || ''} ${kindLabel[e.kind] || e.kind}: ${escapeHtml(e.label || '')}</span>`);
  });
  if (meta.brain) {
    parts.push(`<span class="tag" title="Antwort erzeugt von">${escapeHtml(meta.brain)}${meta.model ? ` · ${escapeHtml(meta.model)}` : ''}</span>`);
  }
  if (meta.note) parts.push(`<span class="tag forgotten" title="Hinweis">${escapeHtml(meta.note)}</span>`);
  node.innerHTML = parts.join('');
  node.querySelectorAll('.tag.recall').forEach((tag) => {
    tag.addEventListener('click', () => focusFact(Number(tag.dataset.fact)));
  });
}

/** Antwort mit Tipp-Effekt (Blöcke werden schrittweise sichtbar). */
async function streamAnswer(text, meta) {
  el.welcome.hidden = true;
  const wrap = document.createElement('div');
  wrap.className = 'msg assistant';
  wrap.innerHTML = `
    <div class="avatar">⚡</div>
    <div class="bubble"><div class="content"><span class="cursor"></span></div><div class="msg-meta"></div></div>`;
  el.messages.appendChild(wrap);
  const content = wrap.querySelector('.content');
  const chunks = String(text).split(/(?<=[.!?:\n])\s+/);
  let shown = '';
  for (const chunk of chunks) {
    shown += (shown ? ' ' : '') + chunk;
    content.innerHTML = renderMarkdown(shown) + '<span class="cursor"></span>';
    scrollDown();
    await sleep(Math.min(140, 22 + chunk.length * 2.4));
  }
  content.innerHTML = renderMarkdown(text);
  fillMeta(wrap.querySelector('.msg-meta'), meta);
  scrollDown();
  return wrap;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function send(text) {
  const message = (text ?? el.input.value).trim();
  if (!message || state.busy) return;

  state.busy = true;
  el.sendBtn.disabled = true;
  el.input.value = '';
  autoGrow();
  addMessage('user', message);
  el.typing.hidden = false;
  scrollDown();

  try {
    const data = await API.chat(message, state.sessionId);
    el.typing.hidden = true;

    state.sessionId = data.session_id;
    localStorage.setItem('denki.session', data.session_id);
    state.lastIntent = data.intent?.name || '–';
    $('#insightIntent').textContent = INTENT_LABELS[state.lastIntent] || state.lastIntent;

    await streamAnswer(data.reply, {
      intent: data.intent,
      recalled: data.recalled,
      learning: data.learning,
      brain: data.brain,
      model: data.model,
    });

    applyLearning(data.learning, data.stats);
    await refresh({ sessions: true });
  } catch (err) {
    el.typing.hidden = true;
    addMessage('assistant', `⚠️ Da ist etwas schiefgelaufen: ${err.message}\n\nLäuft der Denki-Server noch? (` + 'python run.py`)', {});
    toast('Fehler', err.message, 'error');
  } finally {
    state.busy = false;
    el.sendBtn.disabled = false;
    el.input.focus();
  }
}

/** Reagiert auf Lern-Ereignisse: Toasts + Highlight im Gedächtnis-Panel. */
function applyLearning(learning, stats) {
  const events = learning?.events || [];
  const label = { extracted: 'Neu gelernt', reinforced: 'Verstärkt', corrected: 'Korrektur übernommen', forgotten: 'Vergessen', confirmed: 'Bestätigt' };
  events.forEach((e) => {
    if (e.kind === 'nothing') return;
    state.highlight.add(e.fact_id);
    if (e.fact_id) setTimeout(() => state.highlight.delete(e.fact_id), 6000);
    toast(label[e.kind] || e.kind, `${e.label}${e.detail ? ` · ${e.detail}` : ''}`,
      e.kind === 'forgotten' ? 'error' : 'success', 3600);
  });
  if (stats) renderStats(stats);
}

/* --------------------------- Gedächtnis-Panel ------------------------- */

async function loadFacts() {
  const q = el.factSearch.value.trim();
  const status = el.statusFilter.value;
  const data = await API.facts(status, q);
  state.facts = data.facts;
  renderFacts();
}

function renderFacts() {
  if (!state.facts.length) {
    el.factList.innerHTML = `<li class="empty">${el.factSearch.value ? 'Keine Treffer.' : 'Noch nichts gelernt – erzähl mir etwas im Chat.'}</li>`;
    return;
  }
  el.factList.innerHTML = state.facts.map((f) => {
    const conf = Math.round((f.confidence || 0) * 100);
    const learned = state.highlight.has(f.id) ? ' just-learned' : '';
    const statusLabel = { active: 'aktiv', superseded: 'ersetzt', forgotten: 'vergessen' }[f.status] || f.status;
    return `
      <li class="fact ${f.status}${learned}" data-id="${f.id}">
        <div class="fact-head">
          <span class="fact-cat">${escapeHtml(f.category_label || f.category)}</span>
          <span class="fact-status">${escapeHtml(statusLabel)} · ${relTime(f.updated_at)}</span>
        </div>
        <p class="fact-label" data-role="label">${escapeHtml(f.label)}</p>
        <div class="meter" title="Vertrauen ${conf} %"><span style="width:${conf}%"></span></div>
        <div class="fact-foot">
          <div class="fact-stats">
            <span title="Vertrauen">🎯 ${conf} %</span>
            <span title="Wie oft gelernt">🔁 ${f.times_learned}×</span>
            <span title="Wie oft abgerufen">🧠 ${f.times_recalled}×</span>
          </div>
          <div class="fact-actions">
            <button class="icon-btn" data-act="confirm" title="Bestätigen (Vertrauen +)">✓</button>
            <button class="icon-btn" data-act="edit" title="Bearbeiten">✎</button>
            <button class="icon-btn danger" data-act="delete" title="Löschen">🗑</button>
          </div>
        </div>
      </li>`;
  }).join('');
}

function focusFact(id) {
  document.querySelector('.tab[data-tab="memory"]').click();
  const node = el.factList.querySelector(`.fact[data-id="${id}"]`);
  if (!node) { loadFacts().then(() => focusFact(id)); return; }
  node.scrollIntoView({ behavior: 'smooth', block: 'center' });
  node.classList.add('just-learned');
  setTimeout(() => node.classList.remove('just-learned'), 2500);
}

el.factList.addEventListener('click', async (ev) => {
  const btn = ev.target.closest('button[data-act]');
  if (!btn) return;
  const li = btn.closest('.fact');
  const id = Number(li.dataset.id);
  const fact = state.facts.find((f) => f.id === id);
  const act = btn.dataset.act;

  try {
    if (act === 'confirm') {
      const data = await API.confirmFact(id);
      toast('Bestätigt', fact?.label || `Fakt #${id}`, 'success', 2600);
      renderStats(data.stats);
      await loadFacts();
    } else if (act === 'delete') {
      const data = await API.deleteFact(id);
      toast('Vergessen', fact?.label || `Fakt #${id}`, 'error', 2600);
      renderStats(data.stats);
      await loadFacts();
    } else if (act === 'edit') {
      const labelNode = li.querySelector('[data-role="label"]');
      if (labelNode.querySelector('input')) return;
      const current = fact?.label || '';
      labelNode.innerHTML = `<input value="${escapeHtml(current)}" />`;
      const input = labelNode.querySelector('input');
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
      const commit = async () => {
        const value = input.value.trim();
        if (!value || value === current) { labelNode.textContent = current; return; }
        const data = await API.patchFact(id, { label: value, confidence: Math.min(0.97, (fact?.confidence || 0.5) + 0.1) });
        labelNode.textContent = value;
        toast('Korrigiert', 'Denki hat die Erinnerung überschrieben.', 'success', 2600);
        renderStats(data.stats);
        await loadFacts();
      };
      input.addEventListener('blur', commit, { once: true });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { labelNode.textContent = current; input.remove(); }
      });
    }
  } catch (err) {
    toast('Fehler', err.message, 'error');
  }
});

/* --------------------------- Stats & Insights -------------------------- */

function renderStats(stats) {
  state.stats = stats;
  $('#statFacts').textContent = stats.facts_active;
  $('#statLearned').textContent = stats.learned_total;
  $('#statRecalled').textContent = stats.recalled_total;
  $('#statSuperseded').textContent = stats.facts_superseded;
  $('#statForgotten').textContent = stats.facts_forgotten;
  $('#statMessages').textContent = stats.messages_total;
  $('#masteryValue').textContent = fmtPct(stats.mastery);
  $('#masteryBar').style.width = `${Math.round(stats.mastery * 100)}%`;
  $('#masteryExplain').textContent =
    `${stats.facts_active} aktive Erinnerungen · Ø Vertrauen ${fmtPct(stats.avg_confidence)} · stärkste Erinnerung ${stats.strongest_fact_repetitions}× gelernt`;

  const maxHits = Math.max(1, ...(stats.top_topics || []).map((t) => t.hits));
  el.topicCloud.innerHTML = (stats.top_topics || []).length
    ? stats.top_topics.map((t) => `<span class="${t.hits >= maxHits * 0.7 ? 'hot' : ''}" title="${t.hits} Treffer">${escapeHtml(t.topic)}</span>`).join('')
    : '<span class="muted">–</span>';

  const maxCat = Math.max(1, ...(stats.categories || []).map((c) => c.n));
  $('#categoryBars').innerHTML = (stats.categories || []).length
    ? stats.categories.map((c) => `
        <li>
          <div class="bar-head"><span>${escapeHtml(c.label)}</span><span>${c.n}</span></div>
          <div class="meter"><span style="width:${Math.round((c.n / maxCat) * 100)}%"></span></div>
        </li>`).join('')
    : '<li class="empty">Noch keine Kategorien.</li>';

  renderEvents(stats.recent_events || []);
}

function renderEvents(events) {
  const label = { extracted: 'neu', reinforced: 'verstärkt', corrected: 'korrigiert', forgotten: 'vergessen', confirmed: 'bestätigt' };
  el.eventList.innerHTML = events.length
    ? events.map((e) => `
        <li>
          <span class="kind ${e.kind}">${label[e.kind] || e.kind}</span>
          <span class="body">
            <p>${escapeHtml(e.label || `Fakt #${e.fact_id ?? '–'}`)}</p>
            <p class="detail">${escapeHtml(e.detail || '')} · ${relTime(e.created_at)}</p>
          </span>
        </li>`).join('')
    : '<li class="empty">Noch keine Lern-Ereignisse.</li>';
}

/* ------------------------------ Sessions ------------------------------- */

async function loadSessions() {
  const data = await API.sessions();
  const sessions = data.sessions || [];
  if (!sessions.length) {
    el.sessionList.innerHTML = '<li class="empty">Noch keine Gespräche.</li>';
    return;
  }
  el.sessionList.innerHTML = sessions.map((s) => `
    <li data-id="${s.id}" class="${s.id === state.sessionId ? 'active' : ''}">
      <span class="title">${escapeHtml(s.title || 'Ohne Titel')}</span>
      <span class="count">${s.message_count}</span>
      <button class="del" title="Löschen">✕</button>
    </li>`).join('');
}

el.sessionList.addEventListener('click', async (ev) => {
  const li = ev.target.closest('li[data-id]');
  if (!li) return;
  const id = li.dataset.id;

  if (ev.target.closest('.del')) {
    await API.deleteSession(id);
    if (state.sessionId === id) { state.sessionId = null; localStorage.removeItem('denki.session'); el.messages.innerHTML = ''; el.welcome.hidden = false; }
    await Promise.all([loadSessions(), refresh({})]);
    toast('Gelöscht', 'Gespräch entfernt – das Gedächtnis bleibt erhalten.', 'info', 2600);
    return;
  }

  const data = await API.session(id);
  state.sessionId = id;
  localStorage.setItem('denki.session', id);
  el.messages.innerHTML = '';
  el.welcome.hidden = true;
  (data.messages || []).forEach((m) => addMessage(m.role, m.content, m.meta));
  loadSessions();
  scrollDown();
});

async function newChat() {
  const session = await API.newSession();
  state.sessionId = session.id;
  localStorage.setItem('denki.session', session.id);
  el.messages.innerHTML = '';
  el.welcome.hidden = false;
  el.input.focus();
  loadSessions();
}

/* ------------------------------- UI-Events ------------------------------ */

function autoGrow() {
  el.input.style.height = 'auto';
  el.input.style.height = `${Math.min(190, el.input.scrollHeight)}px`;
}

el.composer.addEventListener('submit', (ev) => { ev.preventDefault(); send(); });
el.input.addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); send(); }
});
el.input.addEventListener('input', autoGrow);

document.querySelectorAll('.suggestion').forEach((btn) => {
  btn.addEventListener('click', () => send(btn.textContent.trim()));
});

$('#newChatBtn').addEventListener('click', newChat);

$('#resetBtn').addEventListener('click', async () => {
  if (!confirm('Komplettes Denki-Gedächtnis löschen? Das ist endgültig und betrifft Fakten, Verlauf und Themen.')) return;
  await API.reset();
  el.messages.innerHTML = '';
  el.welcome.hidden = false;
  state.sessionId = null;
  localStorage.removeItem('denki.session');
  await refresh({ sessions: true });
  toast('Gedächtnis geleert', 'Alles auf Null – Denki lernt ab jetzt neu.', 'error');
});

$('#confirmAllBtn').addEventListener('click', async () => {
  const data = await API.confirmAll();
  toast('Alles bestätigt', `${data.count} Erinnerungen im Vertrauen gestärkt.`, 'success');
  await refresh({});
});

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.tab-body').forEach((b) => b.classList.remove('active'));
    tab.classList.add('active');
    document.querySelector(`#tab-${tab.dataset.tab}`).classList.add('active');
    if (tab.dataset.tab === 'log') loadEvents();
  });
});

let searchTimer;
el.factSearch.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadFacts, 220);
});
el.statusFilter.addEventListener('change', loadFacts);

async function loadEvents() {
  const data = await API.events(40);
  renderEvents(data.events || []);
}

/* ------------------------------ Boot ----------------------------------- */

async function refresh({ sessions = false } = {}) {
  const [stats] = await Promise.all([API.stats(), loadFacts(), sessions ? loadSessions() : Promise.resolve()]);
  renderStats(stats);
}

function renderHealth(health) {
  state.health = health;
  const chip = $('#brainChip');
  const label = $('#brainLabel');
  chip.classList.remove('ok', 'mock');
  if (health.brain === 'ollama') {
    chip.classList.add('ok');
    label.textContent = `Lokales LLM · ${health.brain_model}`;
  } else {
    chip.classList.add('mock');
    label.textContent = health.ollama_available
      ? 'Mock-KI (Ollama verfügbar)'
      : 'Mock-KI · offline';
  }
  $('#insightBrain').textContent = health.brain === 'ollama' ? 'Ollama (lokal)' : 'MockBrain (offline)';
  $('#insightModel').textContent = health.brain_model || '–';
  $('#insightOllama').textContent = health.ollama_available
    ? `verbunden (${(health.ollama_models || []).slice(0, 3).join(', ') || 'keine Modelle'})`
    : 'nicht erreichbar';
  $('#dbPath').textContent = health.db_path || 'data/denki.sqlite3';
}

async function restoreSession() {
  if (!state.sessionId) return;
  try {
    const data = await API.session(state.sessionId);
    if (data.messages?.length) {
      data.messages.forEach((m) => addMessage(m.role, m.content, m.meta));
      el.welcome.hidden = true;
    }
  } catch {
    state.sessionId = null;
    localStorage.removeItem('denki.session');
  }
}

(async function boot() {
  try {
    renderHealth(await API.health());
  } catch (err) {
    $('#brainLabel').textContent = 'Server nicht erreichbar';
    toast('Verbindung fehlt', err.message, 'error', 7000);
  }
  await refresh({ sessions: true });
  await restoreSession();
  el.input.focus();
})();
