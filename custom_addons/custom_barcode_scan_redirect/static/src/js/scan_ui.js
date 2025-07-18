document.addEventListener("DOMContentLoaded", function () {
  const input = document.getElementById("barcode_input");
  const status = document.getElementById("scan_status");

  function setStatus(type, message) {
    status.className = "scan-status alert-" + type;
    status.innerText = message;
    status.style.display = "block";
  }

  async function triggerScan() {
    const barcode = input.value.trim();
    if (!barcode) return setStatus("warning", "⚠️ Vui lòng nhập mã phiếu.");

    setStatus("info", "⏳ Đang xử lý mã: " + barcode);

    try {
      const res = await fetch("/custom_barcode_scan/ui/scan", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "call",
          params: { barcode },
        }),
      });

      const response = await res.json();
      const action = response.result;

      if (!action) return setStatus("danger", "❌ Không có action từ server.");

      // Thông báo đơn giản
      if (action.type === "ir.actions.client" && action.tag === "display_notification") {
        return setStatus("warning", "⚠️ " + action.params.message);
      }

      setStatus("success", "✅ Mở phiếu...");

      if (window.odoo?.__DEBUG__?.services?.["web.action_service"]) {
        const actionService = window.odoo.__DEBUG__.services["web.action_service"];
        if (action.action_id) {
          await actionService.doAction(action.action_id, {
            additional_context: action.context || {},
          });
        } else {
          console.warn("⚠️ Action không có action_id:", action);
          setStatus("danger", "❌ Action không hợp lệ từ server.");
        }
      } else {
        // fallback nếu không có OWL
        setStatus("info", "🔄 Chuyển hướng bằng fallback...");
        if (action.action_id) {
          window.location.href = `/web#action=${action.action_id}&active_id=${action.context?.active_id}`;
        }
      }
    } catch (err) {
      console.error("❌ Lỗi fetch:", err);
      setStatus("danger", "❌ Lỗi khi gọi API.");
    }

    input.value = "";
    input.focus(); // auto focus lại sau khi scan
  }

  input.addEventListener("keypress", function (e) {
    if (e.key === "Enter") triggerScan();
  });

  input.focus(); // focus khi load
});
