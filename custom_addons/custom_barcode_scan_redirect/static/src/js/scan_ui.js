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

      if (action.type === "ir.actions.client" && action.tag === "display_notification") {
        return setStatus("warning", "⚠️ " + action.params.message);
      }

      setStatus("success", "✅ Phiếu: " + action.picking.name);

      const container = document.getElementById("scan_status");
      container.innerHTML += `
        <div style="margin-top: 12px">
          <strong>Khách:</strong> ${action.picking.partner}<br/>
          <strong>Ngày:</strong> ${action.picking.scheduled_date}<br/>
          <strong>Trạng thái:</strong> ${action.picking.state}<br/>
          <strong>Sản phẩm:</strong>
          <ul>
            ${action.picking.products.map(p => `<li>${p.product_name}: ${p.qty_done}/${p.qty_total}</li>`).join("")}
          </ul>
        </div>
      `;
    } catch (err) {
      console.error("❌ Lỗi fetch:", err);
      setStatus("danger", "❌ Lỗi khi gọi API.");
    }

    input.value = "";
    input.focus();
  }

  window.triggerScan = triggerScan;
  input.addEventListener("keypress", function (e) {
    if (e.key === "Enter") triggerScan();
  });

  input.focus();
});
