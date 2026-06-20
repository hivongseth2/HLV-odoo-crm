chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "HLV_IMPORT_PURCHASE_REQUEST") {
    return false;
  }

  chrome.storage.sync.get(["odooBaseUrl", "apiToken"], async (settings) => {
    try {
      const baseUrl = (settings.odooBaseUrl || "").replace(/\/+$/, "");
      const token = settings.apiToken || "";
      if (!baseUrl || !token) {
        sendResponse({
          success: false,
          message: "Missing Odoo URL or import token. Click again and enter settings.",
          needsSettings: true,
        });
        return;
      }

      const response = await fetch(`${baseUrl}/misa/crm/purchase-request/import`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Odoo-PR-Token": token,
        },
        body: JSON.stringify(message.payload),
      });
      const body = await response.json().catch(() => ({}));
      sendResponse({
        success: response.ok && body.success,
        status: response.status,
        body,
        message: body.message || body.error || response.statusText,
      });
    } catch (error) {
      sendResponse({ success: false, message: error.message });
    }
  });

  return true;
});
