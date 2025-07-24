document.addEventListener("DOMContentLoaded", function () {
  const input = document.getElementById("pack_barcode_input");
  const list = document.getElementById("product_list");
  const completeBtn = document.getElementById("complete_pack_btn");
  const pickingId = parseInt(window.location.pathname.split("/").pop());

  function setFocus() {
    setTimeout(() => input.focus(), 100);
  }

  function updateQty(barcode, delta = 1) {
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
          barcode: barcode,
          delta: delta
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
          if (item.done_qty >= item.required_qty) {
            el.classList.add("completed");
          } else {
            el.classList.remove("completed");
          }
        }
      });

      setFocus();
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

  list.querySelectorAll(".btn-plus").forEach(btn =>
    btn.addEventListener("click", () =>
      updateQty(btn.dataset.barcode, 1)
    )
  );

  list.querySelectorAll(".btn-minus").forEach(btn =>
    btn.addEventListener("click", () =>
      updateQty(btn.dataset.barcode, -1)
    )
  );

  completeBtn.addEventListener("click", function () {
    if (!confirm("Xác nhận hoàn tất đóng gói phiếu?")) return;

    fetch("/pack_scan/complete_picking", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest"
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: {
          picking_id: pickingId
        }
      })
    })
      .then(res => res.json())
      .then(response => {
        if (response.error) {
          alert("❌ " + response.error);
        } else {
          alert(response.message || "✅ Phiếu đã hoàn tất!");
          window.location.href = "/custom_barcode_scan/ui";
        }
      });
  });

  setFocus();
});
