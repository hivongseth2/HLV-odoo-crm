const ODOO_BASE_URL = "https://hoanglongvu-stagin-v1-32562676.dev.odoo.com";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "hlv_invoice_guard_check") {
    return false;
  }

  fetch(`${ODOO_BASE_URL}/api/hlv/invoice_guard/check`, {
    method: "POST",
    headers: { "Content-Type": "text/plain;charset=utf-8" },
    body: JSON.stringify(message.payload || {}),
  })
    .then(async (response) => {
      const text = await response.text();
      let data;
      try {
        data = text ? JSON.parse(text) : {};
      } catch (error) {
        data = {
          ok: false,
          error: "invalid_json_response",
          message: text.slice(0, 500),
        };
      }
      sendResponse({
        ok: response.ok,
        status: response.status,
        data,
      });
    })
    .catch((error) => {
      sendResponse({
        ok: false,
        status: 0,
        data: {
          ok: false,
          error: "fetch_failed",
          message: error.message,
        },
      });
    });

  return true;
});
