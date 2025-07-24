
document.addEventListener("DOMContentLoaded", function () {
  const input = document.getElementById("pack_barcode_input");
  const list = document.getElementById("product_list");
  const pickingId = parseInt(window.location.pathname.split("/").pop());

  function updateQty(barcode) {
    fetch("/pack_scan/scan_item", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest"
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: {
          picking_id: pickingId,
          barcode: barcode
        }
      })
    })
    .then(res => res.json())
    .then(response => {
      const result = response.result;
      if (result.error) {
        alert(result.error);
        return;
      }

      result.scanned.forEach(item => {
        const el = Array.from(list.children).find(li =>
          li.dataset.barcode === barcode
        );
        if (el) {
          el.querySelector(".done").innerText = item.done_qty;
        }
      });
    });
  }

  input.addEventListener("keypress", function (e) {
    if (e.key === "Enter") {
      const val = input.value.trim();
      if (val) {
        updateQty(val);
        input.value = "";
      }
    }
  });
});
