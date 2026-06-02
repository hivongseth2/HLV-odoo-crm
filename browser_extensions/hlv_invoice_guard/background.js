const ODOO_BASE_URL = "https://www.hoanglongvu-erp.com";
const LOG_PREFIX = "[HLV Invoice Guard BG]";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "hlv_invoice_guard_check") {
    return false;
  }

  console.log(LOG_PREFIX, "check request", {
    sale_name: message.payload?.sale_name,
    line_count: message.payload?.lines?.length || 0,
  });

  fetch(`${ODOO_BASE_URL}/api/hlv/invoice_guard/check`, {
    method: "POST",
    headers: { "Content-Type": "text/plain;charset=utf-8" },
    body: JSON.stringify(message.payload || {}),
  })
    .then(async (response) => {
      const text = await response.text();
      console.log(LOG_PREFIX, "odoo response", response.status, text.slice(0, 300));
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
      console.error(LOG_PREFIX, "fetch failed", error);
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
