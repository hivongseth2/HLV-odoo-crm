(function () {
  const ROOT_ID = "hlv-misa-po-sync-root";
  const SYNC_TEXT = "Đã đồng bộ sang ứng dụng khác";
  const REVOKE_TEXT = "Thu hồi trên ứng dụng khác";
  const DETAIL_PATH_RE = /\/purchase\/popup\/purchaseorderdetail\/[0-9a-f-]+/i;

  let lastPoCode = "";
  let lastCheckAt = 0;
  let revokeHooked = false;

  function clean(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function isPoDetailPage() {
    return DETAIL_PATH_RE.test(window.location.href);
  }

  function findPoCode() {
    const inputs = Array.from(document.querySelectorAll("input[title], input[value]"));
    for (const input of inputs) {
      const value = clean(input.getAttribute("title") || input.value);
      const match = value.match(/\bDMH\d+\b/i);
      if (match) {
        return match[0].toUpperCase();
      }
    }

    const bodyText = clean(document.body && document.body.innerText);
    const match = bodyText.match(/\bDMH\d+\b/i);
    return match ? match[0].toUpperCase() : "";
  }

  function hasSyncedToOtherApp() {
    const nodes = Array.from(document.querySelectorAll("span, div, label"));
    return nodes.some((node) => clean(node.textContent) === SYNC_TEXT);
  }

  function findFooterRight() {
    return document.querySelector(".ms-footer-component .footer-button-right")
      || document.querySelector(".ms-footer-component .m-row")
      || document.body;
  }

  function showSettingsPrompt(done) {
    chrome.storage.sync.get(["odooBaseUrl", "apiToken"], (settings) => {
      const updates = {};
      if (!settings.odooBaseUrl) {
        const url = window.prompt("Odoo base URL", "https://www.hoanglongvu-erp.com");
        if (!url) {
          setStatus("Thiếu Odoo URL", "error");
          return;
        }
        updates.odooBaseUrl = url;
      }
      if (!settings.apiToken) {
        const token = window.prompt("Odoo API token", "hoanglongvu");
        if (!token) {
          setStatus("Thiếu token", "error");
          return;
        }
        updates.apiToken = token;
      }
      chrome.storage.sync.set(updates, done);
    });
  }

  function stateLabel(data) {
    if (!data) {
      return "Chưa kiểm tra";
    }
    if (data.status === "queued") {
      return data.status_label || "Đang chờ đồng bộ";
    }
    if (data.status === "failed") {
      return data.error_log || data.status_label || "Đồng bộ lỗi";
    }
    if (data.exists) {
      return `Đã có Odoo: ${data.status_label || data.status || data.name || ""}`;
    }
    return "Chưa có trên Odoo";
  }

  function setStatus(message, kind) {
    const root = document.getElementById(ROOT_ID);
    if (!root) {
      return;
    }
    const status = root.querySelector(".hlv-misa-po-status");
    if (!status) {
      return;
    }
    status.textContent = message;
    status.dataset.kind = kind || "info";
  }

  function setButtonState() {
    const root = document.getElementById(ROOT_ID);
    if (!root) {
      return;
    }
    const poCode = findPoCode();
    const externalSynced = hasSyncedToOtherApp();
    const syncButton = root.querySelector(".hlv-misa-po-sync-button");
    const revokeButton = root.querySelector(".hlv-misa-po-revoke-button");
    const codeNode = root.querySelector(".hlv-misa-po-code");

    codeNode.textContent = poCode || "Không thấy mã DMH";
    syncButton.disabled = !poCode || !externalSynced;
    syncButton.title = externalSynced
      ? "Đưa đơn mua hàng vào queue đồng bộ Odoo"
      : "Chỉ được đồng bộ sau khi MISA hiển thị Đã đồng bộ sang ứng dụng khác";
    revokeButton.disabled = !poCode;
    revokeButton.title = "Sau khi thu hồi trên MISA, đưa lệnh đồng bộ lại vào queue Odoo";

    if (!externalSynced) {
      setStatus("Chưa đồng bộ sang ứng dụng khác, chưa cho sync Odoo", "warn");
    }
  }

  function sendMessage(message, callback) {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        callback({ ok: false, message: chrome.runtime.lastError.message });
        return;
      }
      callback(response || { ok: false, message: "Không nhận được phản hồi." });
    });
  }

  function checkOdooStatus(force) {
    const poCode = findPoCode();
    if (!poCode) {
      setStatus("Không thấy mã DMH", "error");
      return;
    }
    const now = Date.now();
    if (!force && poCode === lastPoCode && now - lastCheckAt < 8000) {
      return;
    }
    lastPoCode = poCode;
    lastCheckAt = now;
    setStatus("Đang kiểm tra Odoo...", "info");
    sendMessage({ type: "hlv_misa_po_check", poCode }, (response) => {
      if (response.needsSettings) {
        showSettingsPrompt(() => checkOdooStatus(true));
        return;
      }
      if (!response.ok) {
        setStatus(response.message || "Kiểm tra Odoo lỗi", "error");
        return;
      }
      const kind = response.data && response.data.status === "failed"
        ? "error"
        : (response.data && response.data.exists ? "ok" : "warn");
      setStatus(stateLabel(response.data), kind);
    });
  }

  function queueSync(kind) {
    const poCode = findPoCode();
    if (!poCode) {
      setStatus("Không thấy mã DMH", "error");
      return;
    }
    if (kind === "sync" && !hasSyncedToOtherApp()) {
      setStatus("Chưa đồng bộ sang ứng dụng khác, chưa cho sync Odoo", "warn");
      return;
    }
    const type = kind === "revoke" ? "hlv_misa_po_revoke" : "hlv_misa_po_sync";
    setStatus(kind === "revoke" ? "Đang queue thu hồi/sync..." : "Đang queue sync Odoo...", "info");
    sendMessage({
      type,
      poCode,
      source_url: window.location.href,
      create_when_missing: kind !== "revoke",
      delete_when_missing: true,
    }, (response) => {
      if (response.needsSettings) {
        showSettingsPrompt(() => queueSync(kind));
        return;
      }
      if (!response.ok) {
        setStatus(response.message || "Queue lỗi", "error");
        return;
      }
      const queueId = response.data && response.data.queue_id;
      setStatus(queueId ? `Đã đưa vào queue #${queueId}` : "Đã đưa vào queue", "ok");
      setTimeout(() => checkOdooStatus(true), 1500);
    });
  }

  function mountPanel() {
    if (!isPoDetailPage()) {
      return;
    }
    let root = document.getElementById(ROOT_ID);
    if (!root) {
      root = document.createElement("div");
      root.id = ROOT_ID;
      root.innerHTML = [
        '<div class="hlv-misa-po-code"></div>',
        '<div class="hlv-misa-po-status" data-kind="info">Đang kiểm tra...</div>',
        '<div class="hlv-misa-po-actions">',
        '<button type="button" class="hlv-misa-po-sync-button">Sync qua Odoo</button>',
        '<button type="button" class="hlv-misa-po-revoke-button">Queue thu hồi Odoo</button>',
        '</div>',
      ].join("");
      root.querySelector(".hlv-misa-po-sync-button").addEventListener("click", () => queueSync("sync"));
      root.querySelector(".hlv-misa-po-revoke-button").addEventListener("click", () => queueSync("revoke"));

      const footerRight = findFooterRight();
      footerRight.insertBefore(root, footerRight.firstChild);
    }
    setButtonState();
    checkOdooStatus(false);
  }

  function hookRevokeButton() {
    if (revokeHooked || !isPoDetailPage()) {
      return;
    }
    const buttons = Array.from(document.querySelectorAll("button"));
    const revokeButton = buttons.find((button) => clean(button.textContent) === REVOKE_TEXT);
    if (!revokeButton) {
      return;
    }
    revokeHooked = true;
    revokeButton.addEventListener("click", () => {
      setStatus("Đã bắt thao tác thu hồi, sẽ queue Odoo sau 3 giây...", "info");
      setTimeout(() => queueSync("revoke"), 3000);
    }, true);
  }

  function tick() {
    if (!isPoDetailPage()) {
      return;
    }
    mountPanel();
    hookRevokeButton();
  }

  tick();
  const observer = new MutationObserver(tick);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  setInterval(tick, 3000);
})();
