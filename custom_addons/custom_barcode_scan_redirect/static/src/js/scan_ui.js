
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
        } else if (action.type === 'custom_pack_selection') {
          // [NEW] Show Selection Modal
          setStatus("success", "✅ Tìm thấy nhiều phiếu...");
          showSelectionModal(action);
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

  // [NEW] Modal Helpers
  function showSelectionModal(action) {
    let modal = document.getElementById('selectionModal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'selectionModal';
      modal.className = 'modal-overlay'; // Re-use existing modal class if possible or define inline
      modal.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:9999;";
      document.body.appendChild(modal);
    }

    const itemsHtml = action.items.map(p => `
        <div class="pack-option" onclick="window.location.href='/custom_barcode_scan/pack_view/${p.id}'" 
             style="background:white;padding:12px;margin-bottom:8px;border-radius:8px;cursor:pointer;border:1px solid #ddd;display:flex;justify-content:space-between;align-items:center;">
             <div>
                <strong style="display:block;font-size:1.1rem;color:#2c3e50;">${p.name}</strong>
                <span style="font-size:0.9rem;color:#7f8c8d;">📅 ${p.date}</span>
             </div>
             <span class="badge" style="background:${p.state === 'assigned' ? '#2ecc71' : '#f1c40f'};color:white;padding:4px 8px;border-radius:4px;font-size:0.8rem;">
                ${p.state}
             </span>
        </div>
      `).join('');

    modal.innerHTML = `
        <div class="modal-content" style="background:#f8f9fa;width:90%;max-width:400px;border-radius:12px;overflow:hidden;box-shadow:0 4px 15px rgba(0,0,0,0.2);">
            <div class="modal-header" style="padding:15px;background:white;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center;">
                <h3 style="margin:0;font-size:1.1rem;">${action.title || 'Chọn phiếu Packing'}</h3>
                <button onclick="document.getElementById('selectionModal').style.display='none'" style="border:none;background:none;font-size:1.5rem;cursor:pointer;">&times;</button>
            </div>
            <div class="modal-body" style="padding:15px;max-height:60vh;overflow-y:auto;">
                ${itemsHtml}
            </div>
        </div>
      `;
    modal.style.display = 'flex';
  }
});