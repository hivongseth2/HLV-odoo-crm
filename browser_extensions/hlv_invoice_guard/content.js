(() => {
  const GRID_SELECTOR = ".body-grid.col-right.system-subform";
  const FIELD_MAP = {
    ProductID: "product_code",
    Description: "description",
    Amount: "qty",
    Price: "price_unit",
    PriceAfterTax: "price_after_tax",
    TaxPercentID: "tax_percent",
    ToCurrency: "subtotal",
    Tax: "tax",
    Total: "total",
  };

  let panel;
  let lastGrid;

  function textOf(el) {
    if (!el) return "";
    const input = el.querySelector("input, textarea, select");
    const value = input ? (input.value || input.getAttribute("title")) : "";
    return (value || el.getAttribute("title") || el.innerText || el.textContent || "").trim();
  }

  function findGrid() {
    return document.querySelector(GRID_SELECTOR);
  }

  function inferSaleName() {
    const text = document.body.innerText || "";
    const matches = text.match(/\b(SO|S0|SOH|S)[A-Z0-9._/-]{3,}\b/g);
    return matches ? matches[0] : "";
  }

  function extractRows(grid) {
    const rows = Array.from(grid.querySelectorAll(".wrap-body > .wrap-row"));
    return rows.map((row, idx) => {
      const line = { index: idx + 1 };
      Object.entries(FIELD_MAP).forEach(([amisKey, outputKey]) => {
        const cell = row.querySelector(`.input-sticky-${amisKey}, .header-sticky-${amisKey}`);
        line[outputKey] = textOf(cell);
      });
      line._row = row;
      return line;
    }).filter((line) => line.product_code || line.description);
  }

  function clearMarks() {
    document.querySelectorAll(".hlv-invoice-guard-bad-row").forEach((el) => {
      el.classList.remove("hlv-invoice-guard-bad-row");
    });
  }

  function markIssues(lines, issues) {
    clearMarks();
    const badIndexes = new Set((issues || []).map((issue) => issue.line));
    lines.forEach((line) => {
      if (badIndexes.has(line.index) && line._row) {
        line._row.classList.add("hlv-invoice-guard-bad-row");
      }
    });
  }

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement("div");
    panel.className = "hlv-invoice-guard-panel";
    panel.innerHTML = `
      <div class="hlv-invoice-guard-head">
        <span>HLV Invoice Guard</span>
        <button type="button" class="hlv-invoice-guard-close">Ẩn</button>
      </div>
      <div class="hlv-invoice-guard-body">
        <div class="hlv-invoice-guard-row">
          <input class="hlv-invoice-guard-sale" placeholder="Mã đơn bán Odoo, ví dụ SO00123">
          <button type="button" class="hlv-invoice-guard-check">Kiểm tra</button>
        </div>
        <div class="hlv-invoice-guard-status"></div>
        <div class="hlv-invoice-guard-issues"></div>
      </div>
    `;
    document.documentElement.appendChild(panel);
    panel.querySelector(".hlv-invoice-guard-sale").value = inferSaleName();
    panel.querySelector(".hlv-invoice-guard-close").addEventListener("click", () => {
      panel.style.display = "none";
    });
    panel.querySelector(".hlv-invoice-guard-check").addEventListener("click", runCheck);
    return panel;
  }

  function renderIssues(result) {
    const status = panel.querySelector(".hlv-invoice-guard-status");
    const list = panel.querySelector(".hlv-invoice-guard-issues");
    list.innerHTML = "";
    if (!result.ok) {
      status.textContent = result.message || result.error || "Không kiểm tra được.";
      return;
    }
    const summary = result.summary || {};
    if (summary.ok) {
      status.innerHTML = `<span class="hlv-invoice-guard-ok">Khớp ${summary.checked_line_count || 0} dòng.</span>`;
      return;
    }
    status.textContent = `Có ${summary.issue_count || 0} lỗi trên ${summary.checked_line_count || 0} dòng.`;
    (result.issues || []).slice(0, 80).forEach((issue) => {
      const item = document.createElement("div");
      item.className = "hlv-invoice-guard-issue";
      item.textContent = `Dòng ${issue.line} ${issue.product_code || ""}: ${issue.message}`;
      list.appendChild(item);
    });
  }

  function getConfig() {
    return new Promise((resolve) => {
      chrome.storage.sync.get(["odooBaseUrl", "apiToken"], resolve);
    });
  }

  async function runCheck() {
    const grid = findGrid();
    const p = ensurePanel();
    const status = p.querySelector(".hlv-invoice-guard-status");
    const saleName = p.querySelector(".hlv-invoice-guard-sale").value.trim();
    const config = await getConfig();

    if (!grid) {
      status.textContent = "Không tìm thấy grid hàng hóa trên trang.";
      return;
    }
    if (!saleName) {
      status.textContent = "Nhập mã đơn bán Odoo trước khi kiểm tra.";
      return;
    }
    if (!config.odooBaseUrl || !config.apiToken) {
      status.textContent = "Chưa cấu hình Odoo URL hoặc token trong popup extension.";
      return;
    }

    const lines = extractRows(grid);
    status.textContent = `Đang kiểm tra ${lines.length} dòng...`;
    try {
      const response = await fetch(`${config.odooBaseUrl}/api/hlv/invoice_guard/check`, {
        method: "POST",
        headers: { "Content-Type": "text/plain;charset=utf-8" },
        body: JSON.stringify({
          token: config.apiToken,
          sale_name: saleName,
          lines: lines.map(({ _row, ...line }) => line),
        }),
      });
      const result = await response.json();
      markIssues(lines, result.issues || []);
      renderIssues(result);
    } catch (error) {
      status.textContent = `Lỗi gọi Odoo: ${error.message}`;
    }
  }

  function tick() {
    const grid = findGrid();
    if (!grid || grid === lastGrid) return;
    lastGrid = grid;
    ensurePanel().style.display = "block";
  }

  tick();
  new MutationObserver(tick).observe(document.documentElement, { childList: true, subtree: true });
})();
