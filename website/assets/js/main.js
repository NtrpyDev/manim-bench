const EMPTY = "n/a";

const METRICS = {
  score: {
    title: "Overall ManimBench score",
    caption: "Higher is better. Automated checks plus optional visual review.",
    key: "score",
    format: (v) => (v == null ? EMPTY : v.toFixed(1)),
    higherIsBetter: true,
  },
  cost: {
    title: "Estimated cost (USD)",
    caption: "Lower is better. Provider-aware pricing from token counts.",
    key: "cost_usd",
    format: (v) => (v == null ? EMPTY : `$${v.toFixed(3)}`),
    higherIsBetter: false,
  },
  time: {
    title: "Wall-clock time (seconds)",
    caption: "Lower is better. Generation and benchmark pipeline time.",
    key: "elapsed_seconds",
    format: (v) => (v == null ? EMPTY : `${Math.round(v)}s`),
    higherIsBetter: false,
  },
  tokens: {
    title: "Output tokens",
    caption: "Lower is often better at equal quality.",
    key: "output_tokens",
    format: (v) => (v == null ? EMPTY : Math.round(v).toLocaleString()),
    higherIsBetter: false,
  },
};

const state = {
  data: null,
  metric: "score",
  focusModel: "",
};

const els = {
  modelSelect: document.getElementById("model-select"),
  resultsBody: document.getElementById("results-body"),
  chart: document.getElementById("rank-chart"),
  chartBody: document.getElementById("chart-body"),
  chartTitle: document.getElementById("chart-title"),
  chartCaption: document.getElementById("chart-caption"),
  emptyState: document.getElementById("empty-state"),
  modelCount: document.getElementById("model-count"),
  updatedAt: document.getElementById("updated-at"),
  suiteLabel: document.getElementById("suite-label"),
  heroTopScore: document.getElementById("hero-top-score"),
  headerSuiteLabel: document.getElementById("header-suite-label"),
  headerModelCount: document.getElementById("header-model-count"),
  headerUpdatedAt: document.getElementById("header-updated-at"),
};

init();

async function init() {
  setupMetricTabs();
  setupParallax();
  els.modelSelect.addEventListener("change", () => {
    state.focusModel = els.modelSelect.value;
    renderAll();
  });
  window.addEventListener("resize", debounce(renderChart, 120));

  try {
    const response = await fetch("data/leaderboard.json", { cache: "no-cache" });
    state.data = await response.json();
  } catch {
    state.data = { models: [], status: "awaiting_data" };
  }

  populateModelSelect();
  updateMeta();
  renderAll();
}

function setupMetricTabs() {
  document.querySelectorAll(".metric-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".metric-tab").forEach((other) => {
        other.classList.remove("active");
        other.setAttribute("aria-selected", "false");
      });
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      state.metric = tab.dataset.metric;
      const meta = METRICS[state.metric];
      els.chartTitle.textContent = meta.title;
      els.chartCaption.textContent = meta.caption;
      renderAll();
    });
  });
}

function populateModelSelect() {
  const models = state.data?.models ?? [];
  els.modelSelect.innerHTML = '<option value="">All models</option>';
  for (const entry of models) {
    const option = document.createElement("option");
    option.value = entry.model;
    option.textContent = entry.model;
    els.modelSelect.append(option);
  }
}

function updateMeta() {
  const models = state.data?.models ?? [];
  const suite = state.data?.suite ?? {};
  els.modelCount.textContent = String(models.length);
  const suiteText = suite.title || suite.id || "V0.4 public";
  const updatedText = formatDate(state.data?.updated_at);
  els.suiteLabel.textContent = suiteText;
  els.updatedAt.textContent = updatedText;
  if (els.headerSuiteLabel) els.headerSuiteLabel.textContent = suiteText;
  if (els.headerModelCount) els.headerModelCount.textContent = String(models.length);
  if (els.headerUpdatedAt) els.headerUpdatedAt.textContent = updatedText;

  if (!models.length) {
    els.heroTopScore.textContent = EMPTY;
    return;
  }

  const byScore = [...models].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  els.heroTopScore.textContent = METRICS.score.format(byScore[0].score);
}

function renderAll() {
  renderTable();
  renderChart();
}

function renderTable() {
  const models = state.data?.models ?? [];
  els.resultsBody.innerHTML = "";

  if (!models.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="8" style="text-align:center;color:var(--text-muted);padding:1.25rem">No results yet</td>`;
    els.resultsBody.append(row);
    return;
  }

  const sorted = sortModels(models);
  for (const entry of sorted) {
    const row = document.createElement("tr");
    const focused = state.focusModel && state.focusModel === entry.model;
    const dimmed = state.focusModel && !focused;
    if (focused) row.classList.add("focused");
    if (dimmed) row.classList.add("dimmed");

    row.innerHTML = `
      <td>${entry.rank ?? EMPTY}</td>
      <td>${escapeHtml(entry.model)}</td>
      <td>${METRICS.score.format(entry.score)}</td>
      <td>${entry.adjusted_visual_score == null ? EMPTY : entry.adjusted_visual_score.toFixed(1)}</td>
      <td>${METRICS.cost.format(entry.cost_usd)}</td>
      <td>${METRICS.time.format(entry.elapsed_seconds)}</td>
      <td>${METRICS.tokens.format(entry.output_tokens)}</td>
      <td>${reviewBadge(entry.review_status)}</td>
    `;
    row.addEventListener("click", () => {
      state.focusModel = state.focusModel === entry.model ? "" : entry.model;
      els.modelSelect.value = state.focusModel;
      renderAll();
    });
    els.resultsBody.append(row);
  }
}

function sortModels(models) {
  const meta = METRICS[state.metric];
  const key = meta.key;
  const copy = [...models];
  copy.sort((a, b) => {
    const av = a[key] ?? (meta.higherIsBetter ? -Infinity : Infinity);
    const bv = b[key] ?? (meta.higherIsBetter ? -Infinity : Infinity);
    return meta.higherIsBetter ? bv - av : av - bv;
  });
  return copy.map((entry, index) => ({ ...entry, rank: index + 1 }));
}

function renderChart() {
  const canvas = els.chart;
  const ctx = canvas.getContext("2d");
  const models = sortModels(state.data?.models ?? []);

  if (!models.length) {
    els.emptyState.classList.remove("hidden");
    canvas.classList.add("hidden");
    return;
  }

  els.emptyState.classList.add("hidden");
  canvas.classList.remove("hidden");

  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 960;
  const height = Math.max(220, 48 + models.length * 44);
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  els.chartBody.style.minHeight = `${height}px`;

  const meta = METRICS[state.metric];
  const key = meta.key;
  const values = models.map((m) => m[key]).filter((v) => v != null);
  const maxVal = Math.max(...values, meta.higherIsBetter ? 1 : 0.001);
  const padding = { top: 16, right: 16, bottom: 16, left: 140 };
  const chartW = width - padding.left - padding.right;
  const barGap = 10;
  const barH = Math.min(32, (height - padding.top - padding.bottom - barGap * (models.length - 1)) / models.length);

  models.forEach((entry, index) => {
    const raw = entry[key];
    const value = raw ?? 0;
    const ratio = value / maxVal;
    const barWidth = Math.max(4, ratio * chartW);
    const y = padding.top + index * (barH + barGap);
    const focused = !state.focusModel || state.focusModel === entry.model;

    const barColors = ["#5c6b8a", "#7a8ba8", "#4a6741", "#b85c38", "#8b6914", "#2d7a52"];
    const barColor = barColors[index % barColors.length];

    ctx.fillStyle = focused ? barColor : `${barColor}55`;
    roundRect(ctx, padding.left, y, barWidth, barH, 6);
    ctx.fill();

    ctx.fillStyle = focused ? "#1f1c18" : "rgba(31,28,24,0.45)";
    ctx.font = "600 13px IBM Plex Sans, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(entry.model, padding.left - 10, y + barH / 2);

    ctx.textAlign = "left";
    ctx.fillStyle = focused ? barColor : `${barColor}99`;
    ctx.font = "500 12px IBM Plex Sans, sans-serif";
    ctx.fillText(meta.format(raw), padding.left + barWidth + 8, y + barH / 2);
  });
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function reviewBadge(status) {
  const value = status || "pending";
  return `<span class="badge badge-${escapeHtml(value)}">${escapeHtml(value)}</span>`;
}

function formatDate(value) {
  if (!value) return "Not yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function setupParallax() {
  /* decorative parallax removed in benchmark layout */
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}
