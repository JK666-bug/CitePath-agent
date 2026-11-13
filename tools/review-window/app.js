/* CitePath single-reviewer annotation window.
 * Static page: load dataset + blank annotation, annotate 140 items, export JSON.
 * No network calls except optional same-origin fetch of the preparation files.
 */
'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const AUDIT_FIELDS = [
  ['clear', '题目清晰'],
  ['source_supported', '来源支持'],
  ['answer_key_correct', '答案键正确'],
  ['not_repeated', '不重复'],
];
const KIND_LABEL = { mcq: '选择题', short: '简答题', evidence: '证据问答' };
const EXPECTED = 140;

const state = {
  dataset: null,
  base: null,
  items: [],
  labels: new Map(),
  current: 0,
  filter: 'all',
  reviewerId: '',
  independent: false,
  datasetSha: '',
  dirty: false,
  saveTimer: 0,
};

const editor = $('#editor');
const itemList = $('#itemList');
const toastEl = $('#toast');

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function clone(value) {
  return typeof structuredClone === 'function'
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value));
}

function keyOf(itemId, variant) {
  return `${itemId}|${variant}`;
}

function kindOf(item) {
  return item.kind;
}

function variantsOf(item) {
  return item.kind === 'evidence' ? ['baseline', 'full'] : ['shared'];
}

function entryAt(index) {
  return state.items[index];
}

function currentEntry() {
  return entryAt(state.current);
}

function labelOf(entry) {
  return state.labels.get(entry.key);
}

function docById(documentId) {
  return (state.dataset?.documents || []).find((doc) => String(doc.id) === String(documentId));
}

function predictionOf(item, variant) {
  return (item.predictions || {})[variant] || null;
}

function predictionClaims(item, variant) {
  const prediction = predictionOf(item, variant);
  return Array.isArray(prediction?.claims) ? prediction.claims : [];
}

function sourceKey(source) {
  return `${source.document_id}|${source.page_number}`;
}

function hasPage(label, documentId, pageNumber) {
  return (label.supporting_pages || []).some(
    (source) => String(source.document_id) === String(documentId)
      && Number(source.page_number) === Number(pageNumber),
  );
}

function togglePage(label, documentId, pageNumber) {
  const pages = Array.isArray(label.supporting_pages) ? label.supporting_pages : [];
  const index = pages.findIndex(
    (source) => String(source.document_id) === String(documentId)
      && Number(source.page_number) === Number(pageNumber),
  );
  if (index >= 0) pages.splice(index, 1);
  else pages.push({ document_id: documentId, page_number: Number(pageNumber) });
  label.supporting_pages = pages;
}

function pageAllowed(documentId, pageNumber) {
  const doc = docById(documentId);
  if (!doc) return false;
  const page = Number(pageNumber);
  if (!Number.isInteger(page) || page < 1) return false;
  if (Array.isArray(doc.teaching_pages) && doc.teaching_pages.length) {
    return doc.teaching_pages.includes(page);
  }
  return !doc.page_count || page <= Number(doc.page_count);
}

function sourceHref(documentId, pageNumber) {
  const doc = docById(documentId);
  if (!doc || !doc.pdf_path) return null;
  const path = String(doc.pdf_path).split('/').map(encodeURIComponent).join('/');
  return `../../${path}#page=${Number(pageNumber)}`;
}

function blankLabel(item, variant) {
  if (item.kind === 'mcq') {
    return {
      item_id: item.id, variant, correct: null, supporting_pages: [],
      question_audit: { clear: null, source_supported: null, answer_key_correct: null, not_repeated: null },
    };
  }
  if (item.kind === 'short') {
    return {
      item_id: item.id, variant, hits: null, supporting_pages: [],
      question_audit: { clear: null, source_supported: null, answer_key_correct: null, not_repeated: null },
    };
  }
  return {
    item_id: item.id, variant, supported: null, answer_correct: null,
    supporting_pages: [], reference_point_hits: null, claims_complete: null,
    claim_support: {}, irrelevant_citations: null,
  };
}

function ensureLabel(label, item, variant) {
  if (!Array.isArray(label.supporting_pages)) label.supporting_pages = [];
  if (item.kind === 'mcq' || item.kind === 'short') {
    if (!label.question_audit || typeof label.question_audit !== 'object') label.question_audit = {};
    for (const [field] of AUDIT_FIELDS) {
      if (!(field in label.question_audit)) label.question_audit[field] = null;
    }
  }
  if (item.kind === 'evidence') {
    if (!label.claim_support || typeof label.claim_support !== 'object') label.claim_support = {};
    for (const claim of predictionClaims(item, variant)) {
      if (!(claim.id in label.claim_support)) label.claim_support[claim.id] = null;
    }
    if (!('irrelevant_citations' in label)) label.irrelevant_citations = null;
  }
  return label;
}

function baseLabelFor(item, variant) {
  const found = (state.base?.labels || []).find(
    (label) => label.item_id === item.id && label.variant === variant,
  );
  return found ? clone(found) : blankLabel(item, variant);
}

function buildItems() {
  const items = [];
  for (const item of state.dataset.items || []) {
    if (item.kind === 'workflow') continue;
    for (const variant of variantsOf(item)) {
      items.push({ item, variant, key: keyOf(item.id, variant) });
    }
  }
  return items;
}

function hasAny(label, item) {
  if (!label) return false;
  if ((label.supporting_pages || []).length) return true;
  if (item.kind === 'mcq') return label.correct !== null;
  if (item.kind === 'short') return Array.isArray(label.hits);
  return label.supported !== null || label.answer_correct !== null || label.claims_complete !== null
    || Array.isArray(label.reference_point_hits)
    || Object.values(label.claim_support || {}).some((value) => value !== null)
    || (label.irrelevant_citations || []).length > 0;
}

function isComplete(label, item) {
  if (!label) return false;
  if (item.kind === 'mcq') return typeof label.correct === 'boolean';
  if (item.kind === 'short') return Array.isArray(label.hits);
  if (typeof label.supported !== 'boolean') return false;
  if (typeof label.answer_correct !== 'boolean') return false;
  if (typeof label.claims_complete !== 'boolean') return false;
  if (!Array.isArray(label.reference_point_hits)) return false;
  const claims = predictionClaims(item, label.variant);
  if (claims.length) {
    if (!claims.every((claim) => typeof label.claim_support?.[claim.id] === 'boolean')) return false;
  }
  return true;
}

function completedCount() {
  return state.items.filter((entry) => isComplete(labelOf(entry), entry.item)).length;
}

function filteredItems() {
  return state.items.map((entry, index) => ({ entry, index })).filter(({ entry }) => {
    const label = labelOf(entry);
    if (state.filter === 'todo') return !isComplete(label, entry.item);
    if (state.filter === 'mcq' || state.filter === 'short' || state.filter === 'evidence') {
      return entry.item.kind === state.filter;
    }
    return true;
  });
}

function updateProgress() {
  const total = state.items.length || EXPECTED;
  const done = completedCount();
  $('#progressText').textContent = `${done} / ${total}`;
  $('#progressHint').textContent = state.items.length
    ? `当前第 ${state.current + 1} 项 · ${state.dirty ? '未保存' : '已自动保存'}`
    : '等待载入数据';
  $('#progressFill').style.width = `${total ? (done / total) * 100 : 0}%`;
}

function setSaveStatus(text) {
  $('#saveStatus').textContent = text;
}

function toast(message, bad = false) {
  toastEl.textContent = message;
  toastEl.style.background = bad ? '#5d2320' : '#173032';
  toastEl.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toastEl.classList.remove('show'), 2600);
}

function saveLocalNow() {
  if (!state.datasetSha) return;
  try {
    localStorage.setItem(`citepath-review-v1:${state.datasetSha}`, JSON.stringify({
      datasetSha: state.datasetSha,
      reviewerId: state.reviewerId,
      independent: state.independent,
      updatedAt: new Date().toISOString(),
      labels: state.items.map((entry) => labelOf(entry)),
    }));
    state.dirty = false;
    setSaveStatus('已自动保存');
    updateProgress();
  } catch (error) {
    setSaveStatus('自动保存失败（可导出 JSON）');
  }
}

function saveLocalSoon() {
  state.dirty = true;
  setSaveStatus('保存中…');
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(saveLocalNow, 350);
}

function restoreLocal() {
  if (!state.datasetSha) return;
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(`citepath-review-v1:${state.datasetSha}`) || 'null');
  } catch (error) {
    saved = null;
  }
  if (!saved || !Array.isArray(saved.labels)) return;
  const byKey = new Map(saved.labels.map((label) => [keyOf(label.item_id, label.variant), label]));
  for (const entry of state.items) {
    const found = byKey.get(entry.key);
    if (found) state.labels.set(entry.key, ensureLabel(found, entry.item, entry.variant));
  }
  state.reviewerId = saved.reviewerId || state.reviewerId;
  state.independent = saved.independent === true;
  $('#reviewerId').value = state.reviewerId;
  $('#independent').checked = state.independent;
  toast('已恢复上次未完成的标注');
}

function startReview() {
  if (!state.dataset || !state.base) return;
  state.items = buildItems();
  state.labels = new Map();
  state.datasetSha = state.base.dataset_sha256 || state.dataset.sha256 || '';
  for (const entry of state.items) {
    const label = ensureLabel(baseLabelFor(entry.item, entry.variant), entry.item, entry.variant);
    state.labels.set(entry.key, label);
  }
  restoreLocal();
  state.current = 0;
  state.current = Math.min(state.current, Math.max(0, state.items.length - 1));
  $('#loadBanner').hidden = true;
  updateProgress();
  renderSidebar();
  renderEditor();
  setSaveStatus(state.items.length === EXPECTED ? '准备数据已载入' : `条目数 ${state.items.length}，预期 ${EXPECTED}`);
  if (state.items.length !== EXPECTED) toast(`条目数是 ${state.items.length}，不是预期的 ${EXPECTED}`, true);
}

function updateCurrentListItem() {
  const entry = currentEntry();
  if (!entry) return;
  const label = labelOf(entry);
  const button = itemList.querySelector(`[data-index="${state.current}"]`);
  if (!button) return;
  const dot = button.querySelector('.dot');
  if (!dot) return;
  dot.className = `dot ${isComplete(label, entry.item) ? 'done' : hasAny(label, entry.item) ? 'partial' : ''}`;
}

function renderSidebar() {
  if (!state.items.length) {
    itemList.innerHTML = '<div class="empty small">载入 dataset 和空白表后显示题目。</div>';
    return;
  }
  const visible = filteredItems();
  itemList.innerHTML = visible.map(({ entry, index }) => {
    const label = labelOf(entry);
    const done = isComplete(label, entry.item);
    const partial = hasAny(label, entry.item);
    const variant = entry.variant === 'shared' ? '' : `[${entry.variant}] `;
    return `<button type="button" class="item-btn ${index === state.current ? 'active' : ''}" data-index="${index}">
      <span class="item-id">${esc(entry.item.id)}</span>
      <span class="item-title">${esc(variant)}${esc(entry.item.question || '')}</span>
      <span class="dot ${done ? 'done' : partial ? 'partial' : ''}" title="${done ? '已完成' : partial ? '部分填写' : '未填写'}"></span>
    </button>`;
  }).join('') || '<div class="empty small">没有符合条件的题目。</div>';
}

function triSelect(field, value, extra = '', labels = ['未判', '是', '否']) {
  return `<select data-field="${field}" ${extra}>
    <option value="" ${value === null || value === undefined ? 'selected' : ''}>${labels[0]}</option>
    <option value="true" ${value === true ? 'selected' : ''}>${labels[1]}</option>
    <option value="false" ${value === false ? 'selected' : ''}>${labels[2]}</option>
  </select>`;
}

function auditSelects(label) {
  return `<div class="field-grid">${AUDIT_FIELDS.map(([field, text]) => `
    <label class="field"><span>${text}</span>
      ${triSelect('audit', label.question_audit?.[field] ?? null, `data-audit="${field}"`, ['未判', '通过', '不通过'])}
    </label>`).join('')}
  </div>`;
}

function pagesBlock(label) {
  const entry = currentEntry();
  const item = entry.item;
  const pages = new Map();
  for (const source of item.sources || []) pages.set(sourceKey(source), source);
  for (const source of label.supporting_pages || []) pages.set(sourceKey(source), source);
  const rows = [...pages.values()].map((source) => {
    const href = sourceHref(source.document_id, source.page_number);
    const doc = docById(source.document_id);
    return `<div class="source-row">
      <label><input type="checkbox" data-field="supporting_page"
        data-doc="${esc(source.document_id)}" data-page="${Number(source.page_number)}"
        ${hasPage(label, source.document_id, source.page_number) ? 'checked' : ''}> 支持页</label>
      ${href ? `<a href="${esc(href)}" target="_blank" rel="noreferrer">${esc(doc?.title || doc?.id || source.document_id)} · p.${Number(source.page_number)}</a>`
        : `${esc(source.document_id)} · p.${Number(source.page_number)}`}
    </div>`;
  }).join('');
  const options = (state.dataset?.documents || []).map((doc) => {
    const pages = Array.isArray(doc.teaching_pages) && doc.teaching_pages.length
      ? doc.teaching_pages.join(',')
      : `1-${doc.page_count || '?'}`;
    return `<option value="${esc(doc.id)}">${esc(doc.title || doc.id)} (${esc(pages)})</option>`;
  }).join('');
  return `<div class="sources">${rows || '<p class="muted small">没有预设来源页，可在下面添加。</p>'}</div>
    <div class="source-add">
      <select id="docSelect">${options}</select>
      <input id="pageInput" type="number" min="1" step="1" placeholder="页码">
      <button class="secondary" type="button" data-action="add-page">添加来源页</button>
    </div>`;
}

function questionBlock() {
  const entry = currentEntry();
  const item = entry.item;
  const prediction = predictionOf(item, entry.variant);
  if (item.kind === 'mcq') {
    const options = (item.options || []).map((option, index) => {
      const letter = String.fromCharCode(65 + index);
      return `<li><span class="letter">${letter}</span>${esc(option)}</li>`;
    }).join('');
    return `<p class="question">${esc(item.question)}</p>
      <ul class="options">${options}</ul>
      <p class="muted small">系统作答：<strong>${esc(item.response || '（空）')}</strong></p>
      <details><summary>查看候选答案键（审计用，先独立判断再展开）</summary>
        <div class="response">答案键：${esc(item.answer_key || '（无）')}${item.reference_answer ? `\n参考：${esc(item.reference_answer)}` : ''}</div>
      </details>`;
  }
  if (item.kind === 'short') {
    return `<p class="question">${esc(item.question)}</p>
      <div class="response">${esc(item.response || '（空）')}</div>
      <details><summary>查看参考作答</summary>
        <div class="response">${esc(item.reference_answer || '（无）')}</div>
      </details>`;
  }
  const answer = prediction?.answer ?? prediction?.response ?? '';
  const refused = prediction?.refused === true;
  return `<p class="question">${esc(item.question)}</p>
    ${prediction ? `<div class="response">${refused ? '系统拒绝回答。' : esc(answer || '（空）')}</div>`
    : '<div class="notice">该变体还没有真实系统输出（predictions 为 null）。请使用 observed-dataset.json 进行证据题标注；准备数据只能检查输入。</div>'}`;
}

function referencePointsBlock(label) {
  const points = currentEntry().item.reference_points || [];
  if (!points.length) return '<p class="muted small">没有参考点。</p>';
  return `<ul class="rubric">${points.map((point, index) => `
    <li><label><input type="checkbox" data-field="reference_point_hits" data-index="${index}"
      ${Array.isArray(label.reference_point_hits) && label.reference_point_hits.includes(index) ? 'checked' : ''}>
      <span><small>#${index}</small> ${esc(point)}</span></label></li>`).join('')}
  </ul>
  <div class="unknown-row"><button class="secondary" type="button" data-action="clear-ref">标记为未判定</button></div>`;
}

function claimsBlock(label) {
  const entry = currentEntry();
  const claims = predictionClaims(entry.item, entry.variant);
  if (!claims.length) {
    return '<p class="muted small">该变体没有 claims；无法填写 claim 支持。请使用 observed-dataset.json。</p>';
  }
  const irrelevant = Array.isArray(label.irrelevant_citations) ? label.irrelevant_citations : [];
  return claims.map((claim) => {
    const text = claim.text || claim.claim || claim.id;
    const citations = Array.isArray(claim.citations) ? claim.citations : [];
    return `<div class="claim">
      <div class="claim-text">${esc(text)}</div>
      <label class="field"><span>这条 claim 是否被引用页支持</span>
        ${triSelect('claim_support', label.claim_support?.[claim.id] ?? null, `data-claim="${esc(claim.id)}"`)}
      </label>
      ${citations.length ? `<div class="citations">${citations.map((citation) => {
        const doc = docById(citation.document_id);
        const href = sourceHref(citation.document_id, citation.page_number);
        const checked = irrelevant.some((source) => String(source.claim_id) === String(claim.id)
          && String(source.document_id) === String(citation.document_id)
          && Number(source.page_number) === Number(citation.page_number));
        return `<label class="citation"><input type="checkbox" data-field="irrelevant"
          data-claim="${esc(claim.id)}" data-doc="${esc(citation.document_id)}" data-page="${Number(citation.page_number)}"
          ${checked ? 'checked' : ''}> 无关引用
          ${href ? `<a href="${esc(href)}" target="_blank" rel="noreferrer">${esc(doc?.title || citation.document_id)} · p.${Number(citation.page_number)}</a>`
            : `${esc(citation.document_id)} · p.${Number(citation.page_number)}`}
        </label>`;
      }).join('')}</div>` : '<p class="muted small">该 claim 没有引用。</p>'}
    </div>`;
  }).join('');
}

function editorForm() {
  const entry = currentEntry();
  const item = entry.item;
  const label = labelOf(entry);
  if (item.kind === 'mcq') {
    return `<div class="field-grid">
      <label class="field"><span>这条选择题的候选答案是否正确</span>
        ${triSelect('correct', label.correct ?? null, '', ['未判', '正确', '错误'])}
      </label>
    </div>${auditSelects(label)}`;
  }
  if (item.kind === 'short') {
    const rubric = item.rubric || [];
    return `<ul class="rubric">${rubric.map((point, index) => `
      <li><label><input type="checkbox" data-field="hits" data-index="${index}"
        ${Array.isArray(label.hits) && label.hits.includes(index) ? 'checked' : ''}>
        <span><small>#${index}</small> ${esc(point)}</span></label></li>`).join('')}
    </ul>
    <div class="unknown-row"><button class="secondary" type="button" data-action="clear-hits">标记为未判定</button>
      <span class="muted small">5 点中 4 点通过；3 点不通过。</span></div>
    ${auditSelects(label)}`;
  }
  return `<div class="field-grid">
    <label class="field"><span>问题是否被讲义支持</span>${triSelect('supported', label.supported ?? null, '', ['未判', '支持', '不支持'])}</label>
    <label class="field"><span>答案是否正确</span>${triSelect('answer_correct', label.answer_correct ?? null)}</label>
    <label class="field"><span>claim 是否完整</span>${triSelect('claims_complete', label.claims_complete ?? null)}</label>
  </div>
  <h3 class="small">参考点覆盖</h3>${referencePointsBlock(label)}
  <h3 class="small">Claim 支持与引用</h3>${claimsBlock(label)}`;
}

function renderEditor() {
  if (!state.dataset || !state.base || !state.items.length) {
    editor.innerHTML = '<div class="empty">先载入 dataset.json 和 annotator-a.json。</div>';
    return;
  }
  const entry = currentEntry();
  const item = entry.item;
  const label = labelOf(entry);
  const kind = KIND_LABEL[item.kind];
  const variant = entry.variant === 'shared' ? '共同输入' : entry.variant;
  editor.innerHTML = `<div class="editor-head">
      <div>
        <div class="eyebrow">${kind} · ${esc(variant)} · 第 ${state.current + 1} / ${state.items.length} 项</div>
        <h1>${esc(item.id)}</h1>
        <div class="badges">
          <span class="badge kind-${item.kind}">${kind}</span>
          <span class="badge">Lecture ${esc(item.lecture)}</span>
          <span class="badge variant">${esc(variant)}</span>
          <span class="badge">${isComplete(label, item) ? '已完成' : '未完成'}</span>
        </div>
      </div>
      <div class="nav">
        <button type="button" data-action="prev" ${state.current === 0 ? 'disabled' : ''}>上一题</button>
        <button type="button" data-action="next" ${state.current === state.items.length - 1 ? 'disabled' : ''}>下一题</button>
      </div>
    </div>

    <section class="panel">
      <h2>题目与系统输出</h2>
      ${questionBlock()}
    </section>

    <section class="panel">
      <h2>来源页</h2>
      ${pagesBlock(label)}
    </section>

    <section class="panel">
      <h2>人工标注</h2>
      ${editorForm()}
    </section>

    <div class="footer-bar">
      <span class="muted small">自动保存在本机浏览器；导出后才会生成最终文件。</span>
      <div class="toolbar">
        <button type="button" class="secondary" data-action="prev">上一题</button>
        <button type="button" class="primary" data-action="mark-next">完成并下一题</button>
        <button type="button" class="secondary" data-action="next">下一题</button>
      </div>
    </div>`;
}

function afterEdit() {
  saveLocalSoon();
  updateProgress();
  updateCurrentListItem();
}

function onEditorChange(event) {
  const target = event.target;
  const field = target.dataset.field;
  if (!field) return;
  const entry = currentEntry();
  const label = labelOf(entry);
  if (field === 'supporting_page') {
    togglePage(label, target.dataset.doc, Number(target.dataset.page));
  } else if (field === 'hits' || field === 'reference_point_hits') {
    const index = Number(target.dataset.index);
    let values = Array.isArray(label[field]) ? [...label[field]] : [];
    if (target.checked) {
      if (!values.includes(index)) values.push(index);
    } else {
      values = values.filter((value) => value !== index);
    }
    values.sort((a, b) => a - b);
    label[field] = values;
  } else if (field === 'irrelevant') {
    const claimId = target.dataset.claim;
    const source = {
      claim_id: claimId,
      document_id: target.dataset.doc,
      page_number: Number(target.dataset.page),
    };
    let values = Array.isArray(label.irrelevant_citations) ? [...label.irrelevant_citations] : [];
    const index = values.findIndex((item) => String(item.claim_id) === String(source.claim_id)
      && String(item.document_id) === String(source.document_id)
      && Number(item.page_number) === Number(source.page_number));
    if (target.checked && index < 0) values.push(source);
    if (!target.checked && index >= 0) values.splice(index, 1);
    label.irrelevant_citations = values;
  } else if (field === 'audit') {
    const auditField = target.dataset.audit;
    if (!label.question_audit) label.question_audit = {};
    label.question_audit[auditField] = target.value === '' ? null : target.value === 'true';
  } else if (field === 'claim_support') {
    if (!label.claim_support) label.claim_support = {};
    label.claim_support[target.dataset.claim] = target.value === '' ? null : target.value === 'true';
  } else if (field === 'correct' || field === 'supported' || field === 'answer_correct' || field === 'claims_complete') {
    label[field] = target.value === '' ? null : target.value === 'true';
  }
  afterEdit();
}

function onEditorClick(event) {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const action = button.dataset.action;
  if (action === 'prev' || action === 'next') {
    const offset = action === 'next' ? 1 : -1;
    const next = state.current + offset;
    if (next < 0 || next >= state.items.length) return;
    state.current = next;
    renderSidebar();
    renderEditor();
    $('.editor-scroll').scrollTop = 0;
    updateProgress();
  } else if (action === 'mark-next') {
    const entry = currentEntry();
    if (!isComplete(labelOf(entry), entry.item)) {
      toast('本题还有未填项；可以继续填写，或先跳下一题。', true);
      return;
    }
    if (state.current < state.items.length - 1) {
      state.current += 1;
      renderSidebar();
      renderEditor();
      $('.editor-scroll').scrollTop = 0;
      updateProgress();
    }
  } else if (action === 'clear-hits' || action === 'clear-ref') {
    const entry = currentEntry();
    const label = labelOf(entry);
    label[action === 'clear-hits' ? 'hits' : 'reference_point_hits'] = null;
    renderEditor();
    afterEdit();
  } else if (action === 'add-page') {
    const docId = $('#docSelect', editor)?.value;
    const page = Number($('#pageInput', editor)?.value);
    if (!pageAllowed(docId, page)) {
      toast('页码不在该 PDF 的教学页范围内。', true);
      return;
    }
    const label = labelOf(currentEntry());
    if (!hasPage(label, docId, page)) togglePage(label, docId, page);
    renderEditor();
    afterEdit();
  }
}

function downloadAnnotation() {
  if (!state.base || !state.items.length) {
    toast('还没有载入数据。', true);
    return;
  }
  state.reviewerId = $('#reviewerId').value.trim();
  state.independent = $('#independent').checked;
  if (!state.reviewerId) {
    toast('请填写复核人 ID。', true);
    $('#reviewerId').focus();
    return;
  }
  if (!state.independent) {
    toast('请确认“我独立完成”后才能导出。', true);
    return;
  }
  const incomplete = state.items.filter((entry) => !isComplete(labelOf(entry), entry.item)).length;
  if (incomplete && !confirm(`还有 ${incomplete} 项未完成。仍要导出部分标注吗？`)) return;
  const out = {
    ...state.base,
    annotator_id: state.reviewerId,
    independent: true,
    label_origin: 'human',
    labels: state.items.map((entry) => {
      const label = clone(labelOf(entry));
      label.item_id = entry.item.id;
      label.variant = entry.variant;
      if (Array.isArray(label.hits)) label.hits = [...new Set(label.hits)].sort((a, b) => a - b);
      if (Array.isArray(label.reference_point_hits)) {
        label.reference_point_hits = [...new Set(label.reference_point_hits)].sort((a, b) => a - b);
      }
      if (entry.item.kind === 'evidence') {
        const claims = predictionClaims(entry.item, entry.variant);
        const support = {};
        for (const claim of claims) support[claim.id] = label.claim_support?.[claim.id] ?? null;
        label.claim_support = support;
        if (!Array.isArray(label.irrelevant_citations)) label.irrelevant_citations = null;
      }
      return label;
    }),
  };
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'annotator-a.json';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  saveLocalNow();
  toast(`已导出 annotator-a.json（${out.labels.length} 项，未完成 ${incomplete} 项）`);
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadDemo() {
  setSaveStatus('载入准备包…');
  const params = new URLSearchParams(location.search);
  const candidates = [];
  if (params.get('dataset')) {
    candidates.push({
      dataset: new URL(params.get('dataset'), location.href),
      annotation: params.get('annotation')
        ? new URL(params.get('annotation'), location.href)
        : null,
    });
  } else {
    candidates.push({
      dataset: new URL('../../evaluation_assets/cohorts/execution-20261112-r2/dataset.json', location.href),
      annotation: new URL('../../evaluation_assets/cohorts/execution-20261112-r2/annotations/annotator-a.json', location.href),
    });
    candidates.push({
      dataset: new URL('../../../work/CitePath-agent/evaluation_assets/cohorts/execution-20261112-r2/dataset.json', location.href),
      annotation: new URL('../../../work/CitePath-agent/evaluation_assets/cohorts/execution-20261112-r2/annotations/annotator-a.json', location.href),
    });
  }
  let lastError = null;
  for (const candidate of candidates) {
    if (!candidate.annotation) continue;
    try {
      const [dataset, annotation] = await Promise.all([
        fetchJson(candidate.dataset),
        fetchJson(candidate.annotation),
      ]);
      loadDataset(dataset, false);
      loadBase(annotation, false);
      startReview();
      setSaveStatus('准备数据已载入');
      toast('已载入 execution-20261112-r2 准备数据');
      return;
    } catch (error) {
      lastError = error;
    }
  }
  setSaveStatus('自动载入失败');
  $('#loadBanner').hidden = false;
  toast(`自动载入失败：${lastError ? lastError.message : '缺少 annotation'}。请用文件选择器载入。`, true);
}

function loadDataset(data, start = true) {
  if (!data || !Array.isArray(data.items) || !Array.isArray(data.documents)) {
    toast('dataset.json 格式不对：需要 items 和 documents。', true);
    return;
  }
  state.dataset = data;
  if (start && state.base) startReview();
}

function loadBase(data, start = true) {
  if (!data || !Array.isArray(data.labels)) {
    toast('空白表格式不对：需要 labels。', true);
    return;
  }
  state.base = data;
  if (start && state.dataset) startReview();
}

function readFile(input, callback) {
  const file = input.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      callback(JSON.parse(String(reader.result)));
    } catch (error) {
      toast(`无法解析 ${file.name}：${error.message}`, true);
    }
  };
  reader.onerror = () => toast(`无法读取 ${file.name}`, true);
  reader.readAsText(file, 'utf-8');
}

function initEvents() {
  $('#datasetFile').addEventListener('change', (event) => readFile(event.target, loadDataset));
  $('#annotationFile').addEventListener('change', (event) => readFile(event.target, loadBase));
  $('#loadDemo').addEventListener('click', loadDemo);
  $('#exportBtn').addEventListener('click', downloadAnnotation);
  $('#reviewerId').addEventListener('input', (event) => {
    state.reviewerId = event.target.value;
    saveLocalSoon();
  });
  $('#independent').addEventListener('change', (event) => {
    state.independent = event.target.checked;
    saveLocalSoon();
  });
  itemList.addEventListener('click', (event) => {
    const button = event.target.closest('.item-btn');
    if (!button) return;
    state.current = Number(button.dataset.index);
    renderSidebar();
    renderEditor();
    $('.editor-scroll').scrollTop = 0;
    updateProgress();
  });
  $('#chips').addEventListener('click', (event) => {
    const chip = event.target.closest('.chip');
    if (!chip) return;
    state.filter = chip.dataset.filter;
    $$('.chip').forEach((item) => item.classList.toggle('active', item === chip));
    renderSidebar();
  });
  editor.addEventListener('change', onEditorChange);
  editor.addEventListener('click', onEditorClick);
  window.addEventListener('beforeunload', (event) => {
    if (!state.dirty) return undefined;
    event.preventDefault();
    event.returnValue = '';
    return '';
  });
}

function init() {
  initEvents();
  loadDemo();
}

init();
