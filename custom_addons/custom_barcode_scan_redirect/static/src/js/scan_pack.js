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
  function findLineToUpdate(barcode) {
    const elements = [...document.querySelectorAll(`[data-barcode="${barcode}"]`)];
    for (const el of elements) {
      const doneEl = el.querySelector(".done");
      const requiredEl = el.querySelectorAll("span")[1];

      const done = parseFloat(doneEl?.innerText || 0);
      const required = parseFloat(requiredEl?.innerText || 0);

      if (done < required) {
        return el.dataset.lineId;
      }
    }
    return null; // tất cả đã đủ
  }

  function updateQty(barcode, delta = 1, lineId = null) {
    if (!lineId) {
      lineId = findLineToUpdate(barcode);
    } 
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
          delta,
          line_id: lineId  

        }
      })
    })
      .then(res => res.json())
      .then(response => {
        const result = response.result;
        if (result?.error) {
          alert(result.error);
          playError();
          setFocus();
          return;
        }

        if (!result?.scanned?.length) {
          playError();
          setFocus();
          return;
        }

        result.scanned.forEach(item => {
          const el = document.querySelector(`[data-line-id="${item.line_id}"]`);
          if (!el) return;

          const doneEl = el.querySelector(".done");
          const requiredEl = el.querySelectorAll("span")[1]; // span sau dấu "/"
          const required = parseFloat(requiredEl?.innerText || 0);

          doneEl.innerText = item.done_qty;

          if (item.done_qty >= required) {
            el.classList.add("completed");
          } else {
            el.classList.remove("completed");
          }
        });

        playSuccess();
        setFocus();
      });
  }

  // input.addEventListener("keypress", function (e) {
  //   if (e.key === "Enter") {
  //     const val = input.value.trim();
  //     if (val) {
  //       updateQty(val);
  //       input.value = "";
  //     }
  //   }
  // });



  input.addEventListener("keypress", function (e) {
  if (e.key === "Enter") {
    const val = input.value.trim();
    if (!val) return;

    if (val === pickingName) {
      // ✅ Nếu là mã phiếu pick hiện tại → gọi hoàn tất luôn
      fetch("/pack_scan/complete_picking", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "call",
          params: { picking_id: pickingId }
        })
      })
        .then(res => res.json())
        .then(response => {
          if (response.error) {
            alert(response.error);
            playError();
          } else {
            alert(response.message || "✅ Phiếu đã hoàn tất!");
            playSuccess();
            window.location.href = "/custom_barcode_scan/ui";
          }
        });

      input.value = "";
      return;
    }

    // Nếu không phải mã phiếu → quét sản phẩm như thường
    updateQty(val);
    input.value = "";
  }
});

  list.querySelectorAll(".btn-plus").forEach(btn =>
    btn.addEventListener("click", () =>
      updateQty(btn.dataset.barcode, 1, btn.dataset.lineId)
    )
  );

  list.querySelectorAll(".btn-minus").forEach(btn =>
    btn.addEventListener("click", () =>
      updateQty(btn.dataset.barcode, -1, btn.dataset.lineId)
    )
  );


  completeBtn.addEventListener("click", function () {
    if (!confirm("Xác nhận hoàn tất đóng gói phiếu?")) return;

    const items = document.querySelectorAll("#product_list .product-item");
    let isValid = true;
    let missingProducts = [];

    items.forEach(item => {
      const name = item.querySelector("strong").innerText;
      const doneEl = item.querySelector(".done");
      const spanEls = item.querySelectorAll("span");

      const done = parseFloat(doneEl?.innerText || 0);
      const required = parseFloat(spanEls[1]?.innerText || 0);

      if (done < required) {
        isValid = false;
        missingProducts.push(`${name} (${done}/${required})`);
      }
    });

    if (!isValid) {
      alert("❌ Chưa quét đủ các sản phẩm sau:\n\n- " + missingProducts.join("\n- "));
      return;
    }

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
        if (response.error || response.result?.error) {
          const msg = response.error?.message || response.result?.error || "❌ Có lỗi xảy ra!";
          alert(msg);
          return;
        }

        alert(response.message || "✅ Phiếu đã hoàn tất!");
        window.location.href = "/custom_barcode_scan/ui";
      });
  });

  setFocus();
});
