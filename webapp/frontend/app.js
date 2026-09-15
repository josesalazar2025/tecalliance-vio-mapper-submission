/* VIO Mapper — demonstration UI.
 *
 * The screen renders a run; it never computes one. Every figure shown here
 * arrives from /api/run as the mapper produced it, so what a presenter reads
 * off the screen and what a reviewer opens in the downloaded workbook are the
 * same numbers by construction.
 */
'use strict';

/* The payload shape this script expects. If the running server answers with a
 * different number it is serving a different set of field names, and figures
 * this script asks for by name would silently render as em dashes. Say so
 * instead: in practice it means a server was left running across a code change. */
const EXPECTED_PAYLOAD_VERSION = 8;

const state = {
  defaults: null,
  run: null,
  file: null,
  tab: 'summary',
  statusFilter: 'all',
  search: '',
  openRow: null,
};

/* ---------- DOM helpers ------------------------------------------------ */

const $ = (id) => document.getElementById(id);

/** Build an element. Text is always assigned as text, never as markup: source
 *  strings are registry data and must not be able to inject anything. */
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = String(value);
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); return node; };

/* ---------- Formatting -------------------------------------------------- */

const DASH = '—';

/** A cell value for display. Blank, null and NaN all read as an em dash so an
 *  absent value is never mistaken for a zero. */
function show(value) {
  if (value === null || value === undefined || value === '') return DASH;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  return String(value);
}

function num(value, digits = 0) {
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return DASH;
  return Number(value).toLocaleString('en-NZ', { maximumFractionDigits: digits });
}

function kType(value) {
  if (value === null || value === undefined || value === '') return DASH;
  return String(Math.trunc(Number(value)));
}

/** The pill class for a match status. Grouped by what the status means for the
 *  reviewer, not by string: accepted, proposed, needs a choice, contradicted. */
function statusClass(status) {
  const text = String(status || '');
  if (text === 'Matched') return 'pill-matched';
  if (text.startsWith('Proposed')) return 'pill-proposed';
  if (text === 'Ambiguous') return 'pill-ambiguous';
  if (text === 'Conflicting source data') return 'pill-conflict';
  return 'pill-none';
}

function barClass(status) {
  return statusClass(status).replace('pill-', '');
}

const statusPill = (status) => el('span', { class: `pill ${statusClass(status)}`, text: show(status) });

/* ---------- Reusable blocks -------------------------------------------- */

function card(title, body, hint) {
  const head = title ? el('div', { class: 'card-head' }, [
    el('h2', { text: title }),
    hint ? el('span', { class: 'hint', text: hint }) : null,
  ]) : null;
  return el('div', { class: 'card' }, [head, el('div', { class: 'card-body' }, body)]);
}

/** A card whose body is a full-bleed table. */
function tableCard(title, columns, rows, options = {}) {
  const table = dataTable(columns, rows, options);
  const head = el('div', { class: 'card-head' }, [
    el('h2', { text: title }),
    options.hint ? el('span', { class: 'hint', text: options.hint }) : null,
  ]);
  const body = rows.length
    ? el('div', { class: 'table-wrap' }, [table])
    : el('div', { class: 'empty', text: options.empty || 'Nothing to show.' });
  return el('div', { class: 'card' }, [head, body]);
}

/** A table from column specs: {key, label, num, render, width}. */
function dataTable(columns, rows, options = {}) {
  const head = el('tr', {}, columns.map((column) =>
    el('th', { class: column.num ? 'num' : null, text: column.label })));
  const body = el('tbody', {}, rows.map((row, index) => {
    const tr = el('tr', {
      class: options.onRow ? 'clickable' : null,
      onclick: options.onRow ? () => options.onRow(row) : null,
    }, columns.map((column) => {
      const rendered = column.render ? column.render(row, index) : show(row[column.key]);
      return el('td', { class: column.num ? 'num' : column.cellClass || null },
        rendered instanceof Node ? [rendered] : [String(rendered)]);
    }));
    return tr;
  }));
  return el('table', { class: 'data' }, [el('thead', {}, [head]), body]);
}

function stat(label, value, sub, variant) {
  return el('div', { class: `stat${variant ? ' ' + variant : ''}` }, [
    el('div', { class: 'label', text: label }),
    el('div', { class: 'value', text: value }),
    sub ? el('div', { class: 'sub', text: sub }) : null,
  ]);
}

function pairs(entries) {
  const list = el('dl', { class: 'pairs' });
  for (const [key, value] of entries) {
    if (value === null || value === undefined || value === '') continue;
    list.append(el('dt', { text: key }), el('dd', {}, [
      value instanceof Node ? value : String(value),
    ]));
  }
  return list;
}

function fold(title, tag, body, open = false) {
  return el('details', { class: 'fold', open: open || null }, [
    el('summary', {}, [title, tag ? el('span', { class: 'tag', text: tag }) : null]),
    el('div', { class: 'fold-body' }, body),
  ]);
}

function bar(fraction, variant) {
  const width = Math.max(0, Math.min(1, fraction || 0)) * 100;
  return el('div', { class: `bar ${variant || ''}` }, [
    el('span', { style: `width:${width.toFixed(1)}%` }),
  ]);
}

function kvCloud(mapping, limit) {
  const entries = Object.entries(mapping || {});
  const shown = limit ? entries.slice(0, limit) : entries;
  const cloud = el('div', { class: 'kv-cloud' }, shown.map(([key, value]) =>
    el('span', { class: 'kv' }, [
      el('b', { text: key }), el('i', { text: '→' }),
      String(Array.isArray(value) ? value.join(' / ') : value),
    ])));
  if (limit && entries.length > limit) {
    cloud.append(el('span', { class: 'kv muted', text: `+${entries.length - limit} more` }));
  }
  return cloud;
}

/* ---------- API --------------------------------------------------------- */

async function api(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON error page */ }
  if (!response.ok) {
    throw new Error((data && (data.detail || data.message)) || text || `Request failed (${response.status})`);
  }
  return data;
}

/* ---------- Upload screen ----------------------------------------------- */

function chooseFile(file) {
  state.file = file || null;
  const zone = $('dropzone');
  $('upload-error').classList.add('hidden');
  if (!file) {
    zone.classList.remove('chosen');
    $('drop-primary').textContent = 'Drop a registry file, or click to choose';
    $('drop-secondary').textContent = '.xlsx, .xlsm, .csv, .tsv or .txt';
    $('run-button').disabled = true;
    $('run-hint').textContent = 'Choose a file to begin.';
    return;
  }
  zone.classList.add('chosen');
  $('drop-primary').textContent = file.name;
  $('drop-secondary').textContent = `${(file.size / 1024).toFixed(0)} KB — click to choose a different file`;
  $('run-button').disabled = false;
  $('run-hint').textContent = `Mapped against ${state.defaults ? state.defaults.reference_name : 'the bundled reference'}.`;
}

function formData() {
  const form = new FormData();
  form.append('file', state.file);
  return form;
}

function showOverlay(text) {
  clear($('overlay-root')).append(el('div', { class: 'overlay' }, [
    el('div', { class: 'spinner' }),
    el('div', { class: 'what', text: 'Mapping' }),
    el('div', { class: 'step', text }),
  ]));
}

const hideOverlay = () => clear($('overlay-root'));

async function runMapping() {
  if (!state.file) return;
  showOverlay(`Comparing every row of ${state.file.name} against the reference catalogue…`);
  try {
    const run = await api('/api/run', { method: 'POST', body: formData() });
    state.run = run;
    state.tab = 'summary';
    state.statusFilter = 'all';
    state.search = '';
    renderRun();
  } catch (error) {
    const box = $('upload-error');
    clear(box).append(el('b', { text: 'The run did not start' }), el('span', { text: error.message }));
    box.classList.remove('hidden');
  } finally {
    hideOverlay();
  }
}

/* ---------- Run shell --------------------------------------------------- */

function renderRun() {
  const { summary } = state.run;
  $('view-upload').classList.add('hidden');
  $('view-run').classList.remove('hidden');
  $('run-file').textContent = summary.source_name;
  clear($('run-facts')).append(...[
    ['rows', `${num(summary.worksheet_rows)} worksheet rows`],
    ['ids', `${num(summary.distinct_ids)} distinct vehicles`],
    ['time', `${summary.elapsed_seconds}s`],
    ['run', new Date(summary.run_utc).toLocaleString()],
    ['version', `algorithm ${summary.algorithm_version}`],
  ].map(([, text]) => el('div', { text })));
  // The badge counts vehicles, matching the Summary tab; the brief folds them
  // into distinct cases, and each card says how many vehicles it covers.
  $('count-review').textContent = state.run.review.reduce((total, entry) => total + entry.vehicle_count, 0);
  for (const button of document.querySelectorAll('.tab')) {
    button.classList.toggle('active', button.dataset.tab === state.tab);
  }
  for (const name of ['summary', 'review', 'audit', 'rules']) {
    $(`panel-${name}`).classList.toggle('hidden', name !== state.tab);
  }
  const panel = $(`panel-${state.tab}`);
  clear(panel);
  ({ summary: renderSummary, review: renderReview, audit: renderAudit, rules: renderRules })[state.tab](panel);
  window.scrollTo({ top: 0 });
}

/* ---------- Summary tab -------------------------------------------------- */

function renderSummary(panel) {
  const s = state.run.summary;
  panel.append(el('div', { class: 'stat-row' }, [
    stat('Distinct vehicles', num(s.distinct_ids), `${num(s.worksheet_rows)} worksheet rows`),
    stat('Accepted into VIO', num(s.accepted), `${s.accepted_pct}% acceptance coverage`, 'accent good'),
    stat('Left for review', num(s.unresolved), `${num(s.review_rows)} worksheet rows queued`, 'warn'),
    stat('Distinct kTypes', num(s.distinct_ktypes), 'in the accepted VIO'),
    stat('Candidate comparisons', num(s.candidate_comparisons),
      `${num(s.worksheet_rows)} rows weighed against their candidate kTypes`),
  ]));

  panel.append(el('div', { class: 'caveat' }, [
    el('span', { text: '⚠' }), el('div', { text: s.coverage_caveat }),
  ]));

  const maxStatus = Math.max(...s.status_counts.map((row) => row.distinct_ids), 1);
  const statusTable = tableCard('Outcome of every row', [
    {
      key: 'status', label: 'Match status',
      render: (row) => el('div', { class: 'status-cell' }, [
        statusPill(row.status),
        el('div', { class: 'muted', text: row.glossary }),
      ]),
    },
    { key: 'worksheet_rows', label: 'Rows', num: true, render: (row) => num(row.worksheet_rows) },
    { key: 'distinct_ids', label: 'Vehicles', num: true, render: (row) => num(row.distinct_ids) },
    {
      key: 'share', label: 'Share',
      render: (row) => bar(row.distinct_ids / maxStatus, barClass(row.status)),
    },
  ], s.status_counts, { hint: 'distinct vehicles, not worksheet rows' });

  const vioTable = tableCard('Accepted VIO', [
    { key: 'kType', label: 'kType', render: (row) => el('span', { class: 'mono', text: row.kType }) },
    { key: 'distinct_vehicle_count', label: 'Vehicles', num: true },
    {
      key: 'share', label: '', width: 90,
      render: (row) => bar(row.distinct_vehicle_count / Math.max(...s.vio.map((v) => v.distinct_vehicle_count), 1), 'matched'),
    },
  ], s.vio, {
    hint: 'accepted distinct IDs only',
    empty: 'No row was accepted under these settings.',
  });

  panel.append(el('div', { class: 'grid-2' }, [statusTable, vioTable]));

  const checks = [
    ['Exact duplicate copies', num(s.duplicates), 'retained in the workbook, excluded from the VIO count'],
    ['Duplicate ID conflicts', num(s.duplicate_conflicts), 'same ID, different values'],
    ['Acceptances relying on power tolerance', num(s.power_tolerance_dependent),
      s.power_tolerance_dependent ? 'each flagged per row with the kW and % gap' : 'power agreement is exact'],
    ['Supplied labels', `${num(s.label_agreement.agree)} agree · ${num(s.label_agreement.disagree)} disagree · ${num(s.label_agreement.unassigned)} unassigned`,
      `${num(s.label_agreement.labeled)} labelled vehicles; the labels cover one kType and do not measure general accuracy`],
  ];
  panel.append(card('Integrity checks', [
    el('div', { class: 'stat-row', style: 'margin-bottom:0' }, checks.map(([label, value, sub]) =>
      el('div', { class: 'stat' }, [
        el('div', { class: 'label', text: label }),
        el('div', { class: 'value', style: 'font-size:20px', text: value }),
        el('div', { class: 'sub', text: sub }),
      ]))),
  ]));

  panel.append(renderResultsTable());
}

/* ---------- Results table ------------------------------------------------ */

function filteredResults() {
  const needle = state.search.trim().toLowerCase();
  return state.run.results.filter((row) => {
    if (state.statusFilter !== 'all') {
      const matched = row.Match_Status === 'Matched';
      if (state.statusFilter === 'matched' && !matched) return false;
      if (state.statusFilter === 'review' && matched) return false;
      if (state.statusFilter !== 'matched' && state.statusFilter !== 'review'
          && row.Match_Status !== state.statusFilter) return false;
    }
    if (!needle) return true;
    return ['ID', 'MAKE', 'MODEL', 'SUBMODEL', 'mapped kType', 'Match_Status', 'Review_Fields']
      .some((key) => String(row[key] ?? '').toLowerCase().includes(needle));
  });
}

function renderResultsTable() {
  const rows = filteredResults();
  const statuses = [...new Set(state.run.results.map((row) => row.Match_Status))];
  const chips = [
    ['all', `All ${state.run.results.length}`],
    ['matched', 'Accepted'],
    ['review', 'Needs review'],
    ...statuses.filter((status) => status !== 'Matched')
      .map((status) => [status, status.startsWith('Proposed') ? 'Proposed' : status]),
  ];
  const filters = el('div', { class: 'filters' }, [
    ...chips.map(([key, label]) => el('button', {
      class: `chip${state.statusFilter === key ? ' on' : ''}`,
      text: label,
      onclick: () => { state.statusFilter = key; refreshResults(); },
    })),
    el('input', {
      class: 'search', type: 'search', placeholder: 'Filter by ID, make, model, kType…',
      value: state.search,
      oninput: (event) => { state.search = event.target.value; refreshResults(true); },
    }),
  ]);

  const table = tableCard(`Rows (${rows.length})`, [
    { key: 'ID', label: 'ID', cellClass: 'mono nowrap' },
    { key: 'MAKE', label: 'Make' },
    { key: 'MODEL', label: 'Model' },
    { key: 'SUBMODEL', label: 'Submodel', render: (row) => el('span', { class: 'muted', text: show(row.SUBMODEL) }) },
    { key: 'VEHICLE_YEAR', label: 'Year', num: true, render: (row) => show(row.VEHICLE_YEAR) },
    { key: 'Match_Status', label: 'Status', render: (row) => statusPill(row.Match_Status) },
    {
      key: 'mapped kType', label: 'kType', num: true,
      render: (row) => {
        if (row['mapped kType'] !== null && row['mapped kType'] !== undefined) {
          return el('b', { class: 'mono', text: kType(row['mapped kType']) });
        }
        const likely = row.proposed_kType ?? row.triage_lead_kType;
        return likely === null || likely === undefined
          ? el('span', { class: 'muted', text: DASH })
          : el('span', { class: 'pill pill-outline', text: `likely ${kType(likely)}` });
      },
    },
    {
      key: 'Review_Fields', label: 'Stopped on',
      render: (row) => row.Match_Status === 'Matched'
        ? el('span', { class: 'muted', text: DASH })
        : el('span', { text: show(row.Review_Fields) }),
    },
  ], rows, {
    hint: 'click a row for its full evidence',
    empty: 'No row matches this filter.',
    onRow: (row) => openDrawer(row.source_key),
  });

  return el('div', { class: 'section', id: 'results-section' }, [
    el('h2', { text: 'Every row, with the evidence behind it' }),
    el('p', {
      class: 'blurb',
      text: state.run.rules.selection_description,
    }),
    filters, table,
  ]);
}

/** Re-render only the results section, so typing in the filter does not rebuild
 *  the whole tab and lose the caret. */
function refreshResults(keepFocus) {
  const section = $('results-section');
  if (!section) return;
  const caret = keepFocus ? section.querySelector('.search').selectionStart : null;
  section.replaceWith(renderResultsTable());
  if (keepFocus) {
    const input = $('results-section').querySelector('.search');
    input.focus();
    if (caret !== null) input.setSelectionRange(caret, caret);
  }
}

/* ---------- Review brief tab --------------------------------------------- */

/* The four kinds of likely candidate, strongest claim first. The order is the
 * one the API sorts by, and it is the order a reviewer should work in: a
 * proposal already has an identifier anchor, a scoped preference has only a
 * model-specific reading, a lead has only proximity. The gloss labels the card;
 * the blurb is the full statement, kept verbatim behind the legend fold so
 * nothing that qualifies a claim is lost to a shorter layout. */
const BRIEF_KINDS = {
  proposal: {
    label: 'Proposal',
    gloss: 'identifiers name a kType, one specification disagrees',
    blurb: 'Two or more distinct manufacturer identifier fields agree on one kType that is contradicted '
         + 'on exactly one specification. These are not assigned and not counted in VIO: the '
         + 'conflicting field has to be reconciled with the data owner before any of them is accepted.',
  },
  scoped: {
    label: 'Scoped preference',
    gloss: 'a model-specific reading favours one candidate',
    blurb: 'No identifier names these. One candidate is preferred by a reading that holds for this '
         + 'model rather than as a general rule, so the row is named and sent to review instead of '
         + 'being decided on that reading. Weaker than a proposal, and not evidence.',
  },
  lead: {
    label: 'Triage lead',
    gloss: 'one candidate is a single field from compatible',
    blurb: 'Every candidate here is still contradicted. A lead only says which candidate a reviewer '
         + 'should open first, because exactly one specification stands between it and compatibility. '
         + 'A lead is not evidence and accepts nothing.',
  },
  shortlist: {
    label: 'Shortlist',
    gloss: 'several candidates equally close, none named',
    blurb: 'More than one candidate sits a single field from compatibility, so none is named. '
         + 'The shortlist is given instead.',
  },
  none: {
    label: 'No likely candidate',
    gloss: 'nothing came within one specification',
    blurb: 'Nothing came within one specification. These rows need the source or the reference '
         + 'catalogue extending before they can be decided.',
  },
};

const KIND_ORDER = ['proposal', 'scoped', 'lead', 'shortlist', 'none'];

function renderReview(panel) {
  const entries = state.run.review;
  if (!entries.length) {
    panel.append(card(null, [el('div', { class: 'empty', text: 'Every row was accepted. The review queue is empty.' })]));
    return;
  }

  const present = KIND_ORDER.filter((kind) => entries.some((entry) => entry.kind === kind));
  const vehicles = (kind) => entries.filter((entry) => entry.kind === kind)
    .reduce((total, entry) => total + entry.vehicle_count, 0);

  panel.append(el('div', { class: 'section' }, [
    el('h2', { text: 'What stopped each unresolved vehicle, and what is likeliest' }),
    el('p', {
      class: 'blurb',
      text: 'Ordered by how far a reviewer has to go. A proposal already has an identifier anchor; a '
          + 'triage lead has only proximity. Neither has been accepted, and neither is counted in VIO. '
          + 'Vehicles whose whole brief is identical share one card, which carries the count and the IDs.',
    }),
    el('div', { class: 'brief-legend' }, present.map((kind) => el('div', {
      class: `legend-item kind-${kind}`,
    }, [
      el('i', { class: 'swatch' }),
      el('div', {}, [
        el('div', {}, [
          el('b', { text: BRIEF_KINDS[kind].label }),
          el('span', { class: 'n', text: ` · ${vehicles(kind)} vehicles` }),
        ]),
        el('div', { class: 'gloss', text: BRIEF_KINDS[kind].gloss }),
      ]),
    ]))),
    fold('What these categories mean', 'the full statement of each', [
      el('dl', { class: 'pairs kinds' }, present.flatMap((kind) => [
        el('dt', {}, [el('span', { class: `kind-tag kind-${kind}`, text: BRIEF_KINDS[kind].label })]),
        el('dd', { text: BRIEF_KINDS[kind].blurb }),
      ])),
    ]),
  ]));

  // One continuous grid: the API already sorts by kind, so cards stay grouped
  // visually by their coloured band without a heading breaking every row.
  panel.append(el('div', { class: 'brief-grid' }, entries.map(briefCard)));
}

/** How a candidate names itself. Not every kType carries a Type_designation, so
 *  the model design stands in rather than leaving the column blank. */
function referenceName(candidate) {
  return show(candidate.reference_Type_designation || candidate.reference_Model_design
    || candidate.reference_Type_design);
}

/** A pipeline reason as a sentence. These are phrases rather than sentences, and
 *  the prose around them supplies the rest, so only the full stop is missing. */
function sentence(value) {
  const text = show(value);
  return /[.!?]$/.test(text) || text === DASH ? text : `${text}.`;
}

/** A pipeline phrase used as the first word of a sentence. */
function capitalized(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/** The IDs a folded card covers, truncated where a fleet repeats many times. */
function idLabel(entry) {
  const ids = entry.ids || [entry.ID];
  const shown = ids.map(show).join(', ');
  const hidden = entry.vehicle_count - ids.length;
  return hidden > 0 ? `IDs ${shown} +${hidden} more` : `ID${ids.length > 1 ? 's' : ''} ${shown}`;
}

function briefCard(entry) {
  const verdict = el('div', { class: 'verdict' });
  if (entry.kind === 'proposal') {
    verdict.append(
      el('div', { class: 'headline' }, [
        'Proposed kType', el('span', { class: 'ktype', text: kType(entry.likely_kType) }),
        el('span', { class: 'pill pill-proposed', text: 'awaiting confirmation' }),
      ]),
      el('div', { class: 'why' }, [
        'Anchored on ', el('b', { text: show(entry.proposal_basis) }),
        entry.proposal_conflicting_fields
          ? el('span', {}, ['. Contradicted on ', el('b', { text: entry.proposal_conflicting_fields }),
            ' — reconcile that field with the data owner before accepting.'])
          : '. Awaiting confirmation before it can be accepted.',
      ]));
  } else if (entry.kind === 'scoped') {
    verdict.append(
      el('div', { class: 'headline' }, [
        'Preferred kType', el('span', { class: 'ktype', text: kType(entry.likely_kType) }),
        el('span', { class: 'pill pill-ambiguous', text: 'scoped reading, not decided' }),
      ]),
      el('div', { class: 'why' }, [
        sentence(entry.proposal_basis),
        ' No identifier names it, so the row is sent to review rather than decided on that reading.',
      ]));
  } else if (entry.kind === 'lead') {
    verdict.append(
      el('div', { class: 'headline' }, [
        'Most probable kType', el('span', { class: 'ktype', text: kType(entry.likely_kType) }),
        el('span', { class: 'pill pill-ambiguous', text: 'lead only, not evidence' }),
      ]),
      el('div', { class: 'why' }, [
        capitalized(sentence(entry.lead_basis)),
        entry.lead_alternatives
          ? el('span', {}, [' Equally close: ', el('b', { text: entry.lead_alternatives }), '.'])
          : null,
      ]));
  } else if (entry.kind === 'shortlist') {
    verdict.append(
      el('div', { class: 'headline' }, ['Shortlist, none named']),
      el('div', { class: 'why' }, [
        el('b', { text: show(entry.lead_alternatives) }),
        ' are equally close, each a single specification from compatible, so none is named.',
      ]));
  } else {
    verdict.append(
      el('div', { class: 'headline' }, ['No candidate within one specification']),
      el('div', { class: 'why' }, [
        sentence(entry.match_reason || entry.review_category),
        entry.remaining_kTypes
          ? el('span', {}, [' Still in play: ', el('b', { text: entry.remaining_kTypes }), '.'])
          : null,
      ]));
  }

  const candidates = entry.candidates.length ? el('div', { class: 'evidence' }, [
    el('div', { class: 'table-wrap' }, [dataTable([
      { key: 'KType', label: 'kType', render: (row) => el('b', { class: 'mono', text: kType(row.KType) }) },
      {
        key: 'reference_Type_designation', label: 'Reference',
        render: (row) => el('span', { class: 'muted', text: referenceName(row) }),
      },
      {
        key: 'disagreements', label: 'Contradicts',
        render: (row) => row.compatible
          ? el('span', { class: 'pill pill-matched', text: 'compatible' })
          : el('span', { class: 'fchip disagree', text: show(row.disagreements) }),
      },
    ], entry.candidates)]),
  ]) : null;

  return el('article', { class: `brief kind-${entry.kind}` }, [
    el('header', {}, [
      el('div', { class: 'who' }, [
        el('div', { class: 'kind', text: BRIEF_KINDS[entry.kind].label }),
        el('div', { class: 'name' }, [
          `${show(entry.MAKE)} ${show(entry.MODEL)}`,
          entry.vehicle_count > 1
            ? el('span', { class: 'pill pill-outline', style: 'margin-left:8px', text: `× ${entry.vehicle_count} vehicles` })
            : null,
        ]),
        el('div', { class: 'sub', text: `${show(entry.SUBMODEL)} · ${show(entry.VEHICLE_YEAR)}` }),
        el('div', { class: 'sub mono', text: idLabel(entry) }),
      ]),
      el('div', { class: 'right' }, [statusPill(entry.status)]),
    ]),
    verdict,
    candidates,
    el('footer', {}, [
      el('span', { text: `${show(entry.review_category)}${entry.review_fields ? ' · ' + entry.review_fields : ''}` }),
      el('button', {
        class: 'link-btn',
        text: entry.vehicle_count > 1 ? `Full evidence for ID ${show(entry.ID)}` : 'Full evidence',
        onclick: () => openDrawer(entry.source_key),
      }),
    ]),
  ]);
}

/* ---------- Audit tab ----------------------------------------------------- */

function renderAudit(panel) {
  const a = state.run.audit;
  const t = a.candidate_totals;

  panel.append(el('div', { class: 'section' }, [
    el('h2', { text: 'Traceability of every decision' }),
    el('p', {
      class: 'blurb',
      text: 'A comparison is one source row weighed against one candidate kType, so the same kType '
          + 'is counted again for every row that reaches it. Each figure below is read back off the '
          + 'same candidate-evidence trail the workbook carries; retention settings change what is '
          + 'written out, never what was decided.',
    }),
  ]));

  panel.append(el('div', { class: 'stat-row' }, [
    stat('Candidate comparisons', num(t.comparisons),
      `${num(t.rows_with_evidence)} rows × ${num(t.mean_candidates_per_row)} candidates on average`),
    stat('Passed every check', num(t.compatible), 'comparisons compatible on every specification'),
    stat('Met criterion sufficiency', num(t.criterion_sufficient),
      'comparisons satisfying the default acceptance requirement'),
    stat('Ended in a selection', num(t.selected), 'one comparison per accepted row'),
    stat('Vehicles using an assumption', num(a.assumption_rows), 'each assumption named on its row'),
  ]));

  panel.append(tableCard('Where coverage is lost', [
    { key: 'review_category', label: 'Review sub-status' },
    { key: 'review_fields', label: 'Field' },
    {
      key: 'scope', label: 'Covers',
      render: (row) => el('span', { class: 'muted', text: show(row.scope) }),
    },
    { key: 'status', label: 'Status', render: (row) => statusPill(row.status) },
    { key: 'distinct_ids', label: 'Vehicles', num: true },
  ], a.lost_coverage, {
    hint: 'a field marked “every candidate” must be reconciled before the row can match at all',
    empty: 'No coverage was lost: every vehicle was accepted.',
  }));

  panel.append(el('div', { class: 'grid-2' }, [
    tableCard('Which specification contradicted a candidate', [
      { key: 'field', label: 'Evidence key' },
      { key: 'candidates', label: 'Comparisons', num: true },
      {
        key: 'share', label: '', width: 90,
        render: (row) => bar(row.candidates / Math.max(...a.disagreements.map((d) => d.candidates), 1), 'conflict'),
      },
    ], a.disagreements, {
      hint: 'counted per comparison, not per vehicle',
      empty: 'No candidate was contradicted.',
    }),
    tableCard('Criterion sufficiency', [
      { key: 'basis', label: 'Outcome' },
      { key: 'count', label: 'Comparisons', num: true },
    ], a.criterion_shortfalls, {
      hint: 'blank means the criterion requirement was satisfied',
      empty: 'No candidate evidence was retained.',
    }),
  ]));

  panel.append(el('div', { class: 'grid-2' }, [
    tableCard('Assumptions used', [
      { key: 'item', label: 'Assumption' },
      { key: 'distinct_ids', label: 'Vehicles', num: true },
    ], a.assumptions, {
      hint: 'every assumption is named on the row that used it',
      empty: 'No row relied on a configured assumption.',
    }),
    tableCard('VIN helper outcome', [
      { key: 'value', label: 'Status' },
      { key: 'count', label: 'Vehicles', num: true },
    ], a.vin_helper_status, { empty: 'The VIN helper was disabled for this run.' }),
  ]));

  const extras = [];
  if (a.late_registration.length) {
    extras.push(fold('Accepted with a vehicle year after production end',
      `${a.late_registration.length} vehicles`, [
        el('p', {
          class: 'blurb',
          text: 'NZTA defines VEHICLE_YEAR as year of manufacture or model year, falling back to first '
              + 'registration when manufacture is unknown, so this is legitimate for unsold stock '
              + 'registered late. It is listed because these rows pass every check by construction, '
              + 'which makes an incorrect one hard to see.',
        }),
        el('div', { class: 'table-wrap' }, [dataTable([
          { key: 'ID', label: 'ID', cellClass: 'mono' },
          { key: 'MAKE', label: 'Make' },
          { key: 'MODEL', label: 'Model' },
          { key: 'mapped kType', label: 'kType', num: true, render: (row) => kType(row['mapped kType']) },
          { key: 'VEHICLE_YEAR', label: 'Year', num: true },
          { key: 'selected_construction_to', label: 'Production ends', num: true },
          { key: 'selected_registration_after_end_years', label: 'Years later', num: true },
          { key: 'IMPORT_STATUS', label: 'Import status' },
        ], a.late_registration)]),
      ]));
  }
  if (a.duplicates.length) {
    extras.push(fold('Duplicate handling', `${a.duplicates.length} rows`, [
      el('p', { class: 'blurb', text: 'Exact copies are retained in the workbook and excluded from the VIO count, so no vehicle is counted twice.' }),
      el('div', { class: 'table-wrap' }, [dataTable([
        { key: 'ID', label: 'ID', cellClass: 'mono' },
        { key: 'source_key', label: 'Source row', cellClass: 'mono' },
        { key: 'duplicate_of', label: 'Duplicate of', cellClass: 'mono' },
        { key: 'duplicate_id_conflict', label: 'Values differ' },
        { key: 'canonical_record', label: 'Canonical' },
        { key: 'Match_Status', label: 'Status', render: (row) => statusPill(row.Match_Status) },
      ], a.duplicates)]),
    ]));
  }
  if (a.label_agreement_rows.length) {
    extras.push(fold('Supplied labels', `${a.label_agreement_rows.length} labelled vehicles`, [
      el('p', { class: 'blurb', text: 'The supplied labels cover one kType. They are reported, never used to decide, and do not measure general accuracy.' }),
      el('div', { class: 'table-wrap' }, [dataTable([
        { key: 'ID', label: 'ID', cellClass: 'mono' },
        { key: 'MAKE', label: 'Make' },
        { key: 'MODEL', label: 'Model' },
        { key: 'provided_kType', label: 'Supplied', num: true, render: (row) => kType(row.provided_kType) },
        { key: 'mapped kType', label: 'Mapped', num: true, render: (row) => kType(row['mapped kType']) },
        {
          key: 'provided_label_agreement', label: 'Agreement',
          render: (row) => el('span', {
            class: `pill ${row.provided_label_agreement === 'agree' ? 'pill-matched'
              : row.provided_label_agreement === 'disagree' ? 'pill-conflict' : 'pill-neutral'}`,
            text: show(row.provided_label_agreement),
          }),
        },
      ], a.label_agreement_rows)]),
    ]));
  }
  if (a.submodel_conflicts.length) {
    extras.push(fold('SUBMODEL text contradicting the structured fields',
      `${a.submodel_conflicts.length} fields`, [
        el('div', { class: 'table-wrap' }, [dataTable([
          { key: 'item', label: 'Field' }, { key: 'distinct_ids', label: 'Vehicles', num: true },
        ], a.submodel_conflicts)]),
      ]));
  }
  extras.push(fold('Run provenance', 'inputs, versions and file hashes', [
    el('p', { class: 'blurb', text: 'Everything needed to reproduce this run: the policy, the library versions, and a SHA-256 of every input file and every source file that defines a decision.' }),
    el('div', { class: 'table-wrap' }, [dataTable([
      { key: 'property', label: 'Property' },
      { key: 'value', label: 'Value', cellClass: 'mono' },
    ], a.metadata)]),
  ]));
  extras.push(fold('Full performance report', 'the markdown the CLI writes', [
    el('pre', { class: 'report', text: a.report_markdown }),
  ]));
  panel.append(el('div', { class: 'section' }, extras));
}

/* ---------- Rule sets tab ------------------------------------------------- */

const POLICY_LABELS = {
  power_tolerance_pct: ['Power tolerance', 'Percentage of the reference figure. Zero means power must agree exactly.'],
  power_triage_kw: ['Power triage band', 'kW, review only. Names a likely kType; never makes a candidate compatible.'],
  use_identifiers: ['Structural identifiers', 'Structural code support and conflict checks; effect depends on the active policy.'],
  use_vin_helper: ['Sourced VIN helper', 'Reviewed OEM VIN layouts, each with a cited source.'],
  evidence: ['Evidence retention', 'Audit trail only; never changes a decision.'],
  selection: ['Decision policy', 'Dominance compares the sets of version and variant criteria each candidate agrees with.'],
  reuse_identical_rows: ['Reuse identical rows', 'Pure caching: an identical row replays the same outcome.'],
};

function renderRules(panel) {
  const r = state.run ? state.run.rules : state.defaults.rules;

  panel.append(el('div', { class: 'section' }, [
    el('h2', { text: 'The rules that governed this run' }),
    el('p', {
      class: 'blurb',
      text: 'The dominance policy compares explicit evidence and abstains when the available '
          + 'criteria do not support one candidate. Its sufficiency and precedence rules are '
          + 'documented engineering judgments, not calibrated probabilities. The lookup tables '
          + 'below are loaded from data/rules as JSON, so a domain reviewer can amend them '
          + 'without touching code and the change shows up as a data diff.',
    }),
  ]));

  const policyRows = Object.entries(r.policy)
    .filter(([key]) => POLICY_LABELS[key])
    .map(([key, value]) => ({
      setting: POLICY_LABELS[key][0], value, meaning: POLICY_LABELS[key][1],
      changed: state.defaults && String(state.defaults.policy[key]) !== String(value),
    }));
  panel.append(tableCard('Policy applied', [
    { key: 'setting', label: 'Setting' },
    {
      key: 'value', label: 'Value',
      render: (row) => el('span', { class: `pill ${row.changed ? 'pill-ambiguous' : 'pill-neutral'}` },
        [show(row.value) + (row.changed ? ' (changed)' : '')]),
    },
    { key: 'meaning', label: 'What it does', render: (row) => el('span', { class: 'muted', text: row.meaning }) },
  ], policyRows, { hint: 'anything changed from the documented default is marked' }));

  panel.append(tableCard('Every match status', [
    { key: 'status', label: 'Status', render: (row) => statusPill(row.status) },
    { key: 'meaning', label: 'What it means' },
  ], r.statuses));

  const folds = [];
  folds.push(fold('Fields compared, and which of them can veto a candidate',
    `${r.compared_fields.length} compared · ${r.veto_fields.length} vetoing`, [
      el('p', { class: 'blurb', text: 'A contradiction vetoes a candidate. Several evidence keys restate the same underlying observation, and the collapsing table below folds them back onto one specification so a single disagreement is never counted twice.' }),
      el('div', { class: 'kv-cloud' }, r.veto_fields.map((field) =>
        el('span', { class: 'kv' }, [el('b', { text: field })]))),
      el('h3', { style: 'margin-top:16px', text: 'Collapsed onto' }),
      kvCloud(Object.fromEntries(r.core_conflicts.map((row) => [row.evidence_key, row.counts_as]))),
      el('h3', { style: 'margin-top:16px', text: 'Unresolved review conflict classes' }),
      el('p', { class: 'blurb', text: 'These semantic classes order candidates for review only. They never alter compatibility or a mapping decision.' }),
      kvCloud(Object.fromEntries(r.review_conflict_classes.map((row) => [row.evidence_key, row.review_class]))),
      el('p', { class: 'blurb', style: 'margin-top:12px' }, [
        'Never proposable: ',
        el('b', { text: r.unproposable_conflicts.join(', ') || DASH }),
        ' — a contradiction here suggests the wrong production interval altogether.',
      ]),
    ]));

  folds.push(fold('Identifier fields', `${r.identifiers.length} fields`, [
    el('p', { class: 'blurb', text: 'VIN11 and MVMA_MODEL_CODE are manufacturer-assigned at VIN allocation and are expected in the reference; CHASSIS7 is a chassis-number prefix, so its absence says nothing. INDUSTRY_MODEL_CODE is a non-validated NZTA field: it is compared and exported for audit but takes no part in conflicts, anchoring, identity points or proposals.' }),
    el('div', { class: 'kv-cloud' }, r.identifiers.map((field) =>
      el('span', { class: 'kv' }, [el('b', { text: field })]))),
  ]));

  const vocabularyBlocks = [
    ['registry_fuel', 'Register MOTIVE_POWER labels → internal fuel category'],
    ['catalogue_fuel', 'Catalogue fuel labels → internal fuel category'],
    ['reference_drive_system', 'RDM drive labels → internal drive category'],
    ['submodel_drive', 'Drive tokens written in the SUBMODEL string'],
    ['registry_submodel_fuel', 'SUBMODEL fuel family and hybrid flag, register labels'],
    ['catalogue_submodel_fuel', 'SUBMODEL fuel family and hybrid flag, catalogue labels'],
    ['registry_bodies', 'Registration body → internal body category'],
    ['catalogue_structures', 'Catalogue structure → internal body category'],
    ['cab_tokens', 'Cab configuration tokens'],
    ['cab_bodies', 'Cab configuration → permitted bodies'],
  ];
  folds.push(fold('Value vocabularies', 'each catalogue mapped into the neutral categories',
    vocabularyBlocks.map(([key, caption]) => el('div', { style: 'margin-bottom:14px' }, [
      el('h3', { text: caption }),
      kvCloud(r.vocabularies[key]),
    ]))));

  folds.push(fold('SUBMODEL parsing profiles', `${r.submodel_profiles.length} make/model pairs`, [
    el('p', { class: 'blurb', text: 'A make/model pair without a profile is not parsed for trim. These are dataset-scoped readings, never general rules.' }),
    el('div', { class: 'table-wrap' }, [dataTable([
      { key: 'make', label: 'Make' },
      { key: 'model', label: 'Model' },
      { key: 'id', label: 'Profile', cellClass: 'mono' },
      {
        key: 'marketing_trims', label: 'Marketing trims',
        render: (row) => el('span', { class: 'muted', text: row.marketing_trims.join(', ') || DASH }),
      },
    ], r.submodel_profiles)]),
    el('h3', { style: 'margin-top:14px', text: 'SUBMODEL facts, collapsed onto a specification' }),
    kvCloud(r.submodel_core_fields.values || r.submodel_core_fields),
  ]));

  const vinSources = Object.entries(r.vin_rules.sources || {});
  folds.push(fold('VIN layouts and their sources',
    `${r.vin_rules.profiles.length} profiles · ${vinSources.length} cited sources`, [
      el('p', { class: 'blurb', text: 'Every VIN reading is traced to a document that was read and checked. Generation, drive and engine comparisons remain visible beside their source; inferred fields and VIN model years never affect matching.' }),
      el('div', { class: 'table-wrap' }, [dataTable([
        { key: 'id', label: 'Profile', cellClass: 'mono' },
        { key: 'pattern', label: 'Matches VIN', cellClass: 'mono' },
        {
          key: 'segments', label: 'Reads',
          render: (row) => el('span', { class: 'muted', text: row.segments.map((s) => s.key).join(', ') || DASH }),
        },
        { key: 'source', label: 'Source', cellClass: 'mono' },
      ], r.vin_rules.profiles)]),
      el('h3', { style: 'margin-top:16px', text: 'Sources' }),
      el('div', { class: 'table-wrap' }, [dataTable([
        { key: 'key', label: 'Key', cellClass: 'mono' },
        { key: 'title', label: 'Document' },
        { key: 'scope', label: 'Scope', render: (row) => el('span', { class: 'muted', text: show(row.scope) }) },
        {
          key: 'url', label: 'Link',
          render: (row) => row.url
            ? el('a', { href: row.url, target: '_blank', rel: 'noreferrer noopener', text: 'open' })
            : DASH,
        },
        { key: 'accessed', label: 'Accessed', cellClass: 'nowrap' },
      ], vinSources.map(([key, value]) => ({ key, ...value })))]),
    ]));

  panel.append(el('div', { class: 'section' }, folds));
}

/* ---------- Row drawer ---------------------------------------------------- */

const DRAWER_GROUPS = [
  ['Registry record', ['ID', 'MAKE', 'MODEL', 'SUBMODEL', 'VEHICLE_YEAR', 'BODY_TYPE', 'CC_RATING',
    'POWER_RATING', 'MOTIVE_POWER', 'TRANSMISSION_TYPE', 'ENGINE_NUMBER', 'IMPORT_STATUS',
    'PREVIOUS_COUNTRY', 'NZ_ASSEMBLED', 'source_key']],
  ['Identifiers', ['VIN11', 'MVMA_MODEL_CODE', 'CHASSIS7', 'INDUSTRY_MODEL_CODE',
    'parsed_identifiers', 'identifier_kTypes']],
  ['Decision', ['Match_Status', 'mapped kType', 'Match_Reason', 'Review_Category', 'Review_Fields',
    'Review_Fields_scope', 'count_in_vio', 'remaining_kTypes', 'base_candidate_count',
    'compatible_candidate_count', 'evidence_notes']],
  ['Likely candidate', ['proposed_kType', 'proposal_basis', 'proposal_conflicting_fields',
    'triage_lead_kType', 'triage_lead_blocking_field', 'triage_lead_basis', 'triage_lead_alternatives']],
  ['VIN helper', ['vin_origin', 'vin_helper_profile', 'vin_helper_status', 'vin_helper_facts',
    'vin_helper_sources', 'vin_helper_source_conflicts', 'vin_helper_note', 'vin_context_note']],
  ['SUBMODEL reading', ['submodel_parsed', 'submodel_source_checks', 'submodel_source_conflicts',
    'submodel_source_conflict_fields']],
  ['Assumptions and selection', ['assumptions_used', 'assumption_count', 'selected_year_relationship',
    'selected_power_tolerance_used', 'selected_power_difference_kw',
    'selected_registration_after_end_years', 'selected_construction_to']],
  ['Duplicates and labels', ['duplicate_of', 'duplicate_id_conflict', 'canonical_record',
    'provided_kType', 'provided_label_agreement']],
];

const COMPARED = ['capacity', 'fuel', 'power', 'drive', 'body', 'variant', 'engine'];

function closeDrawer() {
  state.openRow = null;
  clear($('drawer-root'));
  document.body.classList.remove('locked');
  document.removeEventListener('keydown', drawerKeys);
}

function drawerKeys(event) {
  if (event.key === 'Escape') closeDrawer();
}

async function openDrawer(sourceKey) {
  state.openRow = sourceKey;
  const root = clear($('drawer-root'));
  const body = el('div', { class: 'drawer-body' }, [el('div', { class: 'empty', text: 'Loading evidence…' })]);
  const title = el('h2', { text: 'Row evidence' });
  const subtitle = el('div', { class: 'sub', text: sourceKey });
  root.append(
    el('div', { class: 'scrim', onclick: closeDrawer }),
    el('aside', { class: 'drawer', role: 'dialog', 'aria-label': 'Row evidence' }, [
      el('header', {}, [
        el('div', {}, [title, subtitle]),
        el('button', { class: 'close', text: '×', 'aria-label': 'Close', onclick: closeDrawer }),
      ]),
      body,
    ]));
  document.body.classList.add('locked');
  document.addEventListener('keydown', drawerKeys);

  try {
    const detail = await api(`/api/run/${state.run.run_id}/row?source_key=${encodeURIComponent(sourceKey)}`);
    if (state.openRow !== sourceKey) return;  // the drawer was closed or moved on
    const row = detail.row;
    title.textContent = `${show(row.MAKE)} ${show(row.MODEL)}`;
    subtitle.textContent = `${show(row.SUBMODEL)} · ${show(row.VEHICLE_YEAR)} · ID ${show(row.ID)}`;
    clear(body).append(...drawerContent(row, detail.candidates));
  } catch (error) {
    clear(body).append(el('div', { class: 'error' }, [
      el('b', { text: 'Could not load this row' }), el('span', { text: error.message }),
    ]));
  }
}

function drawerContent(row, candidates) {
  const blocks = [];
  const headline = row['mapped kType'] !== null && row['mapped kType'] !== undefined
    ? el('div', {}, [
      el('div', { class: 'headline', style: 'font-size:13px;font-weight:600' }, [
        'Accepted as kType ',
        el('span', { style: 'font-family:var(--font-heading);font-size:20px;color:var(--success-700)', text: kType(row['mapped kType']) }),
      ]),
      el('div', { class: 'muted', style: 'margin-top:4px', text: show(row.Match_Reason) }),
    ])
    : el('div', {}, [
      el('div', { style: 'font-size:13px;font-weight:600', text: 'Not accepted' }),
      el('div', { class: 'muted', style: 'margin-top:4px', text: show(row.Match_Reason) }),
    ]);
  blocks.push(card(null, [
    el('div', { style: 'display:flex;gap:12px;align-items:flex-start;margin-bottom:10px' }, [
      headline, el('div', { style: 'margin-left:auto' }, [statusPill(row.Match_Status)]),
    ]),
    pairs([
      ['Decision policy', 'dominance'],
      ['Acceptance route', show(row.acceptance_route)],
      ['Criterion set', show(row.selected_criterion_vector)],
      ['Candidates', `${num(row.base_candidate_count)} compared, ${num(row.compatible_candidate_count)} compatible`],
    ]),
  ]));

  blocks.push(el('h2', { style: 'margin:18px 0 4px', text: `Candidates compared (${candidates.length})` }));
  blocks.push(el('p', { class: 'blurb', style: 'color:var(--circuit-400);font-size:12.5px;margin-bottom:10px', text: 'Most likely and shortlisted candidates appear first, followed by compatible candidates. Within a tier, sole near-power conflicts lead; candidates agreeing with documented identity/generation precede otherwise equal candidates, while identity contradictions follow configuration or specification conflicts. Text similarity breaks later ties. This is review priority, not evidence or probability.' }));
  if (!candidates.length) {
    blocks.push(el('div', { class: 'card' }, [el('div', { class: 'empty', text: 'No candidate evidence was retained for this row under the run\'s retention setting.' })]));
  }
  for (const candidate of candidates) {
    blocks.push(candidateCard(candidate));
  }

  for (const [title, keys] of DRAWER_GROUPS) {
    const entries = keys
      .filter((key) => key in row && row[key] !== null && row[key] !== '' && row[key] !== undefined)
      .map((key) => [key, show(row[key])]);
    if (entries.length) blocks.push(fold(title, `${entries.length} fields`, [pairs(entries)]));
  }
  return blocks;
}

function candidateCard(candidate) {
  const verdict = candidate.selected ? ['pill-matched', 'selected']
    : candidate.compatible ? ['pill-proposed', 'compatible']
      : ['pill-conflict', 'contradicted'];
  const chips = COMPARED.map((field) => {
    const value = candidate[field];
    const kind = value === 'agree' ? 'agree' : value === 'disagree' ? 'disagree' : 'unknown';
    return el('span', { class: `fchip ${kind}`, text: `${field}: ${show(value)}` });
  });
  return el('div', { class: `candidate${candidate.selected ? ' is-selected' : ''}` }, [
    el('header', {}, [
      el('span', { class: 'muted mono', text: `#${candidate.review_rank}` }),
      el('span', { class: 'kt mono', text: kType(candidate.KType) }),
      el('span', { class: 'desig', text: referenceName(candidate) }),
      candidate.review_priority === 'most likely' || candidate.review_priority === 'shortlist'
        ? el('span', { class: 'pill pill-ambiguous', text: candidate.review_priority,
          title: candidate.review_priority_basis })
        : null,
      el('span', { class: `pill ${verdict[0]}`, text: verdict[1] }),
    ]),
    el('div', { class: 'body' }, [
      el('div', { class: 'field-chips' }, chips),
      candidate.disagreements
        ? el('div', { style: 'margin-top:9px' }, [
          el('span', { class: 'muted', text: 'Contradicted on: ' }),
          el('b', { text: candidate.disagreements }),
        ])
        : null,
      el('div', { style: 'margin-top:9px' }, [pairs([
        ['Reference', [candidate.reference_Model_design, candidate.reference_Type_design].filter(Boolean).join(' · ')],
        ['Capacity / fuel', `${show(candidate.reference_Capacity_cubic)} cc · ${show(candidate.reference_Fuel_type)}`],
        ['Power / drive', `${show(candidate.reference_Maximum_output_KW)} kW · ${show(candidate.reference_Drive_system)}`],
        ['Structure', show(candidate.reference_Kind_of_structure)],
        ['Engine code', show(candidate.reference_Engine_code)],
        ['Production', `${show(candidate.reference_Construction_from)} → ${show(candidate.reference_Construction_to)}`],
        ['Power gap', candidate.power_difference_kw === null || candidate.power_difference_kw === undefined
          ? null
          : `${num(candidate.power_difference_kw, 1)} kW${candidate.power_within_triage_band ? ' (within triage band)' : ''}`],
        ['Year', show(candidate.year_relationship)],
        ['Criterion set', show(candidate.criterion_vector)],
        ['Review conflict priority', candidate.review_near_power_only
          ? 'sole near-power conflict'
          : candidate.review_identity_conflicts
            ? `identity conflict: ${candidate.review_identity_conflicts}`
            : candidate.review_configuration_conflicts
              ? `configuration conflict: ${candidate.review_configuration_conflicts}`
              : candidate.review_identity_agreements
                ? `identity agrees: ${candidate.review_identity_agreements}`
                : null],
        ['Text similarity', candidate.text_similarity_score === null || candidate.text_similarity_score === undefined
          ? null
          : `${num(candidate.text_similarity_score, 1)} · rank ${num(candidate.text_similarity_rank)} · ${show(candidate.text_similarity_method)}`],
        ['Similarity input', candidate.text_similarity_score === null || candidate.text_similarity_score === undefined
          ? null
          : `${show(candidate.text_similarity_source)} ↔ ${show(candidate.text_similarity_reference)}`],
      ])]),
    ]),
  ]);
}

/* ---------- Wiring --------------------------------------------------------- */

function bindUpload() {
  const zone = $('dropzone');
  const input = $('file-input');
  zone.addEventListener('click', () => input.click());
  zone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); }
  });
  input.addEventListener('change', () => chooseFile(input.files[0]));
  for (const name of ['dragenter', 'dragover']) {
    zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.add('over'); });
  }
  for (const name of ['dragleave', 'drop']) {
    zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.remove('over'); });
  }
  zone.addEventListener('drop', (event) => {
    const file = event.dataTransfer.files[0];
    if (file) { input.value = ''; chooseFile(file); }
  });
  $('run-button').addEventListener('click', runMapping);
}

function bindRun() {
  for (const button of document.querySelectorAll('.tab')) {
    button.addEventListener('click', () => { state.tab = button.dataset.tab; renderRun(); });
  }
  $('download').addEventListener('click', () => {
    window.location.href = `/api/run/${state.run.run_id}/download`;
  });
  $('new-run').addEventListener('click', () => {
    state.run = null;
    closeDrawer();
    chooseFile(null);
    $('file-input').value = '';
    $('view-run').classList.add('hidden');
    $('view-upload').classList.remove('hidden');
    window.scrollTo({ top: 0 });
  });
}

async function init() {
  bindUpload();
  bindRun();
  try {
    state.defaults = await api('/api/defaults');
    if (state.defaults.payload_version !== EXPECTED_PAYLOAD_VERSION) {
      const box = $('upload-error');
      clear(box).append(
        el('b', { text: 'This page and the server are out of step' }),
        el('span', {
          text: `The page expects payload version ${EXPECTED_PAYLOAD_VERSION}; the server is serving `
              + `version ${state.defaults.payload_version ?? 'unknown'}. Restart it `
              + '(python -m webapp) and reload — otherwise some figures will be blank.',
        }));
      box.classList.remove('hidden');
    }
    $('meta-reference').textContent = state.defaults.reference_name;
    $('reference-name').textContent = state.defaults.reference_name;
    $('meta-version').textContent = state.defaults.algorithm_version;
    if (!state.defaults.reference_available) {
      const box = $('upload-error');
      clear(box).append(
        el('b', { text: 'The reference catalogue is missing' }),
        el('span', { text: `Expected ${state.defaults.reference_name} in data/. Nothing can be mapped without it.` }));
      box.classList.remove('hidden');
    }
  } catch (error) {
    const box = $('upload-error');
    clear(box).append(el('b', { text: 'Could not reach the server' }), el('span', { text: error.message }));
    box.classList.remove('hidden');
  }
}

init();
