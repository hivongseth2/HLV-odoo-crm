
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
        params: { barcode }
      })
    })
      .then(res => res.json())
      .then(response => {
        const action = response.result;
        if (!action) return setStatus("danger", "❌ Không có action từ server.");

        console.log(response);
        

        if (action.type === "ir.actions.client" && action.tag === "display_notification") {
          setStatus("warning", "⚠️ " + action.params.message);
        } else {
          setStatus("success", "✅ Mở phiếu...");
        if (action.type === "ir.actions.act_url") {
          window.location.href = action.url; // 👉 tự xử lý url redirect
        } else if (window.odoo?.__DEBUG__?.services?.["web.action_service"]) {
          window.odoo.__DEBUG__.services["web.action_service"].doAction(action);
        } else {
          // window.location.href = "/custom_barcode_scan/ui"; 
          setStatus("success", "Phiếu không ở trạng thái đóng gói, kiểm tra lại...");
        }

        }
      })
      .catch(err => {
        console.error("❌ Lỗi fetch:", err);
        setStatus("danger", "❌ Lỗi khi gọi API.");
      });

    input.value = "";
  };

  input.addEventListener("keypress", function (e) {
    if (e.key === "Enter") triggerScan();
  });
});