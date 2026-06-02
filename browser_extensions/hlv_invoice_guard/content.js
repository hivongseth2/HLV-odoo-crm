(() => {
  const LOG_PREFIX = "[HLV Invoice Guard]";
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
    tax_percent: 9,
    tax: 10,
    total: 11,
  };

  let root;
  let lastResult = null;
  let lastLines = [];
  let lastCheckKey = "";
  let autoCheckDone = false;
  let pollCount = 0;
  let lastPath = "";
  let connectorRedrawTimer = null;

  function log(...args) {
    console.log(LOG_PREFIX, ...args);
  }

  log("content loaded", window.location.href);

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

  function compactText(value) {
    return (value || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/đ/g, "d")
      .replace(/\s+/g, " ")
      .trim();
  }

  function findProductSection() {
    const headings = Array.from(document.querySelectorAll("h1,h2,h3,h4,span,div,label"));
    const heading = headings.find((el) => compactText(textOf(el)) === "thong tin hang hoa")
      || headings.find((el) => {
        const text = compactText(textOf(el));
        return text.includes("thong tin hang hoa") && text.length < 80;
      });
    if (!heading) return null;
    return heading.closest(".group-field")
      || heading.closest("section")
      || heading.parentElement?.parentElement
      || heading.parentElement;
  }

  function findProductTableByHeaders() {
    return Array.from(document.querySelectorAll("table")).find((table) => {
      const headerText = compactText(Array.from(table.querySelectorAll("thead th, th"))
        .map(textOf)
        .join(" "));
      return headerText.includes("ma hang hoa")
        && headerText.includes("thue suat")
        && headerText.includes("tien thue")
        && headerText.includes("tong tien");
    }) || null;
  }

  function findGrid() {
    const productSection = findProductSection();
    const grid = productSection?.querySelector(GRID_SELECTOR)
      || productSection?.querySelector("table")
      || productSection?.querySelector("[role='table']")
      || productSection?.querySelector(ROW_BODY_SELECTOR)
      || findProductTableByHeaders()
      || document.querySelector(GRID_SELECTOR)
      || document.querySelector(ROW_BODY_SELECTOR)?.closest("crm-table-input-grid")
      || document.querySelector(ROW_BODY_SELECTOR);
    if (isInvoiceRequestPage()) {
      log("findGrid", {
        hasProductSection: Boolean(productSection),
        gridTag: grid?.tagName || null,
        gridClass: grid?.className || null,
      });
    }
    return grid;
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

  function headerMap(grid) {
    const headers = Array.from(grid.querySelectorAll("thead th, .crm-table-header, [role='columnheader']"))
      .map((header, index) => ({ key: compactText(textOf(header)), index }));
    const find = (...names) => {
      const normalized = names.map(compactText);
      const found = headers.find((header) => normalized.includes(header.key));
      return found ? found.index : -1;
    };
    return {
      product_code: find("Mã hàng hóa", "Mã hàng", "Mã HH"),
      tax_percent: find("Thuế suất"),
      tax: find("Tiền thuế"),
      total: find("Tổng tiền"),
    };
  }

  function parseRows(grid) {
    const rowBody = findRowBody(grid);
    const rows = Array.from((rowBody || grid).querySelectorAll(".wrap-row"));
    const sourceRows = rows.length ? rows : Array.from((rowBody || grid).querySelectorAll("tbody tr, .dx-row, [role='row']"));
    const columns = headerMap(grid);

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
        const productIndex = columns.product_code >= 0 ? columns.product_code : FALLBACK_CELL_INDEX.product_code;
        const taxPercentIndex = columns.tax_percent >= 0 ? columns.tax_percent : FALLBACK_CELL_INDEX.tax_percent;
        const taxIndex = columns.tax >= 0 ? columns.tax : FALLBACK_CELL_INDEX.tax;
        const totalIndex = columns.total >= 0 ? columns.total : FALLBACK_CELL_INDEX.total;

        if (values.length && values.some(Boolean) && !/tong cong/i.test(compactText(values.join(" ")))) {
          line.product_code = values[productIndex] || "";
          line.tax_percent = values[taxPercentIndex] || "";
          line.tax = values[taxIndex] || "";
          line.total = values[totalIndex] || "";
          if (cells[productIndex]) line._cells.product_code = cells[productIndex];
          if (cells[taxPercentIndex]) line._cells.tax_percent = cells[taxPercentIndex];
          if (cells[taxIndex]) line._cells.tax = cells[taxIndex];
          if (cells[totalIndex]) line._cells.total = cells[totalIndex];
        }
      }

      return line;
    }).filter((line) => line.product_code || line.description);
  }

  function payloadLines(lines) {
    return lines.map(({ _row, _cells, ...line }) => line);
  }

  function normalizeNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value === "number") return value;
    const text = String(value).trim().replace("%", "").replace(/\s+/g, "");
    if (!text) return null;
    const normalized = text.replace(/\./g, "").replace(",", ".");
    const number = Number(normalized);
    return Number.isNaN(number) ? null : number;
  }

  function numberDiffers(actual, expected, tolerance = 0.01) {
    if (actual === null || expected === null) return false;
    return Math.abs(actual - expected) > tolerance;
  }

  function lineMap(lines) {
    const map = new Map();
    (lines || []).forEach((line) => {
      const code = String(line.product_code || "").trim().toUpperCase();
      if (!code) return;
      if (!map.has(code)) {
        map.set(code, { ...line });
        return;
      }
      const current = map.get(code);
      ["qty", "tax", "total"].forEach((field) => {
        current[field] = (normalizeNumber(current[field]) || 0) + (normalizeNumber(line[field]) || 0);
      });
    });
    return map;
  }

  function issueKey(issue) {
    return `${issue.line || ""}:${normalizedCode(issue.product_code)}:${issue.field || ""}`;
  }

  function issueExists(issues, line, productCode, field, message) {
    const key = `${line || ""}:${normalizedCode(productCode)}:${field || ""}`;
    return issues.some((issue) => issueKey(issue) === key && issue.message === message);
  }

  function addIssue(issues, line, productCode, field, message, actual, expected) {
    if (issueExists(issues, line, productCode, field, message)) return;
    issues.push({
      line,
      product_code: productCode,
      field,
      message,
      actual,
      expected,
      diff: actual !== null && expected !== null ? actual - expected : null,
    });
  }

  function enforcePurchaseCompare(result, crmLines) {
    if (!result || !result.ok) return result;
    const issues = Array.isArray(result.issues) ? [...result.issues] : [];
    const po = result.purchase_order;
    const poByCode = lineMap(po?.lines || []);

    crmLines.forEach((crmLine) => {
      const code = String(crmLine.product_code || "").trim().toUpperCase();
      if (!code) return;
      const poLine = poByCode.get(code);
      if (!po) {
        addIssue(issues, crmLine.index, code, "product_code", "Không tìm thấy đơn mua liên kết.", null, null);
        return;
      }
      if (!poLine) {
        addIssue(issues, crmLine.index, code, "product_code", "Mã hàng không có trong đơn mua liên kết.", null, null);
        return;
      }

      [
        ["qty", "Số lượng CRM/đơn mua lệch", 0.01],
        ["tax_percent", "VAT CRM/đơn mua lệch", 0.01],
        ["tax", "Tiền thuế CRM/đơn mua lệch", 1],
        ["total", "Tổng tiền CRM/đơn mua lệch", 1],
      ].forEach(([field, label, tolerance]) => {
        const sameFieldPurchaseIssue = issues.some((issue) => (
          issue.line === crmLine.index
          && normalizedCode(issue.product_code) === code
          && issue.field === field
          && isSalePurchaseIssue(issue)
        ));
        if (sameFieldPurchaseIssue) return;

        const actual = normalizeNumber(crmLine[field]);
        const expected = normalizeNumber(poLine[field]);
        if (numberDiffers(actual, expected, tolerance)) {
          addIssue(
            issues,
            crmLine.index,
            code,
            field,
            `${label}: CRM=${crmLine[field]}, PO=${poLine[field]}.`,
            actual,
            expected,
          );
        }
      });
    });

    const collapsedIssues = collapseIssues(issues);
    return {
      ...result,
      issues: collapsedIssues,
      summary: {
        ...(result.summary || {}),
        ok: collapsedIssues.length === 0,
        issue_count: collapsedIssues.length,
        checked_line_count: crmLines.length,
      },
    };
  }

  function collapseIssues(issues) {
    const byKey = new Map();
    (issues || []).forEach((issue) => {
      const key = issueKey(issue);
      const previous = byKey.get(key);
      if (!previous) {
        byKey.set(key, issue);
        return;
      }
      if (isSalePurchaseIssue(issue) && !isSalePurchaseIssue(previous)) {
        byKey.set(key, issue);
      }
    });
    return Array.from(byKey.values());
  }

  function clearMarks() {
    document.querySelectorAll(".hlv-invoice-guard-bad-cell, .hlv-invoice-guard-ok-cell").forEach((el) => {
      el.classList.remove("hlv-invoice-guard-bad-cell");
      el.classList.remove("hlv-invoice-guard-ok-cell");
      el.removeAttribute("data-hlv-issue");
      el.removeAttribute("data-hlv-crm-line");
      el.removeAttribute("data-hlv-field");
    });
    document.querySelector(".hlv-invoice-guard-lines")?.remove();
  }

  function isCrmPurchaseIssue(issue) {
    return compactText(issue?.message || "").includes("crm/don mua");
  }

  function isSalePurchaseIssue(issue) {
    return compactText(issue?.message || "").includes("don ban/don mua");
  }

  function isPurchaseOnlyIssue(issue) {
    const message = compactText(issue?.message || "");
    return isCrmPurchaseIssue(issue)
      || isSalePurchaseIssue(issue)
      || message.includes("khong co trong don mua")
      || message.includes("khong tim thay don mua");
  }

  function isCrmSaleIssue(issue) {
    return !isPurchaseOnlyIssue(issue);
  }

  function markIssues(lines, issues) {
    clearMarks();
    const byIndex = new Map(lines.map((line) => [line.index, line]));
    const crmSaleIssues = (issues || []).filter(isCrmSaleIssue);
    const crmSaleIssueKeys = new Set(crmSaleIssues.map((issue) => `${issue.line}:${issue.field}`));

    lines.forEach((line) => {
      ["tax_percent", "tax", "total"].forEach((field) => {
        const cell = line._cells[field];
        if (!cell) return;
        cell.setAttribute("data-hlv-crm-line", String(line.index));
        cell.setAttribute("data-hlv-field", field);
        if (!crmSaleIssueKeys.has(`${line.index}:${field}`)) {
          cell.classList.add("hlv-invoice-guard-ok-cell");
        }
      });
    });

    crmSaleIssues.forEach((issue) => {
      const line = byIndex.get(issue.line);
      if (!line) return;
      const cell = line._cells[issue.field] || line._cells.product_code;
      if (!cell) return;
      cell.classList.add("hlv-invoice-guard-bad-cell");
      cell.setAttribute("data-hlv-issue", issue.message || "Sai dữ liệu");
    });
  }

  function findInsertTarget(grid) {
    const section = findProductSection();
    const group = section || grid.closest(".group-field") || grid.closest("crm-input-grid")?.parentElement || grid.parentElement;
    const table = group?.querySelector("table, crm-input-grid, crm-table-input-grid, .table");
    return { group, table };
  }

  function ensureRoot() {
    const grid = findGrid();
    if (!grid) return null;
    if (root && document.documentElement.contains(root)) return root;

    const { group, table } = findInsertTarget(grid);
    if (!group) return null;
    log("inject inline bar", { groupTag: group.tagName, groupClass: group.className, tableTag: table?.tagName || null });

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

    if (table && table.parentNode) {
      table.parentNode.insertBefore(root, table);
    } else {
      group.appendChild(root);
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
      setStatus(`OK: ${summary.checked_line_count || 0} dòng khớp CRM + đơn bán + đơn mua.`, "is-ok");
      return;
    }
    setStatus(`${summary.issue_count || 0} lỗi / ${summary.checked_line_count || 0} dòng.`, "is-error");
    collapseIssues(result.issues || []).slice(0, 40).forEach((issue) => {
      const item = document.createElement("div");
      item.className = "hlv-invoice-guard-issue";
      item.textContent = `Dòng ${issue.line} ${issue.product_code || ""}: ${issue.message}`;
      list.appendChild(item);
    });
  }

  function getConfig() {
    return new Promise((resolve) => {
      try {
        chrome.storage.sync.get(["apiToken"], resolve);
      } catch (error) {
        resolve({
          apiToken: "",
          _contextError: error.message || String(error),
        });
      }
    });
  }

  function callOdooCheck(payload) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type: "hlv_invoice_guard_check", payload }, (response) => {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, error: "runtime_message_failed", message: chrome.runtime.lastError.message });
            return;
          }
          resolve(response?.data || { ok: false, error: "empty_odoo_response", message: `HTTP ${response?.status || 0}` });
        });
      } catch (error) {
        resolve({
          ok: false,
          error: "extension_context_invalidated",
          message: `${error.message || error}. Refresh lại tab AMIS sau khi reload extension.`,
        });
      }
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
    if (config._contextError) {
      setStatus(`Extension context invalidated. Refresh lại tab AMIS. (${config._contextError})`, "is-error");
      return null;
    }
    if (!config.apiToken) {
      setStatus("Thiếu API token trong extension.", "is-error");
      return null;
    }

    const lines = parseRows(grid);
    lastLines = lines;
    log("parsed lines", lines.map((line) => ({
      index: line.index,
      product_code: line.product_code,
      tax_percent: line.tax_percent,
      tax: line.tax,
      total: line.total,
    })));
    const checkKey = `${saleName}|${JSON.stringify(payloadLines(lines))}`;
    if (!options.force && checkKey === lastCheckKey) return lastResult;
    lastCheckKey = checkKey;

    setStatus(`Đang check ${lines.length} dòng...`);
    let result = await callOdooCheck({
      token: config.apiToken,
      sale_name: saleName,
      lines: payloadLines(lines),
    });
    result = enforcePurchaseCompare(result, lines);
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

  function normalizedCode(value) {
    return String(value || "").trim().toUpperCase();
  }

  function ensureCompareIssueBucket(map, side, code, field) {
    if (!map[side].has(code)) map[side].set(code, new Map());
    const fields = map[side].get(code);
    if (!fields.has(field)) fields.set(field, []);
    return fields.get(field);
  }

  function addCompareIssue(map, side, code, field, message) {
    const normalized = normalizedCode(code);
    if (!normalized) return;
    ensureCompareIssueBucket(map, side, normalized, field).push(message);
  }

  function compareIssueMap(result) {
    const map = {
      sale: new Map(),
      purchase: new Map(),
    };
    collapseIssues(result.issues || []).forEach((issue) => {
      const field = issue.field || "product_code";
      const message = issue.message || "";
      const code = issue.product_code || "";
      const normalizedMessage = compactText(message);

      if (normalizedMessage.includes("crm/don mua")) {
        addCompareIssue(map, "purchase", code, field, message);
        return;
      }
      if (normalizedMessage.includes("don ban/don mua")) {
        addCompareIssue(map, "purchase", code, field, message);
        return;
      }
      if (normalizedMessage.includes("khong co trong don mua") || normalizedMessage.includes("khong tim thay don mua")) {
        addCompareIssue(map, "sale", code, "product_code", message);
        return;
      }
      if (normalizedMessage.includes("don ban odoo") || normalizedMessage.includes("odoo")) {
        addCompareIssue(map, "sale", code, field, message);
      }
    });
    return map;
  }

  function compareOkClass(issueMap, side, code, field) {
    if (!["qty", "tax_percent", "tax", "total"].includes(field)) return "";
    return compareCellClass(issueMap, side, code, field) ? "" : "hlv-invoice-guard-compare-ok";
  }

  function compareCellClass(issueMap, side, code, field) {
    const messages = issueMap?.[side]?.get(normalizedCode(code))?.get(field);
    return messages?.length ? "hlv-invoice-guard-compare-bad" : "";
  }

  function compareCellTitle(issueMap, side, code, field) {
    const messages = issueMap?.[side]?.get(normalizedCode(code))?.get(field);
    return messages?.length ? escapeHtml(messages.join("\n")) : "";
  }

  function compareCellAttrs(issueMap, side, code, field) {
    const cls = compareCellClass(issueMap, side, code, field);
    const title = compareCellTitle(issueMap, side, code, field);
    return cls ? ` class="${cls}" title="${title}"` : "";
  }

  function compareDataAttrs(side, code, field) {
    return ` data-hlv-compare-side="${side}" data-hlv-code="${escapeHtml(normalizedCode(code))}" data-hlv-field="${field}"`;
  }

  function renderOrderTable(title, order, side, issueMap) {
    if (!order) return `<div class="hlv-invoice-guard-empty">${title}: không có dữ liệu.</div>`;
    const rows = (order.lines || []).map((line) => `
      <tr>
        <td${compareCellAttrs(issueMap, side, line.product_code, "product_code")}${compareDataAttrs(side, line.product_code, "product_code")}>${escapeHtml(line.product_code || "")}</td>
        <td>${escapeHtml(line.product_name || line.description || "")}</td>
        <td class="num ${compareCellClass(issueMap, side, line.product_code, "qty")} ${compareOkClass(issueMap, side, line.product_code, "qty")}" title="${compareCellTitle(issueMap, side, line.product_code, "qty")}"${compareDataAttrs(side, line.product_code, "qty")}>${formatMoney(line.qty)}</td>
        <td class="num ${compareCellClass(issueMap, side, line.product_code, "tax_percent")} ${compareOkClass(issueMap, side, line.product_code, "tax_percent")}" title="${compareCellTitle(issueMap, side, line.product_code, "tax_percent")}"${compareDataAttrs(side, line.product_code, "tax_percent")}>${formatMoney(line.tax_percent)}%</td>
        <td class="num ${compareCellClass(issueMap, side, line.product_code, "tax")} ${compareOkClass(issueMap, side, line.product_code, "tax")}" title="${compareCellTitle(issueMap, side, line.product_code, "tax")}"${compareDataAttrs(side, line.product_code, "tax")}>${formatMoney(line.tax)}</td>
        <td class="num ${compareCellClass(issueMap, side, line.product_code, "total")} ${compareOkClass(issueMap, side, line.product_code, "total")}" title="${compareCellTitle(issueMap, side, line.product_code, "total")}"${compareDataAttrs(side, line.product_code, "total")}>${formatMoney(line.total)}</td>
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
      document.querySelector(".hlv-invoice-guard-lines")?.remove();
      return;
    }
    const result = lastResult || await runCheck({ force: true, showCompare: true });
    if (result) renderCompare(result);
  }

  function renderCompare(result) {
    const box = root?.querySelector(".hlv-invoice-guard-compare-box");
    if (!box) return;
    const issueMap = compareIssueMap(result || {});
    box.hidden = false;
    box.innerHTML = `
      ${renderOrderTable("Đơn bán Odoo", result.sale_order, "sale", issueMap)}
      ${renderOrderTable("Đơn mua liên kết", result.purchase_order, "purchase", issueMap)}
    `;
    scheduleConnectorRedraw();
  }

  function cellCenter(rect, side) {
    return {
      x: (side === "left" ? rect.left : rect.right) + window.scrollX,
      y: rect.top + rect.height / 2 + window.scrollY,
    };
  }

  function scheduleConnectorRedraw() {
    window.clearTimeout(connectorRedrawTimer);
    connectorRedrawTimer = window.setTimeout(() => {
      const box = root?.querySelector(".hlv-invoice-guard-compare-box");
      if (!lastResult || !box || box.hidden) return;
      drawConnectorLines(lastResult);
    }, 60);
  }

  function drawConnectorLines(result) {
    document.querySelector(".hlv-invoice-guard-lines")?.remove();
    const lineIssues = collapseIssues(result?.issues || []).filter((issue) => isCrmPurchaseIssue(issue) || isSalePurchaseIssue(issue));
    if (!lineIssues.length) return;
    const docWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth, window.innerWidth);
    const docHeight = Math.max(document.documentElement.scrollHeight, document.body.scrollHeight, window.innerHeight);

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("hlv-invoice-guard-lines");
    svg.setAttribute("width", String(docWidth));
    svg.setAttribute("height", String(docHeight));
    svg.setAttribute("viewBox", `0 0 ${docWidth} ${docHeight}`);

    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.innerHTML = `
      <marker id="hlv-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
        <path d="M0,0 L8,4 L0,8 Z" fill="#dc2626"></path>
      </marker>
    `;
    svg.appendChild(defs);

    lineIssues.forEach((issue) => {
      const crmLine = lastLines.find((line) => line.index === issue.line);
      const source = crmLine?._cells?.[issue.field];
      const targetSide = isCrmPurchaseIssue(issue) || isSalePurchaseIssue(issue) ? "purchase" : "sale";
      const target = document.querySelector(
        `[data-hlv-compare-side="${targetSide}"][data-hlv-code="${CSS.escape(normalizedCode(issue.product_code))}"][data-hlv-field="${issue.field}"]`,
      );
      if (!source || !target) return;

      const from = cellCenter(source.getBoundingClientRect(), "left");
      const to = cellCenter(target.getBoundingClientRect(), "right");
      const midX = Math.max(0, Math.min(docWidth, (from.x + to.x) / 2));
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", `M ${from.x} ${from.y} C ${midX} ${from.y}, ${midX} ${to.y}, ${to.x} ${to.y}`);
      path.setAttribute("class", "hlv-invoice-guard-line");
      path.setAttribute("marker-end", "url(#hlv-arrow)");
      svg.appendChild(path);
    });

    document.body.appendChild(svg);
  }

  function scheduleSetup() {
    if (!isInvoiceRequestPage()) return;
    const grid = findGrid();
    if (!grid) {
      log("waiting: grid not found");
      return;
    }
    const panel = ensureRoot();
    if (!panel) {
      log("waiting: root not injected");
      return;
    }
    const saleName = inferSaleName();
    if (saleName && !panel.querySelector(".hlv-invoice-guard-sale").value) {
      panel.querySelector(".hlv-invoice-guard-sale").value = saleName;
    }
    if (autoCheckDone || !saleName) return;
    autoCheckDone = true;
    window.setTimeout(() => runCheck(), 800);
  }

  const poll = window.setInterval(() => {
    if (lastPath !== window.location.pathname) {
      lastPath = window.location.pathname;
      log("path", lastPath, "isInvoice", isInvoiceRequestPage());
      if (isInvoiceRequestPage()) {
        autoCheckDone = false;
        lastCheckKey = "";
      }
    }
    pollCount += 1;
    scheduleSetup();
    if (pollCount >= 300) window.clearInterval(poll);
  }, 1000);
  window.setTimeout(scheduleSetup, 2500);
  window.addEventListener("scroll", scheduleConnectorRedraw, true);
  window.addEventListener("resize", scheduleConnectorRedraw);
})();
