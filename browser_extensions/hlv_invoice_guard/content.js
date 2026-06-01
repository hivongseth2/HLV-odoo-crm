(() => {
  const AMIS_INVOICE_PATH = "/crm/invoice-request/generate/sale_order/invoice_request";
  const ODOO_BASE_URL = "https://hoanglongvu-stagin-v1-32562676.dev.odoo.com";
  const GRID_SELECTOR = ".body-grid.col-right.system-subform";
  const ROW_BODY_SELECTOR = ".field-item.wrap-body.ui-sortable";
  const SALE_INPUT_SELECTOR = 'input.misa-text-box[readonly][title^="DH"]';
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
  let lastAutoCheckKey = "";
  let autoCheckTimer;

  function isInvoiceRequestPage() {
    return window.location.hostname === "amisapp.misa.vn"
      && window.location.pathname === AMIS_INVOICE_PATH;
  }

  function textOf(el) {
    if (!el) return "";
    const input = el.querySelector("input, textarea, select");
    const value = input ? (input.value || input.getAttribute("title")) : "";
    return (value || el.getAttribute("title") || el.innerText || el.textContent || "").trim();
  }

  function findGrid() {
    return document.querySelector(GRID_SELECTOR);
  }

  function findRowBody(grid) {
    return grid ? grid.querySelector(ROW_BODY_SELECTOR) : null;
  }

  function inferSaleName() {
    const directInput = document.querySelector(SALE_INPUT_SELECTOR);
    const directTitle = directInput ? (directInput.getAttribute("title") || directInput.value || "").trim() : "";
    if (directTitle) return directTitle;

    const titledInput = Array.from(document.querySelectorAll("input[readonly][title]"))
      .map((input) => (input.getAttribute("title") || "").trim())
      .find((title) => /^DH\d{6,}$/.test(title));
    if (titledInput) return titledInput;

    const text = document.body.innerText || "";
    const matches = text.match(/\bDH\d{6,}\b/g);
    return matches ? matches[0] : "";
  }

  function extractRows(grid) {
    const rowBody = findRowBody(grid);
    const rows = Array.from((rowBody || grid).querySelectorAll(".wrap-row"));
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
        <button type="button" class="hlv-invoice-guard-close">Hide</button>
      </div>
      <div class="hlv-invoice-guard-body">
        <div class="hlv-invoice-guard-row">
          <input class="hlv-invoice-guard-sale" placeholder="Odoo sale order">
          <button type="button" class="hlv-invoice-guard-check">Check</button>
        </div>
        <div class="hlv-invoice-guard-status"></div>
        <div class="hlv-invoice-guard-issues"></div>
      </div>
    `;
    document.documentElement.appendChild(panel);
    panel.querySelector(".hlv-invoice-guard-close").addEventListener("click", () => {
      panel.style.display = "none";
    });
    panel.querySelector(".hlv-invoice-guard-check").addEventListener("click", () => runCheck({ force: true }));
    return panel;
  }

  function renderIssues(result) {
    const status = panel.querySelector(".hlv-invoice-guard-status");
    const list = panel.querySelector(".hlv-invoice-guard-issues");
    list.innerHTML = "";
    if (!result.ok) {
      status.textContent = result.message || result.error || "Check failed.";
      return;
    }
    const summary = result.summary || {};
    if (summary.ok) {
      status.innerHTML = `<span class="hlv-invoice-guard-ok">OK: matched ${summary.checked_line_count || 0} rows.</span>`;
      return;
    }
    status.textContent = `${summary.issue_count || 0} issue(s) in ${summary.checked_line_count || 0} checked row(s).`;
    (result.issues || []).slice(0, 80).forEach((issue) => {
      const item = document.createElement("div");
      item.className = "hlv-invoice-guard-issue";
      item.textContent = `Row ${issue.line} ${issue.product_code || ""}: ${issue.message}`;
      list.appendChild(item);
    });
  }

  function getConfig() {
    return new Promise((resolve) => {
      chrome.storage.sync.get(["apiToken"], resolve);
    });
  }

  async function runCheck(options = {}) {
    if (!isInvoiceRequestPage()) return;

    const grid = findGrid();
    const p = ensurePanel();
    const status = p.querySelector(".hlv-invoice-guard-status");
    const saleInput = p.querySelector(".hlv-invoice-guard-sale");
    const detectedSaleName = inferSaleName();
    if (detectedSaleName && (!saleInput.value || !options.force)) {
      saleInput.value = detectedSaleName;
    }
    const saleName = saleInput.value.trim();
    const config = await getConfig();

    if (!grid) {
      status.textContent = "AMIS product grid not found.";
      return;
    }
    if (!saleName) {
      status.textContent = "Sale order code not detected.";
      return;
    }
    if (!config.apiToken) {
      status.textContent = "Missing API token in extension popup.";
      return;
    }

    const lines = extractRows(grid);
    const checkKey = `${saleName}|${JSON.stringify(lines.map(({ _row, ...line }) => line))}`;
    if (!options.force && checkKey === lastAutoCheckKey) return;
    lastAutoCheckKey = checkKey;

    status.textContent = `Checking ${lines.length} row(s) against ${saleName}...`;
    try {
      const response = await fetch(`${ODOO_BASE_URL}/api/hlv/invoice_guard/check`, {
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
      status.textContent = `Odoo request error: ${error.message}`;
    }
  }

  function scheduleAutoCheck() {
    if (!isInvoiceRequestPage()) return;
    const grid = findGrid();
    const saleName = inferSaleName();
    if (!grid || !saleName) return;
    ensurePanel().style.display = "block";
    clearTimeout(autoCheckTimer);
    autoCheckTimer = setTimeout(() => runCheck(), 600);
  }

  scheduleAutoCheck();
  new MutationObserver(scheduleAutoCheck).observe(document.documentElement, { childList: true, subtree: true });
})();
