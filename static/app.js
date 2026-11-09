'use strict';
const $ = (id) => document.getElementById(id);
let lastVersion = -1;
let lastExercise = '';
let fetching = false;
let toastTimer = null;
const STATUSES = {
  idle: ['AWAITING', 'Ready to start', 'is-idle'],
  incomplete: ['TYPING', 'Incomplete expression', 'is-idle'],
  running: ['RUNNING', 'Evaluating saved code', 'is-idle'],
  wrong: ['NOT YET', 'Target not matched', 'is-wrong'],
  correct: ['CORRECT', 'Transformation complete', 'is-correct'],
  error: ['ERROR', 'Python runtime error', 'is-error'],
  syntax: ['SYNTAX', 'Invalid Python syntax', 'is-error'],
  no_result: ['NO RESULT', 'Missing result assignment', 'is-wrong'],
};

function el(tag, content, cls) {
  const node = document.createElement(tag);
  if (content !== undefined && content !== null) node.textContent = String(content);
  if (cls) node.className = cls;
  return node;
}
function showPreview(containerId, data, targetForDiff = null) {
  const parent = $(containerId);
  parent.replaceChildren();
  if (!data) {
    parent.append(el('div', 'Start typing:  result = ...', 'empty'));
    return;
  }
  if (data.kind === 'scalar') {
    const wrap = el('div', null, 'dg-scalar');
    wrap.append(el('span', data.value));
    wrap.append(el('small', data.type));
    parent.append(wrap);
    return;
  }
  const table = el('table', null, 'dg-table');
  const thead = el('thead');
  const hr = el('tr');
  hr.append(el('th', data.index_name, 'dg-index-head'));
  data.columns.forEach((name, j) => {
    const different = targetForDiff && targetForDiff.kind === data.kind &&
      (j >= targetForDiff.columns.length || targetForDiff.columns[j] !== name);
    hr.append(el('th', name, different ? 'dg-diff' : ''));
  });
  thead.append(hr);
  table.append(thead);
  const tbody = el('tbody');
  data.rows.forEach((row, i) => {
    const tr = el('tr');
    const indexDifferent = targetForDiff && targetForDiff.kind === data.kind &&
      (i >= targetForDiff.index.length || targetForDiff.index[i] !== data.index[i]);
    tr.append(el('th', data.index[i], 'dg-index' + (indexDifferent ? ' dg-diff' : '')));
    row.forEach((val, j) => {
      const different = targetForDiff && targetForDiff.kind === data.kind &&
        (i >= targetForDiff.rows.length || j >= targetForDiff.rows[i].length ||
          targetForDiff.rows[i][j] !== val);
      tr.append(el('td', val, different ? 'dg-diff' : ''));
    });
    tbody.append(tr);
  });
  table.append(tbody);
  parent.append(table);
  if (data.truncated) parent.append(el('div', 'Preview truncated; grading uses the full result.', 'dg-truncation'));
}

function fillCategories(categories) {
  const select = $('category');
  const previous = select.value;
  const values = Array.from(select.options).map((o) => o.value);
  if (JSON.stringify(values) === JSON.stringify(categories)) return;
  select.replaceChildren(...categories.map((v) => {
    const option = el('option', v);
    option.value = v;
    return option;
  }));
  if (categories.includes(previous)) select.value = previous;
}
function readableTime(total) {
  const s = Math.floor(total);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}
function renderExercise(state) {
  const exercise = state.exercise;
  const key = `${exercise.id}/${exercise.seed}`;
  if (key === lastExercise) return;

  lastExercise = key;
  lastVersion = -1;
  $('assistBox').hidden = true;
  $('assistBox').textContent = '';
  $('categoryTag').textContent = exercise.category;
  $('exerciseId').textContent = `${exercise.id} / seed ${exercise.seed}`;
  $('exerciseTitle').textContent = `${exercise.title} (${exercise.variable === 'arr' ? 'NumPy' : 'pandas'})`;
  $('instructions').textContent = exercise.instructions;
  $('levelTag').textContent = `LEVEL ${exercise.difficulty}`;
  $('solutionPath').textContent = state.solution_path;

  if (state.filters) {
    $('category').value = state.filters.category;
    $('difficulty').value = state.filters.difficulty;
  }
}

function renderStatus(state) {
  const mode = STATUSES[state.status] || STATUSES.idle;
  const isError = ['error', 'syntax'].includes(state.status);
  const isPending = ['wrong', 'incomplete'].includes(state.status);

  $('liveState').textContent = mode[0];
  $('liveState').className = 'live-pill ' + (
    state.status === 'correct' ? 'correct' : isError ? 'error' : isPending ? 'pending' : ''
  );
  $('statusBox').className = `status-box ${mode[2]}`;
  $('statusIcon').textContent = state.status === 'correct' ? '✓'
    : state.status === 'running' ? '◌'
    : isError ? '×' : state.status === 'wrong' ? '!' : '●';
  $('statusTitle').textContent = mode[1];
  $('statusMessage').textContent = state.message;
  $('timer').textContent = `${readableTime(state.elapsed)} elapsed`;
  $('softGoal').textContent = state.elapsed >= state.time_goal
    ? 'Past 2:00 soft goal (keep going)' : '2:00 soft goal';
}

function renderStats(state) {
  const stats = state.stats;
  const currentSolve = state.solved ? 1 : 0;
  const values = [
    [`${stats.solved + currentSolve}/${stats.attempted + currentSolve}`, 'solved'],
    [stats.streak + currentSolve, 'streak'],
    [state.template_count, 'templates'],
  ];

  const metrics = values.map(([value, label]) => {
    const span = el('span');
    span.append(el('strong', value), document.createTextNode(` ${label}`));
    return span;
  });
  $('topStats').replaceChildren(...metrics);
  $('footProgress').textContent =
    `${state.previews} evaluations · ${state.hints_used} hints · ${stats.unique} distinct templates solved`;
}

function renderPreviews(state) {
  if (lastVersion === state.render_version) return;
  lastVersion = state.render_version;

  showPreview('inputTable', state.input);
  showPreview('targetTable', state.target);
  showPreview('liveTable', state.live, state.status === 'wrong' ? state.target : null);
  $('inputMeta').textContent = state.input?.meta || '—';
  $('targetMeta').textContent = state.target?.meta || '—';
  $('liveMeta').textContent = state.live?.meta || 'No result yet';
}

function render(state) {
  if (!state.exercise) return;
  renderExercise(state);
  fillCategories(state.categories);
  renderStatus(state);
  renderStats(state);
  renderPreviews(state);
}

async function api(url, body = null) {
  const init = body === null ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  };
  const response = await fetch(url, init);
  if (!response.ok) {
    let error = 'Request failed';
    try { error = (await response.json()).error || error; } catch (_e) { /* ignore */ }
    throw new Error(error);
  }
  return response.json();
}
async function poll() {
  if (fetching) return;
  fetching = true;
  try { render(await api('/api/state')); }
  catch (e) { $('statusMessage').textContent = 'Connection error: ' + e.message; }
  finally { fetching = false; }
}
function toast(message) {
  const box = $('toast');
  box.textContent = message;
  box.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.remove('visible'), 2500);
}
async function action(path, payload, callback) {
  try {
    const result = await api(path, payload);
    if (callback) callback(result);
    await poll();
  } catch (e) { toast(e.message); }
}
$('nextBtn').addEventListener('click', () => action('/api/new', {
  category: $('category').value, difficulty: $('difficulty').value,
}, (state) => { render(state); toast('New exercise loaded in solution.py'); }));
function showAssistance(mode, heading, code, steps = []) {
  const box = $('assistBox');
  const close = el('button', '×', 'assist-close');
  close.type = 'button';
  close.title = 'Close (Esc)';
  close.setAttribute('aria-label', 'Close explanation');
  close.addEventListener('click', () => { box.hidden = true; });

  box.dataset.mode = mode;
  box.replaceChildren(close, el('div', heading, 'answer-label'), el('pre', code, 'answer-code'));

  if (steps.length) {
    box.append(el('div', 'EXPLANATION', 'answer-label'));
    for (const step of steps) {
      const row = el('div', null, 'answer-step');
      row.append(el('code', step.code), el('p', step.meaning));
      box.append(row);
    }
  }
  box.hidden = false;
}

function toggleAssistance(mode, endpoint, heading, display) {
    const box = $('assistBox');

    if (!box.hidden && box.dataset.mode === mode) {
        box.hidden = true;
        return;
    }

    action(endpoint, {}, data => {
        showAssistance(
            mode,
            heading,
            display(data),
            mode === 'answer' ? (data.steps || []) : []
        );
    });
}

$('hintBtn').addEventListener('click', () => {
    toggleAssistance(
        'hint',
        '/api/hint',
        'HINT',
        data => data.hint
    );
});

$('revealBtn').addEventListener('click', () => {
    toggleAssistance(
        'answer',
        '/api/reveal',
        'REFERENCE SOLUTION',
        data => data.reference
    );
});
$('resetBtn').addEventListener('click', () => action('/api/reset', {}, () => toast('solution.py reset')));
$('reloadBtn').addEventListener('click', () => action('/api/import', {}, (r) => toast(`Imported / updated ${r.imported} templates`)));
$('copyPath').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('solutionPath').textContent); toast('Path copied'); }
  catch (_e) { toast('Select the displayed path and copy it manually'); }
});
window.addEventListener('DOMContentLoaded', poll);
setInterval(poll, 450);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    $('assistBox').hidden = true;
    return;
  }

  if (
    e.metaKey ||
    e.ctrlKey ||
    e.altKey ||
    e.target.closest('input, textarea, select, button')
  ) return;

  if (e.key.toLowerCase() === 'n') {
    $('nextBtn').click();
  }
});