document.addEventListener("DOMContentLoaded", function () {
  const input = document.getElementById("barcode_input");
  const status = document.getElementById("scan_status");

  function setStatus(type, message) {
    status.className = "scan-status alert-" + type;
    status.innerText = message;
    status.style.display = "block";
  }

  window.triggerScan = async function () {
    const barcode = input.value.trim();
    if (!barcode) return setStatus("warning", "⚠️ Vui lòng nhập mã phiếu.");

    setStatus("info", "⏳ Đang xử lý mã: " + barcode);

    try {
      const res = await fetch("/custom_barcode_scan/ui/scan", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "call",
          params: { barcode }
        })
      });

      const response = await res.json();
      const action = response.result;
      if (!action) return setStatus("danger", "❌ Không có action từ server.");

      if (action.type === "ir.actions.client" && action.tag === "display_notification") {
        setStatus("warning", "⚠️ " + action.params.message);
      } else {
        setStatus("success", "✅ Mở phiếu...");

        if (window.odoo?.__DEBUG__?.services?.["web.action_service"]) {
          await window.odoo.__DEBUG__.services["web.action_service"].doAction(action);
        } else {
          // fallback
          window.location.href = '/web#action=' + encodeURIComponent(JSON.stringify(action));
        }
      }
    } catch (err) {
      console.error("❌ Lỗi fetch:", err);
      setStatus("danger", "❌ Lỗi khi gọi API.");
    }

    input.value = "";
  };

  input.addEventListener("keypress", function (e) {
    if (e.key === "Enter") triggerScan();
  });
});
