(function () {
  const BUTTON_ID = "hlv-odoo-pr-import-button";

  function text(value) {
    return (value || "").toString().replace(/\s+/g, " ").trim();
  }

  function readAmisCrmToken() {
    const raw = localStorage.getItem("AMIS.CRM_token") || "";
    if (!raw) {
      return "";
    }
    try {
      const parsed = JSON.parse(raw);
      if (typeof parsed === "string") {
        return parsed;
      }
      return text(
        parsed.access_token ||
        parsed.token ||
        parsed.Token ||
        parsed.AccessToken ||
        parsed.value ||
        raw
      );
    } catch (error) {
      return text(raw);
    }
  }

  function controlText(fieldName) {
    const el = document.querySelector(`[data-pld="${fieldName}"]`);
    if (!el) {
      return "";
    }
    if (el.tagName === "SELECT") {
      const selected = el.selectedOptions && el.selectedOptions[0];
      if (selected && text(selected.textContent)) {
        return text(selected.textContent);
      }
    }
    if (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) && text(el.value)) {
      return text(el.value);
    }

    let node = el;
    for (let i = 0; node && i < 5; i += 1, node = node.parentElement) {
      if (text(node.getAttribute("title"))) {
        return text(node.getAttribute("title"));
      }
      const rendered = node.querySelector(".select2-selection__rendered, .text-view-label");
      if (rendered && text(rendered.textContent)) {
        return text(rendered.textContent);
      }
    }
    return text(el.textContent);
  }

  function fieldByLabel(labelText) {
    const labels = Array.from(document.querySelectorAll("label"));
    const label = labels.find((item) => text(item.textContent) === labelText);
    if (!label) {
      return "";
    }
    const row = label.closest("app-crm-field, .row-item");
    if (!row) {
      return "";
    }
    const value = row.querySelector(".text-view-label, .select2-selection__rendered");
    if (value && text(value.textContent)) {
      return text(value.textContent);
    }
    const input = row.querySelector("input, textarea, select");
    if (input) {
      return text(input.value || input.getAttribute("title"));
    }
    return "";
  }

  function extractLines() {
    const rows = Array.from(
      document.querySelectorAll(".grid_purchase_request_product .jsgrid-grid-body tbody tr")
    ).filter((row) => !row.classList.contains("summary-row"));

    return rows.map((row) => {
      const code = row.querySelector(".last-pin span, .last-pin div");
      const description = row.querySelector(".text-div-Description");
      const stock = row.querySelector(".div-StockID");
      const unit = row.querySelector(".div-UnitID");
      const numeric = Array.from(row.querySelectorAll("td.jsgrid-align-right div"))
        .map((item) => text(item.getAttribute("title") || item.textContent))
        .filter(Boolean);

      return {
        ProductIDText: text(code && code.textContent),
        Description: text(description && description.getAttribute("title")) || text(description && description.textContent),
        StockIDText: text(stock && stock.textContent),
        UnitIDText: text(unit && unit.textContent),
        Amount: numeric.length >= 2 ? numeric[numeric.length - 2] : "",
        QuantityFromAccounting: numeric.length >= 1 ? numeric[numeric.length - 1] : "",
      };
    }).filter((line) => line.ProductIDText || line.Description);
  }

  function extractPurchaseRequest() {
    return {
      PurchaseRequestNo: controlText("PurchaseRequestNo"),
      RequestDate: controlText("RequestDate"),
      PurchasePurpose: controlText("PurchasePurpose"),
      DeliveryAddress: controlText("DeliveryAddress"),
      DesiredDeliveryDeadline: controlText("DesiredDeliveryDeadline"),
      ProcessID: controlText("ProcessID"),
      ProcessStatusText: controlText("ProcessStatusID"),
      PurchaseStatusText: controlText("PurchaseStatusID"),
      Description: controlText("Description"),
      OwnerText: controlText("OwnerID"),
      SaleOrderNo: fieldByLabel("Đơn hàng"),
      OpportunityText: fieldByLabel("Cơ hội"),
      source_url: window.location.href,
      lines: extractLines(),
    };
  }

  function showStatus(message, isError) {
    const button = document.getElementById(BUTTON_ID);
    if (!button) {
      return;
    }
    button.textContent = message;
    button.style.background = isError ? "#c62828" : "#2e7d32";
    setTimeout(() => {
      button.textContent = "Tạo YCMH Odoo";
      button.style.background = "#1f6feb";
    }, 5000);
  }

  function ensureSettingsThenImport(payload) {
    chrome.storage.sync.get(["odooBaseUrl", "apiToken"], (settings) => {
      const updates = {};
      if (!settings.odooBaseUrl) {
        const url = window.prompt("Odoo base URL", "https://your-odoo-domain.com");
        if (!url) {
          showStatus("Thiếu Odoo URL", true);
          return;
        }
        updates.odooBaseUrl = url;
      }
      if (!settings.apiToken) {
        const token = window.prompt("Odoo import token");
        if (!token) {
          showStatus("Thiếu token", true);
          return;
        }
        updates.apiToken = token;
      }
      chrome.storage.sync.set(updates, () => importPayload(payload));
    });
  }

  function importPayload(payload) {
    chrome.runtime.sendMessage(
      { type: "HLV_IMPORT_PURCHASE_REQUEST", payload },
      (response) => {
        if (!response) {
          showStatus("Không nhận được phản hồi", true);
          return;
        }
        if (response.needsSettings) {
          chrome.storage.sync.remove(["odooBaseUrl", "apiToken"], () => ensureSettingsThenImport(payload));
          return;
        }
        if (!response.success) {
          const msg = response.body && response.body.message ? response.body.message : response.message;
          showStatus(msg || "Import lỗi", true);
          return;
        }
        const name = response.body.purchase_request_name || "OK";
        showStatus(`Đã tạo ${name}`, false);
      }
    );
  }

  function onClick() {
    const purchaseRequest = extractPurchaseRequest();
    const payload = {
      crm_token: readAmisCrmToken(),
      purchase_request: purchaseRequest,
    };
    if (!purchaseRequest.PurchaseRequestNo) {
      showStatus("Không thấy Số yêu cầu", true);
      return;
    }
    if (!purchaseRequest.lines.length) {
      showStatus("Không thấy dòng hàng hóa", true);
      return;
    }
    if (!payload.crm_token) {
      showStatus("Không thấy AMIS.CRM_token", true);
      return;
    }
    ensureSettingsThenImport(payload);
  }

  function mountButton() {
    if (document.getElementById(BUTTON_ID)) {
      return;
    }
    const button = document.createElement("button");
    button.id = BUTTON_ID;
    button.textContent = "Tạo YCMH Odoo";
    button.type = "button";
    button.style.cssText = [
      "position:fixed",
      "right:18px",
      "bottom:18px",
      "z-index:2147483647",
      "border:0",
      "border-radius:6px",
      "background:#1f6feb",
      "color:#fff",
      "font:600 13px Arial,sans-serif",
      "padding:10px 14px",
      "box-shadow:0 4px 12px rgba(0,0,0,.25)",
      "cursor:pointer",
    ].join(";");
    button.addEventListener("click", onClick);
    document.body.appendChild(button);
  }

  mountButton();
})();