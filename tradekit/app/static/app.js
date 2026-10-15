const state = {
  health: null,
  overview: null,
};

const $ = (id) => document.getElementById(id);

function setBadge(el, ok, goodText, badText) {
  el.className = `badge ${ok ? "good" : "bad"}`;
  el.textContent = ok ? goodText : badText;
}

function formatJson(value) {
  return JSON.stringify(value, null, 2);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function loadHealth() {
  const data = await fetchJson("/health");
  state.health = data;
  setBadge($("tradeKitBadge"), Boolean(data.okx_cli?.installed), "可用", "不可用");
  $("cliVersion").textContent = data.okx_cli?.version?.stdout?.split("\n")[0] || "--";
  $("policyMode").textContent = data.policy?.mode || "--";
  $("orderLimit").textContent = data.policy?.limits?.max_order_notional_usdt
    ? `${data.policy.limits.max_order_notional_usdt} USDT`
    : "--";
}

async function loadOverview() {
  const data = await fetchJson("/okk/overview");
  state.overview = data;
  setBadge($("okkBadge"), Boolean(data.status?.connected), "已连接", "未连接");
  $("strategyCount").textContent = data.strategy_count ?? "--";
  $("runningCount").textContent = data.running_strategy_count ?? "--";
  $("positionCount").textContent = Array.isArray(data.swap_positions) ? data.swap_positions.length : "--";
  renderNotes(data.copilot_notes || []);
  renderStrategies(data.strategies || []);
}

function renderNotes(notes) {
  $("notes").innerHTML = notes.map((note) => `<div class="note">${escapeHtml(note)}</div>`).join("");
}

function renderStrategies(strategies) {
  if (!strategies.length) {
    $("strategies").innerHTML = `<div class="note">暂无策略数据</div>`;
    return;
  }

  $("strategies").innerHTML = strategies
    .map((item) => {
      const id = item.id ?? "";
      const name = item.name || `策略 ${id}`;
      const type = item.type || "--";
      const symbol = item.symbol || "--";
      const status = item.status || "--";
      return `
        <div class="strategy-item">
          <div>
            <div class="strategy-title">${escapeHtml(name)}</div>
            <div class="strategy-meta">${escapeHtml(type)} · ${escapeHtml(symbol)} · ${escapeHtml(status)}</div>
          </div>
          <button class="small-button" data-advice-id="${id}">建议</button>
        </div>
      `;
    })
    .join("");

  document.querySelectorAll("[data-advice-id]").forEach((button) => {
    button.addEventListener("click", () => loadAdvice(button.dataset.adviceId));
  });
}

async function loadTicker() {
  const instId = $("tickerInput").value.trim();
  $("tickerOutput").textContent = "查询中";
  try {
    const data = await fetchJson(`/market/ticker/${encodeURIComponent(instId)}`);
    $("tickerOutput").textContent = data.stdout || formatJson(data);
  } catch (error) {
    $("tickerOutput").textContent = error.message;
  }
}

async function reviewProposal() {
  $("reviewOutput").textContent = "评估中";
  const payload = {
    inst_id: $("intentInst").value.trim(),
    side: $("intentSide").value,
    product_type: "swap",
    notional_usdt: Number($("intentNotional").value),
    leverage: Number($("intentLeverage").value),
    order_type: "market",
    reason: $("intentReason").value.trim(),
    source: "tradekit-ui",
  };

  try {
    const data = await fetchJson("/proposal/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("reviewOutput").textContent = formatJson(data);
  } catch (error) {
    $("reviewOutput").textContent = error.message;
  }
}

async function loadAdvice(strategyId) {
  $("reviewOutput").textContent = `读取策略 ${strategyId} 建议中`;
  try {
    const data = await fetchJson(`/okk/strategies/${strategyId}/advice`);
    $("reviewOutput").textContent = formatJson(data.advice || data);
  } catch (error) {
    $("reviewOutput").textContent = error.message;
  }
}

async function refreshAll() {
  $("tradeKitBadge").className = "badge muted";
  $("tradeKitBadge").textContent = "检测中";
  $("okkBadge").className = "badge muted";
  $("okkBadge").textContent = "检测中";

  await Promise.allSettled([loadHealth(), loadOverview()]);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

$("refreshBtn").addEventListener("click", refreshAll);
$("overviewBtn").addEventListener("click", loadOverview);
$("tickerBtn").addEventListener("click", loadTicker);
$("reviewBtn").addEventListener("click", reviewProposal);

refreshAll();
