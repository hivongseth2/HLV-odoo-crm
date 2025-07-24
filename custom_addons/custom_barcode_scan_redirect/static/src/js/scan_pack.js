document.addEventListener("DOMContentLoaded", function () {
  const input = document.getElementById("pack_barcode_input");
  const list = document.getElementById("product_list");
  const completeBtn = document.getElementById("complete_pack_btn");
  const pickingId = parseInt(window.location.pathname.split("/").pop());

  function setFocus() {
    setTimeout(() => input.focus(), 100);
  }


  
  function playSuccess() {
    new Audio("/custom_barcode_scan_redirect/static/src/sound/success.mp3").play();
  }

  function playError() {
    new Audio("/custom_barcode_scan_redirect/static/src/sound/error.mp3").play();
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
            barcode,
            delta
          }
        })
      })
      .then(res => res.json())
      .then(response => {
        const result = response.result;
        if (result.error) {
          alert(result.error);
          playError();
          setFocus();
          return;
        }

        result.scanned.forEach(item => {
          const el = [...list.children].find(li =>
            li.dataset.barcode === barcode
          );
          if (el) {
            el.querySelector(".done").innerText = item.done_qty;

            if (item.done_qty > item.required_qty) {
              el.classList.remove("completed");
              el.classList.add("over");
              playError();
            } else if (item.done_qty === item.required_qty) {
              el.classList.remove("over");
              el.classList.add("completed");
              playSuccess();
            } else {
              el.classList.remove("completed", "over");
              playSuccess();
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

  // Check nếu còn dòng nào chưa đủ số lượng
  const items = document.querySelectorAll("#product_list .product-item");
  let isValid = true;
  let missingProducts = [];

  items.forEach(item => {
    const name = item.querySelector("strong").innerText;
    const done = parseFloat(item.querySelector(".done").innerText);
    const required = parseFloat(item.querySelectorAll("span")[2].innerText);

    if (done < required) {
      isValid = false;
      missingProducts.push(`${name} (${done}/${required})`);
    }
  });

  if (!isValid) {
    alert("❌ Chưa quét đủ các sản phẩm sau:\n\n- " + missingProducts.join("\n- "));
    return;
  }

  // Nếu đủ hết thì cho gửi request hoàn tất
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