document.addEventListener("DOMContentLoaded", function () {
  const input = document.getElementById("barcode_input");
  const status = document.getElementById("scan_status");

  function setStatus(type, message) {
    status.className = "scan-status alert-" + type;
    status.innerText = message;
    status.style.display = "block";
  }

  window.triggerScan = function () {
    const barcode = input.value.trim();
    if (!barcode) return setStatus("warning", "⚠️ Vui lòng nhập mã phiếu.");

    setStatus("info", "⏳ Đang xử lý mã: " + barcode);

    fetch("/custom_barcode_scan/ui/scan", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest"
      },
            body: JSON.stringify({
            jsonrpc: "2.0",
            method: "call",
            params: {
            barcode: barcode
            }
        })
        //    body: JSON.stringify({ barcode })
    })
      .then((res) => res.json())
      .then((action) => {
        if (action?.type === "ir.actions.client" && action.tag === "display_notification") {
          setStatus("warning", "⚠️ " + action.params.message);
        } else {
          // 🔥 Nếu là action (barcode scanner hoặc act_window)
          setStatus("success", "✅ Mở phiếu...");

          if (window.odoo?.__DEBUG__?.services?.["web.action_service"]) {
            window.odoo.__DEBUG__.services["web.action_service"].doAction(action);
          } else {
            // fallback cho các trường hợp dev mode không bật
            window.location.href = '/web#action=' + encodeURIComponent(JSON.stringify(action));
          }
        }
      })

    input.value = "";
  };

  input.addEventListener("keypress", function (e) {
    if (e.key === "Enter") triggerScan();
  });
});
