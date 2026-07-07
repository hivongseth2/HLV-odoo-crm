const MSG_CHECK = "hlv_misa_po_check";
const MSG_SYNC = "hlv_misa_po_sync";
const MSG_REVOKE = "hlv_misa_po_revoke";

function normalizeBaseUrl(value) {
  return String(value || "").replace(/\/+$/, "");
}

async function readSettings() {
  const settings = await chrome.storage.sync.get(["odooBaseUrl", "apiToken"]);
  return {
    baseUrl: normalizeBaseUrl(settings.odooBaseUrl),
    token: String(settings.apiToken || "").trim(),
  };
}

async function requestJson(path, options = {}) {
  const settings = await readSettings();
  if (!settings.baseUrl || !settings.token) {
    return {
      ok: false,
      needsSettings: true,
      message: "Thiếu Odoo URL hoặc token.",
    };
  }

  const url = `${settings.baseUrl}${path}`;
  const method = options.method || "GET";
  const headers = {
    "Content-Type": "application/json",
    "X-MISA-Token": settings.token,
  };
  const fetchOptions = { method, headers };
  if (options.body) {
    fetchOptions.body = JSON.stringify(options.body);
  }

  const response = await fetch(url, fetchOptions);
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (error) {
    data = {
      ok: false,
      error: "invalid_json_response",
      message: text.slice(0, 500),
    };
  }

  return {
    ok: response.ok && data.ok !== false,
    status: response.status,
    data,
    message: data.message || data.error || response.statusText,
  };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || ![MSG_CHECK, MSG_SYNC, MSG_REVOKE].includes(message.type)) {
    return false;
  }

  (async () => {
    try {
      const poCode = encodeURIComponent(message.poCode || "");
      if (!poCode) {
        sendResponse({ ok: false, message: "Không tìm thấy mã đơn mua hàng." });
        return;
      }

      if (message.type === MSG_CHECK) {
        sendResponse(await requestJson(`/api/extension/po/check?po_code=${poCode}`));
        return;
      }

      const body = {
        po_code: message.poCode,
        create_when_missing: message.create_when_missing !== false,
        delete_when_missing: message.delete_when_missing !== false,
        source_url: message.source_url || "",
      };

      if (message.type === MSG_REVOKE) {
        body.create_when_missing = false;
        body.delete_when_missing = true;
        sendResponse(await requestJson("/api/extension/po/revoke", { method: "POST", body }));
        return;
      }

      sendResponse(await requestJson("/api/extension/po/sync", { method: "POST", body }));
    } catch (error) {
      sendResponse({ ok: false, message: error.message });
    }
  })();

  return true;
});
