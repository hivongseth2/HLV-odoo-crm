(() => {
  const AMIS_INVOICE_PATH = "/crm/invoice-request/generate/sale_order/invoice_request";
  const GRID_SELECTOR = ".body-grid.col-right.system-subform";
  const ROW_BODY_SELECTOR = ".field-item.wrap-body.ui-sortable";
  const SALE_INPUT_SELECTOR = 'input.misa-text-box[readonly][title^="DH"]';
  const FIELD_MAP = {
    ProductID: "product_code",
    TaxPercentID: "tax_percent",
    Tax: "tax",
    Total: "total",
  };
  const FALLBACK_CELL_INDEX = {
    product_code: 1,
    tax_percent: 11,
    tax: 12,
    total: 13,
  };

  let root;
  let lastResult = null;
  let lastCheckKey = "";
  let autoCheckDone = false;
  let pollCount = 0;

  function isInvoiceRequestPage() {
    return window.location.hostname === "amisapp.misa.vn"
      && window.location.pathname.startsWith(AMIS_INVOICE_PATH);
  }

  function textOf(el) {
    if (!el) return "";
    const input = el.querySelector("input, textarea, select");
    const value = input ? (input.value || input.getAttribute("title")) : "";
    return (value || el.getAttribute("title") || el.innerText || el.textContent || "").trim();
  }

  function findGrid() {
    return document.querySelector(GRID_SELECTOR)
      || document.querySelector(ROW_BODY_SELECTOR)?.closest("crm-table-input-grid")
      || document.querySelector(ROW_BODY_SELECTOR);
  }

  function findRowBody(grid) {
    return grid ? grid.querySelector(ROW_BODY_SELECTOR) : null;
  }

  function inferSaleName() {
    const directInput = document.querySelector(SALE_INPUT_SELECTOR)
      || Array.from(document.querySelectorAll("input[readonly], input.misa-text-box"))
        .find((input) => /^DH\d{6,}$/.test(((input.getAttribute("title") || input.value || "").trim())));
    return directInput ? (directInput.getAttribute("title") || directInput.value || "").trim() : "";
  }

  function parseRows(grid) {
    const rowBody = findRowBody(grid);
    const rows = Array.from((rowBody || grid).querySelectorAll(".wrap-row"));
    const sourceRows = rows.length ? rows : Array.from((rowBody || grid).querySelectorAll("tbody tr, .dx-row, [role='row']"));

    return sourceRows.map((row, idx) => {
      const line = {
        index: idx + 1,
        description: "",
        qty: "",
        price_unit: "",
        subtotal: "",
        tax_percent: "",
        tax: "",
        total: "",
        _row: row,
        _cells: {},
      };

      Object.entries(FIELD_MAP).forEach(([amisKey, outputKey]) => {
        const cell = row.querySelector(`.input-sticky-${amisKey}, .header-sticky-${amisKey}`);
        line[outputKey] = textOf(cell);
        if (cell) line._cells[outputKey] = cell;
      });

      if (!line.product_code) {
        const cells = Array.from(row.children);
        const values = cells.map(textOf);
        if (values.length >= 13 && /^\d+$/.test(values[0] || "")) {
          line.product_code = values[1] || "";
          line.description = values[2] || "";
          line.qty = values[5] || "";
          line.price_unit = values[6] || "";
          line.subtotal = values[8] || "";
          line.tax_percent = values[11] || "";
          line.tax = values[12] || "";
          line.total = values[13] || "";
          Object.entries(FALLBACK_CELL_INDEX).forEach(([field, cellIndex]) => {
            if (cells[cellIndex]) line._cells[field] = cells[cellIndex];
          });
        }
      }

      return line;
    }).filter((line) => line.product_code || line.description);
  }

  function payloadLines(lines) {
    return lines.map(({ _row, _cells, ...line }) => line);
  }

  function clearMarks() {
    document.querySelectorAll(".hlv-invoice-guard-bad-cell").forEach((el) => {
      el.classList.remove("hlv-invoice-guard-bad-cell");
      el.removeAttribute("data-hlv-issue");
    });
  }

  function markIssues(lines, issues) {
    clearMarks();
    const byIndex = new Map(lines.map((line) => [line.index, line]));
    (issues || []).forEach((issue) => {
      const line = byIndex.get(issue.line);
      if (!line) return;
      const cell = line._cells[issue.field] || line._cells.product_code;
      if (!cell) return;
      cell.classList.add("hlv-invoice-guard-bad-cell");
      cell.setAttribute("data-hlv-issue", issue.message || "Sai dữ liệu");
    });
  }

  function findInsertTarget(grid) {
    const group = grid.closest(".group-field") || grid.closest("crm-input-grid")?.parentElement || grid.parentElement;
    const footer = group?.querySelector("footer");
    return { group, footer };
  }

  function ensureRoot() {
    const grid = findGrid();
    if (!grid) return null;
    if (root && document.documentElement.contains(root)) return root;

    const { group, footer } = findInsertTarget(grid);
    if (!group) return null;

    root = document.createElement("div");
    root.className = "hlv-invoice-guard-inline";
    root.innerHTML = `
      <div class="hlv-invoice-guard-main">
        <div class="hlv-invoice-guard-title">HLV Invoice Guard</div>
        <input class="hlv-invoice-guard-sale" placeholder="Mã đơn bán Odoo">
        <button type="button" class="hlv-invoice-guard-check">Check</button>
        <button type="button" class="hlv-invoice-guard-compare">Đối chiếu</button>
        <span class="hlv-invoice-guard-status"></span>
      </div>
      <div class="hlv-invoice-guard-issues"></div>
      <div class="hlv-invoice-guard-compare-box" hidden></div>
    `;

    if (footer) {
      group.insertBefore(root, footer);
    } else {
      group.insertBefore(root, group.firstChild);
    }

    root.querySelector(".hlv-invoice-guard-check").addEventListener("click", () => runCheck({ force: true }));
    root.querySelector(".hlv-invoice-guard-compare").addEventListener("click", toggleCompare);
    return root;
  }

  function setStatus(message, mode = "") {
    const status = root?.querySelector(".hlv-invoice-guard-status");
    if (!status) return;
    status.className = `hlv-invoice-guard-status ${mode}`;
    status.textContent = message;
  }

  function renderIssues(result) {
    const list = root.querySelector(".hlv-invoice-guard-issues");
    list.innerHTML = "";
    if (!result.ok) {
      setStatus(result.message || result.error || "Check failed.", "is-error");
      return;
    }
    const summary = result.summary || {};
    if (summary.ok) {
      setStatus(`OK: ${summary.checked_line_count || 0} dòng khớp VAT, tiền thuế, tổng tiền.`, "is-ok");
      return;
    }
    setStatus(`${summary.issue_count || 0} lỗi / ${summary.checked_line_count || 0} dòng.`, "is-error");
    (result.issues || []).slice(0, 40).forEach((issue) => {
      const item = document.createElement("div");
      item.className = "hlv-invoice-guard-issue";
      item.textContent = `Dòng ${issue.line} ${issue.product_code || ""}: ${issue.message}`;
      list.appendChild(item);
    });
  }

  function getConfig() {
    return new Promise((resolve) => chrome.storage.sync.get(["apiToken"], resolve));
  }

  function callOdooCheck(payload) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "hlv_invoice_guard_check", payload }, (response) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: "runtime_message_failed", message: chrome.runtime.lastError.message });
          return;
        }
        resolve(response?.data || { ok: false, error: "empty_odoo_response", message: `HTTP ${response?.status || 0}` });
      });
    });
  }

  async function runCheck(options = {}) {
    if (!isInvoiceRequestPage()) return null;
    const grid = findGrid();
    const panel = ensureRoot();
    if (!grid || !panel) return null;

    const saleInput = panel.querySelector(".hlv-invoice-guard-sale");
    const detectedSaleName = inferSaleName();
    if (detectedSaleName && (!saleInput.value || !options.force)) {
      saleInput.value = detectedSaleName;
    }
    const saleName = saleInput.value.trim();
    const config = await getConfig();

    if (!saleName) {
      setStatus("Không detect được số đơn hàng DH.", "is-error");
      return null;
    }
    if (!config.apiToken) {
      setStatus("Thiếu API token trong extension.", "is-error");
      return null;
    }

    const lines = parseRows(grid);
    const checkKey = `${saleName}|${JSON.stringify(payloadLines(lines))}`;
    if (!options.force && checkKey === lastCheckKey) return lastResult;
    lastCheckKey = checkKey;

    setStatus(`Đang check ${lines.length} dòng...`);
    const result = await callOdooCheck({
      token: config.apiToken,
      sale_name: saleName,
      lines: payloadLines(lines),
    });
    lastResult = result;
    markIssues(lines, result.issues || []);
    renderIssues(result);
    if (options.showCompare) renderCompare(result);
    return result;
  }

  function formatMoney(value) {
    if (value === null || value === undefined || value === "") return "";
    const number = Number(value);
    if (Number.isNaN(number)) return String(value);
    return new Intl.NumberFormat("vi-VN").format(number);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[char]));
  }

  function renderOrderTable(title, order) {
    if (!order) return `<div class="hlv-invoice-guard-empty">${title}: không có dữ liệu.</div>`;
    const rows = (order.lines || []).map((line) => `
      <tr>
        <td>${escapeHtml(line.product_code || "")}</td>
        <td>${escapeHtml(line.product_name || line.description || "")}</td>
        <td class="num">${formatMoney(line.qty)}</td>
        <td class="num">${formatMoney(line.tax_percent)}%</td>
        <td class="num">${formatMoney(line.tax)}</td>
        <td class="num">${formatMoney(line.total)}</td>
      </tr>
    `).join("");
    return `
      <div class="hlv-invoice-guard-order">
        <div class="hlv-invoice-guard-order-title">${escapeHtml(title)}: ${escapeHtml(order.name || "")}</div>
        <div class="hlv-invoice-guard-order-meta">
          ${escapeHtml(order.partner?.name || "")} | VAT: ${escapeHtml(order.partner?.vat || "")} | Tổng: ${formatMoney(order.amount_total)}
        </div>
        <table>
          <thead><tr><th>Mã hàng</th><th>Tên hàng</th><th>SL</th><th>VAT</th><th>Tiền thuế</th><th>Tổng</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }

  async function toggleCompare() {
    const box = root?.querySelector(".hlv-invoice-guard-compare-box");
    if (!box) return;
    if (!box.hidden) {
      box.hidden = true;
      return;
    }
    const result = lastResult || await runCheck({ force: true, showCompare: true });
    if (result) renderCompare(result);
  }

  function renderCompare(result) {
    const box = root?.querySelector(".hlv-invoice-guard-compare-box");
    if (!box) return;
    box.hidden = false;
    box.innerHTML = `
      ${renderOrderTable("Đơn bán Odoo", result.sale_order)}
      ${renderOrderTable("Đơn mua liên kết", result.purchase_order)}
    `;
  }

  function scheduleSetup() {
    if (!isInvoiceRequestPage()) return;
    const grid = findGrid();
    if (!grid) return;
    const panel = ensureRoot();
    if (!panel) return;
    const saleName = inferSaleName();
    if (saleName && !panel.querySelector(".hlv-invoice-guard-sale").value) {
      panel.querySelector(".hlv-invoice-guard-sale").value = saleName;
    }
    if (autoCheckDone || !saleName) return;
    autoCheckDone = true;
    window.setTimeout(() => runCheck(), 800);
  }

  if (!isInvoiceRequestPage()) return;
  const poll = window.setInterval(() => {
    pollCount += 1;
    scheduleSetup();
    if (autoCheckDone || pollCount >= 60) window.clearInterval(poll);
  }, 1000);
  window.setTimeout(scheduleSetup, 2500);
})();
