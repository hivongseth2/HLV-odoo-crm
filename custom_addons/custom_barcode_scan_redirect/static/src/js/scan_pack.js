const toast = (() => {
  let host = document.getElementById('toastHost');
  if (!host) {
    host = document.createElement('div');
    host.id = 'toastHost';
    host.className = 'toast-host';
    document.body.appendChild(host);
  }
  const push = (type, message, { title = '', ms = 2500 } = {}) => {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `
    ${title ? `<div class="title">${title}</div>` : ''}
    <div class="msg">${message}</div>
    <div class="close" title="Đóng">×</div>
  `;
    host.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    const close = () => { el.classList.remove('show'); setTimeout(() => el.remove(), 200); };
    el.querySelector('.close').addEventListener('click', close);
    if (ms > 0) setTimeout(close, ms);
  };
  return {
    success: (m, o) => push('success', m, o),
    error: (m, o) => push('error', m, o),
    info: (m, o) => push('info', m, o),
    warn: (m, o) => push('warn', m, o),
    show: push,
  };
})();

document.addEventListener("DOMContentLoaded", function () {

  const input = document.getElementById("pack_barcode_input");
  const list = document.getElementById("product_list");
  const completeBtn = document.getElementById("complete_pack_btn");
  const pickingId = parseInt(window.location.pathname.split("/").pop());


  const enforceFocus = () => {
    const visibleModal = document.querySelector('.modal-overlay:not([style*="display: none"])');
    if (visibleModal) return; // Completely disable auto-focus if a modal is open

    const active = document.activeElement;
    // Allow focus if it's the Done Input or a Button
    if (active && (active.classList.contains('done-input') || active.tagName === 'BUTTON')) return;
    setFocus();
  };

  document.addEventListener('focusout', (e) => {
    // Check what will be focused next
    setTimeout(enforceFocus, 50);
  });

  document.addEventListener('click', (e) => {
    // If clicking safely -> ignore
    if (e.target.classList.contains('done-input') || e.target.closest('button') || e.target.closest('.modal-overlay')) return;
    // Otherwise force focus
    setFocus();
  });
  // ========================

  let lastKeyTime = 0;
  let fastKeyCount = 0;
  // [NEW] Semaphore to prevent double-packing (race condition)
  let isProcessingPack = false;

  document.addEventListener("keydown", (e) => {
    const now = Date.now();
    // Reset count if gap is large (> 70ms implies manual typing or start of new sequence)
    if (now - lastKeyTime < 70) {
      fastKeyCount++;
    } else {
      fastKeyCount = 0;
    }
    lastKeyTime = now;
  });



  window.handleManualQtyKey = function (event, el) {
    if (event.key === 'Enter') {
      el.blur(); // Trigger change
      setFocus(); // Focus back to barcode input
    }
  };

  window.handleManualQtyChange = async function (el) {
    const newVal = parseFloat(el.value);
    const oldVal = parseFloat(el.dataset.currentQty || 0); // Value before change (from dataset)

    // 1. Check Negative
    if (isNaN(newVal) || newVal < 0) {
      toast.warn("Số lượng không được nhỏ hơn 0");
      playError();
      el.value = oldVal;
      return;
    }

    // 2. Check Packed Constraint
    const itemEl = el.closest('.product-item');
    const packedQty = parseFloat(itemEl ? itemEl.getAttribute('data-packed-qty') : 0) || 0;

    if (newVal < packedQty) {
      toast.warn(`Đã đóng gói ${packedQty} sản phẩm. Không được sửa nhỏ hơn số lượng đã đóng gói!`);
      playError();
      el.value = oldVal;
      return;
    }

    // 2.5: Check Max Required Constraint (tránh nhập lố)
    const maxQty = parseFloat(el.dataset.maxQty || 0);

    if (maxQty > 0 && newVal > maxQty) { // Chỉ check nếu có maxQty set
      toast.warn(`Không được nhập quá số lượng yêu cầu (${maxQty})!`);
      playError();
      el.value = oldVal;
      return;
    }

    const delta = newVal - oldVal;
    if (delta === 0) return;

    // 3. Call Server to Update
    const barcode = el.dataset.barcode; // Prefer barcode if available
    const lineId = el.dataset.lineId;   // Or Line ID
    // Extract moveId from parent product-item element (reuse itemEl from above)
    const moveId = itemEl ? itemEl.dataset.moveId : null;

    try {
      // Pass lineId and moveId as explicit target
      await updateQty(barcode, delta, lineId, moveId);
      // Success: updateQty calls savePackageChanges -> updates UI & dataset.currentQty
    } catch (e) {
      // Fail: Revert UI
      // Note: updateQty already toasts error
      console.warn("Manual update failed, reverting...", e);
      el.value = oldVal;
    }
  };

  window.manualIncrement = async function (btn, amount) {
    const itemEl = btn.closest('.product-item'); // Find the row container
    if (!itemEl) return;

    const input = itemEl.querySelector('.done-input');
    if (!input) return;

    let currentVal = parseFloat(input.value || 0);
    // Fix floating point precision issues (e.g. 0.1 + 0.2 = 0.300000004)
    let newVal = parseFloat((currentVal + amount).toFixed(3));

    input.value = newVal;

    // Trigger change logic
    await window.handleManualQtyChange(input);
  };

  /* ----------------------------------------------------------- */

  const BARCODE_MAP_POINT_ONE = {
    "452424752161": "045242475216",//4361
    "452424752301": "045242475230", //4364
  };

  function setFocus() {
    setTimeout(() => input?.focus(), 100);
  }

  function playSuccess() {
    new Audio("/custom_barcode_scan_redirect/static/src/sound/success.mp3").play();
  }
  function playError() {
    new Audio("/custom_barcode_scan_redirect/static/src/sound/error.mp3").play();
  }

  // [NEW] Helper to flush manual input before critical actions
  async function flushActiveInput() {
    const active = document.activeElement;
    if (active && active.classList.contains('done-input')) {

      if (window.handleManualQtyChange) {
        await window.handleManualQtyChange(active);
      }
    }
  }

  function normalizeCode(s) {
    // Bỏ kí tự điều khiển ASCII, khoảng trắng, NBSP, BOM, zero-width, v.v.
    return String(s ?? '')
      .replace(/[\u0000-\u001F\u007F-\u009F]/g, '')   // control chars
      .replace(/[\u200B-\u200D\u2060\uFEFF]/g, '')    // zero-width & BOM
      .replace(/\s+/g, '')                             // mọi whitespace (kể cả NBSP)
      .trim();
  }
  window.normalizeCode = normalizeCode;

  function findLineToUpdate(barcode) {
    if (!barcode) return null;
    const searchCode = normalizeCode(barcode).toUpperCase();

    // 1. Tìm theo Barcode chính xác (Ưu tiên 1)
    let elements = [...document.querySelectorAll(`[data-barcode="${searchCode}"]`)];
    if (elements.length === 0) {
      elements = [...document.querySelectorAll(`[data-default-code="${searchCode}"]`)];
    }


    if (elements.length === 0) {
      const allItems = document.querySelectorAll('.product-item');
      for (const item of allItems) {
        const itemBar = normalizeCode(item.dataset.barcode || '').toUpperCase();
        if (itemBar.endsWith(searchCode) || searchCode.endsWith(itemBar)) {
          elements.push(item);
        }
      }
    }

    // [FIX] Priority Logic: Active (Partial) > Empty > First
    // Returns { lineId, moveId } to identify both move_line and stock.move
    let activeMatch = null;
    let emptyMatch = null;

    for (const el of elements) {
      // Changed: Support done-input or fallback to .done
      const input = el.querySelector(".done-input");
      const doneVal = input ? input.value : (el.querySelector(".done")?.innerText || 0);
      const done = parseFloat(doneVal) || 0; // [FIX] Ensure NaN becomes 0

      // Attempt to find required element relative to input (if input exists)
      const requiredEl = input ? input.nextElementSibling.nextElementSibling : el.querySelectorAll("span")[1];

      const required = parseFloat(requiredEl?.innerText || 0);

      const info = { lineId: el.dataset.lineId, moveId: el.dataset.moveId };

      // Prioritize "Active" (Partially Full) lines
      if (done > 0 && done < required) {
        return info; // Priority 1: Return immediately
      }

      // Store "Empty" line as fallback
      if (done === 0 && done < required && !emptyMatch) {
        emptyMatch = info;
      }
    }

    // Priority 2: Empty Line
    if (emptyMatch) return emptyMatch;

    // Priority 3: Fallback to first line (even if full, usually implies overflow)
    if (elements.length > 0) return { lineId: elements[0].dataset.lineId, moveId: elements[0].dataset.moveId };

    return null;
  }
  window.highlightElement = function (el, color = "#ffeb3b") { // Default strong yellow
    if (!el) return;

    // Clear previous transition/timers if any (simple approach)
    el.style.transition = "none";
    el.style.backgroundColor = "transparent";

    // Force Reflow
    void el.offsetWidth;

    el.style.transition = "background-color 0.4s ease-out";
    el.style.removeProperty("background-color"); // Clear first

    // Use cssText to ensure priority or just standard inline
    el.style.setProperty("background-color", color, "important");

    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    setTimeout(() => {
      el.style.transition = "background-color 1.5s ease-out"; // Slow fade
      el.style.backgroundColor = ""; // Remove inline, reverts to CSS
      // Cleanup transition style after fade
      setTimeout(() => { el.style.transition = ""; }, 1500);
    }, 600);
  };

  async function updateQty(barcode, delta = 1, lineId = null, moveId = null) {
    if (!lineId) {
      const found = findLineToUpdate(barcode);
      lineId = found?.lineId || null;
      moveId = found?.moveId || null;
    }
    // If we have lineId but no moveId, extract moveId from DOM
    if (lineId && !moveId) {
      const el = document.querySelector(`[data-line-id="${lineId}"]`);
      if (el) moveId = el.dataset.moveId || null;
    }

    // [NEW] Client-side Over-Quantity Validation
    if (lineId) {
      const checkEl = moveId
        ? document.querySelector(`[data-move-id="${moveId}"]`)
        : document.querySelector(`[data-line-id="${lineId}"]`);
      if (checkEl) {
        const maxQty = parseFloat(checkEl.getAttribute('data-max-qty') || 0);
        const input = checkEl.querySelector(".done-input");
        const currentDone = parseFloat(input ? input.value : (checkEl.querySelector(".done")?.innerText || 0));

        // Allow slight floating point tolerance if needed, but strict for > logic
        if (maxQty > 0 && (currentDone + delta) > maxQty) {
          toast.warn(`❌ Không được nhập quá số lượng yêu cầu (${maxQty})!`);
          playError();
          // Reset input if it was manual change (heuristic)
          if (input && Math.abs(currentDone - parseFloat(input.value)) > 0.001) {
            input.value = input.dataset.currentQty || 0;
          }
          return;
        }
      }
    }

    try {
      const res = await fetch("/pack_scan/scan_item", {
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
            line_id: lineId,
            move_id: moveId
          }
        })
      });
      const response = await res.json();
      const result = response.result;

      // [DEBUG ALERT REMOVED]

      if (result?.error) {
        toast.error(result.error);
        playError();
        setFocus();
        throw new Error(result.error); // Throw to trigger catch in caller
      }
      if (!result?.scanned?.length) {
        toast.warn('Không có dòng nào được cập nhật');
        playError();
        setFocus();
        throw new Error("No lines updated");
      }

      result.scanned.forEach(item => {
        // [FIX] Ưu tiên tìm theo move_id (1 li = 1 stock.move, luôn đúng dòng)
        let el = item.move_id ? document.querySelector(`[data-move-id="${item.move_id}"]`) : null;
        // Fallback: tìm theo line_id
        if (!el) el = document.querySelector(`[data-line-id="${item.line_id}"]`);

        // [FIX] If server returns a line_id that is NOT in the DOM, we must create/update dynamically.
        if (!el && item.barcode) {
          const code = normalizeCode(item.barcode).toUpperCase();
          const candidates = [...document.querySelectorAll('#product_list li.product-item')]
            .filter(e => normalizeCode(e.dataset.barcode).toUpperCase() === code);


          const targetDone = parseFloat(item.done_qty || 0);
          const targetMax = parseFloat(item.required_qty || 0);

          let bestMatch = null;
          let minDiff = Infinity;

          for (const c of candidates) {
            // Priority 0: Exact ID Recovery (Golden Path)
            if (String(c.dataset.lineId) === String(item.line_id)) {
              bestMatch = c;
              break;
            }

            let mMax = parseFloat(c.dataset.maxQty || 0);

            // [FIX] Fallback read from UI if dataset is missing/zero
            if (mMax === 0) {
              const doneInp = c.querySelector('.done-input');
              const reqEl = doneInp ? doneInp.nextElementSibling.nextElementSibling : c.querySelectorAll("span")[1];
              if (reqEl) mMax = parseFloat(reqEl.innerText.replace(',', '.') || 0);
            }

            const mDoneInput = c.querySelector('.done-input');
            const mDone = parseFloat(mDoneInput ? (mDoneInput.value || 0) : (c.querySelector('.done')?.innerText || 0));

            // Heuristic: Minimize Quantity Difference
            // e.g. Item=40 matches Line=40 (Diff=0) better than Line=0 (Diff=40)
            // e.g. Item=1 matches Line=0 (Diff=1) better than Line=10 (Diff=9)
            const diff = Math.abs(mDone - targetDone);

            // console.log(`[DEBUG_HEURISTIC] Candidate ${c.dataset.lineId}: Done=${mDone}, Target=${targetDone}, Diff=${diff}`);

            if (diff < minDiff) {
              minDiff = diff;
              bestMatch = c;
            } else if (diff === minDiff) {
              // Tie-breaker: Match Capacity?
              // If one capacity matches exactly, prefer it.
              if (mMax === targetMax) bestMatch = c;
            }
          }

          let match = bestMatch;

          // Final Fallback (Unlikely to be needed but safe)
          if (!match && candidates.length > 0) {
            match = candidates[candidates.length - 1];
          }

          if (match) {
            // === FORCE UPDATE EXISTING ROW ===
            console.log(`[SCAN] Force updating row ${match.dataset.lineId} -> ${item.line_id}`);
            el = match;

            // Update Identity
            el.setAttribute('data-line-id', item.line_id);
            el.dataset.lineId = String(item.line_id);

            // Update Stats
            el.setAttribute('data-packed-qty', item.packed_qty || 0);
            el.dataset.packedQty = item.packed_qty || 0;

            // Input value will be updated by common logic below
            const input = el.querySelector(".done-input");
            if (input) {
              input.dataset.lineId = String(item.line_id);
            }

            // Visual Feedback
            highlightElement(el, "#dbe4ff");
          } else {
            console.warn("No candidates found to update for", item.barcode);
          }
        }

        if (!el) { console.warn('No DOM line for', item); return; }

        // [FIX] Sync data-line-id to the actual line the backend wrote to
        if (item.line_id && el.dataset.lineId !== String(item.line_id)) {
          el.setAttribute('data-line-id', item.line_id);
          el.dataset.lineId = String(item.line_id);
          const doneInp = el.querySelector('.done-input');
          if (doneInp) doneInp.dataset.lineId = String(item.line_id);
        }

        const requiredEl = el.querySelectorAll('span')[1];
        const required = parseFloat((requiredEl?.innerText || '0').replace(',', '.')) || 0;

        // Check if there is a done input
        const doneInput = el.querySelector('.done-input');

        // If we found the input, update it
        if (doneInput) {
          doneInput.value = item.done_qty;
          doneInput.dataset.currentQty = item.done_qty; // Sync current qty
        } else {
          // Fallback for safety (though we replaced it)
          const doneEl = el.querySelector('.done');
          if (doneEl) doneEl.innerText = item.done_qty;
        }

        if (typeof item.packed_qty !== 'undefined') {
          const srvPacked = parseFloat(item.packed_qty);
          const oldPacked = parseFloat(el.getAttribute('data-packed-qty') || 0);
          if (Math.abs(oldPacked - srvPacked) > 0.001) {
            console.warn(`[AUTO-SYNC] Correcting Packed Qty: ${oldPacked} -> ${srvPacked}`);
            el.setAttribute('data-packed-qty', srvPacked);
          }
        }
        // Force update unpacked label
        updateUnpackedLabel(el);

        if (item.done_qty >= required) el.classList.add("completed");
        else el.classList.remove("completed");

        // Flash highlight to notify user
        highlightElement(el, "#ffd43b"); // Vivid Yellow
      });

    } catch (err) {
      toast.error("Lỗi kết nối: " + err.message);
      playError();
      setFocus();
    }
  }



  completeBtn?.addEventListener("click", async function () {
    // [FIX] Flush active input before completing
    await flushActiveInput();

    const items = document.querySelectorAll("#product_list .product-item");
    let isValid = true, missingProducts = [];
    items.forEach(item => {
      const name = item.querySelector("strong").innerText;

      const input = item.querySelector(".done-input");
      const doneVal = input ? input.value : (item.querySelector(".done")?.innerText || 0);
      const done = parseFloat(doneVal);

      const requiredEl = input ? input.nextElementSibling.nextElementSibling : item.querySelectorAll("span")[1];
      const required = parseFloat(requiredEl?.innerText || 0);

      if (done < required) { isValid = false; missingProducts.push(`${name} (${done}/${required})`); }
    });

    if (!isValid) {
      toast.warn("Chưa quét đủ:\n- " + missingProducts.join("\n- "), { ms: 3500 });
      return;
    }

    // [NEW] Kiểm tra có package không, nếu có thì in nhãn trước
    try {
      const checkRes = await fetch("/pack_scan/check_and_print_label", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { picking_id: pickingId } })
      });
      const checkResponse = await checkRes.json();
      const checkResult = checkResponse.result || checkResponse;

      if (checkResult?.has_package && checkResult?.report_url) {
        toast.info("🖨️ Đang in nhãn...", { ms: 2000 });
        window.open(checkResult.report_url, '_blank');
        // Đợi một chút để người dùng thấy nhãn đang in
        await new Promise(resolve => setTimeout(resolve, 500));
      }
    } catch (e) {
      console.warn("Lỗi kiểm tra package:", e);
      // Tiếp tục hoàn thành ngay cả khi không check được package
    }

    const res = await fetch("/pack_scan/complete_picking", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { picking_id: pickingId } })
    });
    const response = await res.json();
    if (response.error || response.result?.error) {
      const msg = response.error?.message || response.result?.error || "Có lỗi xảy ra!";
      toast.error(msg, { ms: 1800 })

      return;
    }

    // dừng ghi (sẽ tự upload trong onstop)
    await stopRecording();

    toast.success("Phiếu đã hoàn tất! Đang chuyển trang...", { ms: 1200 });
    setTimeout(() => { window.location.href = "/custom_barcode_scan/ui"; }, 600);
  });

  const btnSwitch = document.getElementById('btnDriveSwitch');
  if (btnSwitch) {
    btnSwitch.addEventListener('click', () => {
      // mở tab mới để disconnect + start OAuth
      window.open('/gdrive/oauth2/disconnect', '_blank', 'noopener');
    });
  }

  // Nút Partial Pack - tạo mã barcode tự động (người dùng có thể scan mã này để đóng gói)
  document.getElementById('btnPartialPack')?.addEventListener('click', async function () {
    // [FIX] Flush active input before packing
    await flushActiveInput();

    const autoPackageBarcode = `AUTO-PKG-${Date.now()}`;
    // Put barcode into input (so user can scan it later) and copy to clipboard
    const inputEl = document.getElementById('pack_barcode_input');
    if (inputEl) {
      inputEl.value = autoPackageBarcode;
      inputEl.focus();

      const enterEvent = new KeyboardEvent('keypress', {
        key: 'Enter',
        code: 'Enter',
        keyCode: 13,
        which: 13,
        bubbles: true
      });
      inputEl.dispatchEvent(enterEvent);
    }
    toast.info(`Mã barcode tạo: ${autoPackageBarcode}`, { ms: 1000 });
  });


  input?.addEventListener("keypress", async function (event) {

    // Chỉ xử lý khi nhấn Enter
    if (event.key !== "Enter" && event.keyCode !== 13) return;

    const raw = this.value.trim();
    if (!raw) return;
    this.value = ""; // Clear input ngay sau khi nhận

    // A. Kiểm tra Auto-Complete Picking
    if (typeof originPickName !== 'undefined' && raw === originPickName) {
      completeBtn?.click();
      return;
    }

    // B. Mapping Barcode đặc biệt (nếu có)
    const targetBarcode = BARCODE_MAP_POINT_ONE[raw];
    if (targetBarcode) {
      await updateQty(targetBarcode, 0.1);
      return;
    }

    // Chuẩn hóa barcode
    const barcode = raw;

    if (barcode !== 'CMD-CREATE-PACK' && !barcode.startsWith("AUTO-PKG-") && !barcode.startsWith("PACK")) {

      const foundLine = findLineToUpdate(barcode);

      // Nếu tìm thấy dòng cần update (chưa done), kiểm tra required qty
      if (foundLine) {
        const lineEl = foundLine.moveId
          ? document.querySelector(`[data-move-id="${foundLine.moveId}"]`)
          : document.querySelector(`[data-line-id="${foundLine.lineId}"]`);
        if (lineEl) {
          const required = parseFloat(lineEl.querySelectorAll("span")[1]?.innerText || 0);
          if (required < 10) {
            // Nếu nhập tay (fastKeyCount thấp) -> Chặn
            if (fastKeyCount < 2) {
              toast.warn("Sản phẩm SL < 10: Chỉ được dùng máy quét (không nhập tay)!");
              playError();
              return;
            }
          }
        }
      }
    }
    if (barcode === 'CMD-CREATE-PACK' || barcode.startsWith("AUTO-PKG-") || barcode.startsWith("PACK")) {

      // [Rule] Prevent Double-Submit
      if (isProcessingPack) {
        console.warn("Packing already in progress...");
        return;
      }

      // 1. Thu thập các dòng đã quét (qty > 0) ở danh sách bên trái
      const items = [];
      document.querySelectorAll("#product_list .product-item").forEach(el => {
        const lineId = parseInt(el.dataset.lineId);
        const name = el.querySelector("strong")?.innerText;

        const input = el.querySelector(".done-input");
        const doneVal = input ? input.value : (el.querySelector(".done")?.innerText || 0);
        const currentDone = parseFloat(doneVal);

        const alreadyPacked = parseFloat(el.dataset.packedQty || 0); // Lấy số đã đóng gói từ data attribute

        // Tính số lượng trôi nổi (chưa vào gói)
        const qtyToPack = currentDone - alreadyPacked;

        console.log(`[DEBUG_PACK] ${name} | Line: ${lineId} | Done: ${currentDone} | Packed: ${alreadyPacked} | ToPack: ${qtyToPack}`);

        const barcode = el.dataset.barcode || "";
        // Chỉ lấy nếu còn hàng chưa đóng gói
        if (lineId && qtyToPack > 0) {
          items.push({
            move_line_id: lineId,
            qty: qtyToPack,
            // [FIX] Enrich data for UI rendering
            name: name,
            barcode: barcode
          });
        }
      });

      // 2. Validate: Nếu items rỗng nghĩa là tất cả đã vào gói hết rồi
      if (items.length === 0) {
        toast.warn("Không có sản phẩm nào mới để đóng gói (Tất cả đã nằm trong gói).");
        playError();
        return;
      }

      // 3. Tạo mã gói (nếu là lệnh CMD thì sinh mã tự động, ngược lại dùng mã vừa quét)
      const pkgCode = (barcode === 'CMD-CREATE-PACK') ? `AUTO-PKG-${Date.now()}` : barcode;

      if (barcode === 'CMD-CREATE-PACK') {
        toast.info(`Đang tạo gói hàng tự động...`, { ms: 1000 });
      }

      isProcessingPack = true; // Lock
      try {
        // 4. Gọi API tạo Partial Pack
        const res = await fetch('/pack_scan/create_partial_pack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          body: JSON.stringify({
            jsonrpc: '2.0',
            method: 'call',
            params: {
              picking_id: pickingId,
              package_barcode: pkgCode,
              move_line_data: items // list [{move_line_id, qty}]
            }
          })
        });

        const response = await res.json();
        const result = response.result || response;

        if (result?.package_id) {
          toast.success(`Tạo gói hàng ${result.package_name} thành công!`);
          // 1. Luôn hiển thị gói mới bên phải
          const pkgId = result.package_id;
          const pkgName = result.package_name;
          renderNewPackageToPanel(pkgId, pkgName, items);

          // 2. Cập nhật thông tin "Đã đóng gói" (Sync vs Optimistic)
          if (result.sync_info && result.sync_info.length > 0) {
            console.log("[PACK UI] Using Server Sync Info");
            applyServerSyncInfo(result.sync_info);
          } else {
            console.warn("[PACK UI] No Sync Info from Server -> Using Optimistic Update");
            // Fallback: Tự cộng dồn data-packed-qty từ danh sách items vừa gửi đi
            if (items && items.length > 0) {
              items.forEach(item => {
                const lineId = item.move_line_id;
                const qty = parseFloat(item.qty || 0);
                let el = document.querySelector(`#product_list .product-item[data-line-id="${lineId}"]`);

                // Fallback finding logic (borrowed from findLineToUpdate)
                if (!el && item.barcode) {
                  const code = normalizeCode(item.barcode).toUpperCase();
                  el = document.querySelector(`#product_list .product-item[data-barcode="${CSS.escape(code)}"]`) ||
                    document.querySelector(`#product_list .product-item[data-barcode="${code}"]`);
                }

                if (el) {
                  const oldPacked = parseFloat(el.getAttribute('data-packed-qty') || 0);
                  const newPacked = oldPacked + qty;
                  el.setAttribute('data-packed-qty', newPacked);

                  // Visual flash
                  highlightElement(el, "#dbe4ff");

                  // IMPORTANT: Update label
                  updateUnpackedLabel(el);
                }
              });
            }
          }
        } else {
          toast.error(result?.error || "Lỗi tạo gói hàng");
          playError();
        }
      } catch (e) {
        toast.error("Lỗi kết nối: " + e.message);
        playError();
      } finally {
        isProcessingPack = false; // Unlock
      }
      return;
    }

    // D. Logic quét sản phẩm thông thường (Cộng dồn số lượng)
    await updateQty(barcode);
  });
  // Nút In nhãn
  document.getElementById('btnPrintLabel')?.addEventListener('click', async function () {
    const res = await fetch('/pack_scan/print_label', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'call',
        params: { picking_id: pickingId }
      })
    });
    const response = await res.json();
    const result = response.result || response;
    if (result?.success) {
      toast.success(result.message, { ms: 1500 });
      window.open(result.report_url, '_blank');
    } else {
      toast.error(result?.error || 'Không thể in nhãn', { ms: 2000 });
    }
  });
  // Nút In nhãn 80x80
  document.getElementById('btnPrintLabel80x80')?.addEventListener('click', async function () {
    const res = await fetch('/pack_scan/print_label_80x80', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'call',
        params: { picking_id: pickingId }
      })
    });
    const response = await res.json();
    const result = response.result || response;
    if (result?.success) {
      toast.success(result.message, { ms: 1500 });
      window.open(result.report_url, '_blank');
    } else {
      toast.error(result?.error || 'Không thể in nhãn 80x80', { ms: 2000 });
    }
  });

  setFocus();
  diag();
  setTimeout(optimizePackageUI, 100); // Delay nhẹ 100ms để đảm bảo DOM đã render xong
  // [FIX] Khởi tạo label "Chưa đóng gói" cho tất cả items khi load trang
  setTimeout(() => {
    document.querySelectorAll('#product_list .product-item').forEach(el => updateUnpackedLabel(el));
  }, 150);
  setTimeout(startRecording, 400);
});

// ====== Upload Session Management ======
let uploadId = null;
let chunkIndex = 0;
let finishing = false;

async function startServerUploadSession() {
  const resp = await fetch('/pack_scan/start_upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    body: JSON.stringify({ picking_id: pickingId, ext: 'webm', mimetype: 'video/webm' })
  }).then(r => r.json());
  const r = resp.result || resp;
  if (!r || !r.upload_id) throw new Error('Không khởi tạo phiên upload được');
  uploadId = r.upload_id;
  chunkIndex = 0;
  finishing = false;
}

async function sendChunk(blob) {
  if (!uploadId || !blob || !blob.size) return;
  const idx = chunkIndex++;
  const fd = new FormData();
  fd.append('upload_id', uploadId);
  fd.append('index', String(idx));
  fd.append('chunk', blob, `part_${idx}.webm`);
  await fetch('/pack_scan/upload_chunk', { method: 'POST', body: fd, credentials: 'same-origin' });
}

async function finishServerUploadSession() {
  if (finishing) return;
  finishing = true;

  try { await chunkBusy; } catch { }
  if (!uploadId) return;

  try {
    await fetch('/pack_scan/finish_upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      keepalive: true,
      body: JSON.stringify({ upload_id: uploadId, picking_id: pickingId })
    });
  } finally {
    uploadId = null;
  }
}

// ============================================================
// [HELPER] AUTORITATIVE SYNC WITH SERVER
// ============================================================
function applyServerSyncInfo(syncInfoList) {
  if (!Array.isArray(syncInfoList)) return;
  console.log("[UI SYNC] Applying Server Sync Info...", syncInfoList);

  syncInfoList.forEach(info => {
    let targetEl = null;

    // [FIX] Prioritize lookup by Line ID if available in sync info
    if (info.line_id) {
      targetEl = document.querySelector(`[data-line-id="${info.line_id}"]`);
    }

    // Only use fuzzy matching if no line_id or line_id not found (and fallback needed? Prefer strict)
    if (!targetEl) {
      const allItems = document.querySelectorAll('#product_list .product-item');
      for (const item of allItems) {
        const itemBar = normalizeCode(item.dataset.barcode || '').toUpperCase();
        const itemSku = normalizeCode(item.dataset.defaultCode || '').toUpperCase();
        const sBarcode = normalizeCode(info.product_barcode || '').toUpperCase();
        const sSku = normalizeCode(info.product_sku || '').toUpperCase();

        // Match by Barcode (Fuzzy: endsWith)
        if (sBarcode && (itemBar === sBarcode || itemBar.endsWith(sBarcode) || sBarcode.endsWith(itemBar))) {
          targetEl = item;
          break;
        }
        // Match by SKU (Fuzzy: endsWith)
        if (!targetEl && sSku && (itemSku === sSku || itemSku.endsWith(sSku) || sSku.endsWith(itemSku))) {
          targetEl = item;
          break;
        }
      }
    }

    // 3. Update nếu tìm thấy
    if (targetEl) {
      const oldPacked = parseFloat(targetEl.getAttribute('data-packed-qty') || 0);
      const serverPacked = parseFloat(info.packed_qty || 0);

      if (Math.abs(oldPacked - serverPacked) > 0.001) {
        console.warn(`[UI SYNC] Correction for ${info.product_sku}: Client(${oldPacked}) -> Server(${serverPacked})`);
        targetEl.setAttribute('data-packed-qty', serverPacked);

        // Hiệu ứng visual báo hiệu update
        highlightElement(targetEl, "#dbe4ff"); // Xanh dương nhạt
      }

      // Luôn update label unpacked để đảm bảo nhất quán
      updateUnpackedLabel(targetEl);
    }
  });
}

function updateUnpackedLabel(el) {
  if (!el) return;
  const packedQty = parseFloat(el.getAttribute('data-packed-qty') || 0);
  const input = el.querySelector(".done-input");
  const currentDone = parseFloat(input ? input.value : (el.querySelector(".done")?.innerText || 0));

  const unpackedQty = currentDone - packedQty;
  let unpackedEl = el.querySelector('.unpacked-info');

  if (unpackedQty > 0.001) {
    if (!unpackedEl) {
      const newInfo = document.createElement('div');
      newInfo.className = 'unpacked-info';
      newInfo.style.cssText = "font-size: 0.8rem; color: #d97706; margin-top: 4px; font-style: italic;";
      const container = el.querySelector('div') || el;
      container.appendChild(newInfo);
      unpackedEl = newInfo;
    }
    unpackedEl.innerText = `⚠️ Chưa đóng gói: ${unpackedQty}`;
  } else {
    if (unpackedEl) unpackedEl.remove();
  }
}

// ====== Recording Module ======
let mediaStream = null;
let mediaRecorder = null;
let isRecording = false;
let chunkBusy = Promise.resolve();

const MAX_DURATION_MS = 25 * 60 * 1000; // 5 phút
let stopTimer = null, countdownTimer = null, endAt = 0;
let overlayCanvas = null, overlayCtx = null, drawRAF = 0;

function updateCountdownLabel() {
  const el = document.getElementById('recCountdown');
  if (!el || !endAt) return;
  const left = Math.max(0, endAt - Date.now());
  const mm = String(Math.floor(left / 60000)).padStart(2, '0');
  const ss = String(Math.floor((left % 60000) / 1000)).padStart(2, '0');
  el.textContent = `${mm}:${ss}`;
}

async function startRecording() {
  const statusDot = document.getElementById('recStatus');
  const statusText = document.getElementById('recText');
  const preview = document.getElementById('recPreview');
  if (!statusText || !preview) return;

  const constraints = {
    video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 24, max: 24 } },
    audio: { echoCancellation: true, noiseSuppression: true }
  };
  try {
    try { mediaStream = await navigator.mediaDevices.getUserMedia(constraints); }
    catch { mediaStream = await navigator.mediaDevices.getUserMedia({ video: constraints.video, audio: false }); }
  } catch (e) {
    statusText.textContent = 'Không thể mở camera.';
    console.error('[REC] getUserMedia failed:', e);
    return;
  }

  const vTrack = mediaStream.getVideoTracks()[0];
  const s = vTrack.getSettings ? vTrack.getSettings() : {};
  const W = s.width || 1280, H = s.height || 720;

  overlayCanvas = document.createElement('canvas');
  overlayCanvas.width = W; overlayCanvas.height = H;
  overlayCtx = overlayCanvas.getContext('2d');

  const rawVideo = document.createElement('video');
  rawVideo.srcObject = new MediaStream([vTrack]);
  rawVideo.muted = true;
  rawVideo.playsInline = true;
  rawVideo.autoplay = true;
  try { await rawVideo.play(); } catch { }

  endAt = Date.now() + MAX_DURATION_MS;
  updateCountdownLabel();
  clearInterval(countdownTimer);
  countdownTimer = setInterval(updateCountdownLabel, 500);

  function drawOverlay() {
    if (!overlayCtx) return;
    overlayCtx.drawImage(rawVideo, 0, 0, W, H);
    overlayCtx.fillStyle = 'rgba(0,0,0,0.5)';
    overlayCtx.fillRect(0, H - 52, W, 52);

    const left = Math.max(0, endAt - Date.now());
    const mm = String(Math.floor(left / 60000)).padStart(2, '0');
    const ss = String(Math.floor((left % 60000) / 1000)).padStart(2, '0');

    overlayCtx.fillStyle = '#fff';
    overlayCtx.font = 'bold 24px Segoe UI, Arial';
    overlayCtx.fillText(`Time: ${new Date().toLocaleString()} `, 16, H - 16);

    drawRAF = requestAnimationFrame(drawOverlay);
  }
  drawOverlay();

  const canvasStream = overlayCanvas.captureStream(24);
  const tracks = [canvasStream.getVideoTracks()[0]];
  const a = mediaStream.getAudioTracks()[0];
  if (a) tracks.push(a);
  const mixedStream = new MediaStream(tracks);

  preview.srcObject = mixedStream;
  try { await preview.play(); } catch { }

  await startServerUploadSession();

  let mimeType = '';
  if (MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')) mimeType = 'video/webm;codecs=vp9,opus';
  else if (MediaRecorder.isTypeSupported('video/webm;codecs=vp8,opus')) mimeType = 'video/webm;codecs=vp8,opus';
  else if (MediaRecorder.isTypeSupported('video/webm')) mimeType = 'video/webm';
  const mrOpts = mimeType ? { mimeType, videoBitsPerSecond: 1_200_000, audioBitsPerSecond: 64_000 } : {};

  mediaRecorder = new MediaRecorder(mixedStream, mrOpts);
  mediaRecorder.ondataavailable = (e) => {
    if (!e.data || !e.data.size) return;
    chunkBusy = chunkBusy.then(() => sendChunk(e.data)).catch(() => { });
  };
  mediaRecorder.onstart = () => {
    isRecording = true;
    statusText.textContent = 'Đang ghi hình...';
    statusDot && statusDot.classList.add('on');
    stopTimer = setTimeout(() => stopRecording(), MAX_DURATION_MS);
  };
  mediaRecorder.onstop = async () => {
    isRecording = false;
    try { clearTimeout(stopTimer); } catch { }
    try { clearInterval(countdownTimer); } catch { }
    countdownTimer = null;

    statusText.textContent = 'Đang hoàn tất upload...';
    try { await chunkBusy; } catch { }
    await finishServerUploadSession();

    statusText.textContent = 'Đã gửi video lên server để xử lý.';
    statusDot && statusDot.classList.remove('on');

    if (drawRAF) cancelAnimationFrame(drawRAF);
    drawRAF = 0; overlayCtx = null; overlayCanvas = null;

    if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
  };

  try {
    mediaRecorder.start(5000);
  } catch (err) {
    console.error('[REC] mediaRecorder.start failed:', err);
    statusText.textContent = 'Không thể bắt đầu ghi hình.';
  }
}

function stopRecording() {
  if (mediaRecorder && isRecording) { try { mediaRecorder.stop(); } catch { } }
}

async function diag() {
  const statusText = document.getElementById('recText');
  const ua = navigator.userAgent;
  const secure = window.isSecureContext ? 'HTTPS' : 'NOT-HTTPS';
  let cams = 'unknown';
  try {
    const devs = await navigator.mediaDevices.enumerateDevices();
    cams = devs.filter(d => d.kind === 'videoinput').length + ' camera(s)';
  } catch { }
  console.log('[REC] DIAG =>', { secure, ua, cams });
  statusText && (statusText.title = `Diag: ${secure} | ${cams}`);
}

window.addEventListener('beforeunload', () => { try { mediaRecorder && mediaRecorder.stop(); } catch { } });

// ===================== UTILITIES =====================
function createModal(title, content, buttons = []) {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.style.cssText = `
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center;
    z-index: 10000;
  `;

  const modalContent = document.createElement('div');
  modalContent.style.cssText = `
    background: #fff; border-radius: 12px; padding: 20px; max-width: 600px;
    width: 90%; max-height: 80vh; overflow-y: auto; box-shadow: 0 10px 40px rgba(0,0,0,0.2);
  `;

  const titleEl = document.createElement('h2');
  titleEl.textContent = title;
  titleEl.style.margin = '0 0 16px 0';
  modalContent.appendChild(titleEl);

  if (typeof content === 'string') {
    const contentDiv = document.createElement('div');
    contentDiv.innerHTML = content;
    modalContent.appendChild(contentDiv);
  } else {
    modalContent.appendChild(content);
  }

  const buttonContainer = document.createElement('div');
  buttonContainer.style.cssText = 'display: flex; gap: 10px; margin-top: 20px; justify-content: flex-end;';

  buttons.forEach(btn => {
    const button = document.createElement('button');
    button.textContent = btn.label;
    button.style.cssText = `
      padding: 10px 16px; border: none; border-radius: 8px;
      cursor: pointer; font-size: 14px; font-weight: 600;
      background: ${btn.color || '#3b82f6'}; color: #fff;
    `;
    button.addEventListener('click', () => {
      btn.onclick();
      modal.remove();
    });
    buttonContainer.appendChild(button);
  });

  modalContent.appendChild(buttonContainer);
  modal.appendChild(modalContent);

  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.remove();
  });

  document.body.appendChild(modal);
  return modal;
}
// ============================================================
// HÀM DỌN DẸP UI KHI VỪA F5 (GỘP DÒNG & FORMAT TÊN)

function optimizePackageUI() {
  const packageCards = document.querySelectorAll('.package-item-card');
  const allMainItems = document.querySelectorAll('#product_list .product-item');

  packageCards.forEach(card => {
    const previewContainer = card.querySelector('.package-items-preview');
    if (!previewContainer) return;

    const items = previewContainer.querySelectorAll('.preview-item');
    const aggregated = {};

    items.forEach(item => {
      // Lấy tên gốc và làm sạch
      let originalName = item.querySelector('.preview-item-name').innerText.trim();
      let compareName = originalName.toLowerCase();

      let qtyText = item.querySelector('.preview-item-qty').innerText.toLowerCase().replace('x', '');
      let qty = parseFloat(qtyText) || 0;

      if (qty <= 0) {
        item.remove();
        return;
      }

      // --- LOGIC TÌM MÃ (SỬA ĐỂ ƯU TIÊN DEFAULT CODE) ---
      let finalName = originalName;

      // Nếu tên chưa có [...], đi tìm mã
      if (!originalName.startsWith('[')) {
        for (let mainItem of allMainItems) {
          const mainRawText = mainItem.querySelector('strong')?.innerText || '';
          const mainCompare = mainRawText.toLowerCase().trim();

          // So sánh tương đối
          if (mainCompare.includes(compareName) || compareName.includes(mainCompare)) {

            // 👇 SỬA Ở ĐÂY: Lấy data-default-code trước
            const code = mainItem.getAttribute('data-default-code') || mainItem.getAttribute('data-barcode');

            if (code) {
              finalName = `[${code}] ${originalName}`;
            } else {
              // Fallback: Nếu không có attribute, lấy luôn text gốc bên trái nếu nó có dạng [Mã]
              if (mainRawText.trim().startsWith('[')) {
                finalName = mainRawText.trim();
              }
            }
            break;
          }
        }
      }

      // Gom nhóm
      if (aggregated[finalName]) {
        aggregated[finalName].qty += qty;
        aggregated[finalName].elementsToRemove.push(item);
      } else {
        aggregated[finalName] = {
          qty: qty,
          mainElement: item,
          elementsToRemove: []
        };
      }
    });

    // Render lại DOM
    for (const [name, data] of Object.entries(aggregated)) {
      data.elementsToRemove.forEach(el => el.remove());

      const mainEl = data.mainElement;
      const nameEl = mainEl.querySelector('.preview-item-name');
      const qtyEl = mainEl.querySelector('.preview-item-qty');

      if (nameEl) {
        nameEl.innerText = name;
        nameEl.style.color = "#495057";
        nameEl.style.fontSize = "0.85rem";
      }

      if (qtyEl) {
        qtyEl.innerText = `x${data.qty}`;
        qtyEl.style.cssText = "font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;";
      }

      mainEl.style.display = 'flex';
      mainEl.style.justifyContent = 'space-between';
      mainEl.style.marginBottom = '0.35rem';
      mainEl.style.alignItems = 'center';
    }
  });
}
// ===================== SIBLING PACK ACTIONS (COMMENTED OUT SPLIT FUNCTIONALITY) =====================
document.addEventListener('click', async function (e) {
  const unpackBtn = e.target.closest('.btn-unpack');
  const editBtn = e.target.closest('.btn-edit');
  // COMMENTED OUT: Transfer button for splitting package into separate picking
  // const transferBtn = e.target.closest('.btn-transfer');

  if (unpackBtn) {
    const packId = parseInt(unpackBtn.dataset.packId);
    if (confirm('Bạn chắc chắn muốn unpack kiện này?')) {
      const res = await fetch('/pack_scan/unpack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({
          jsonrpc: '2.0',
          method: 'call',
          params: { picking_id: packId }
        })
      });
      const response = await res.json();
      const result = response.result || response;

      if (result?.success) {
        toast.success(result.message, { ms: 2000 });
        const card = document.querySelector(`.package-item-card[data-package-id="${packId}"]`);
        if (card) {
          card.style.transition = 'all 0.3s ease';
          card.style.opacity = '0';
          card.style.transform = 'translateX(20px)';
          setTimeout(() => card.remove(), 300);
        }
      } else {
        toast.error(result?.error || 'Unpack thất bại', { ms: 2000 });
      }
    }
  }

  if (editBtn) {
    const packId = parseInt(editBtn.dataset.packId);
    window.location.href = `/custom_barcode_scan/pack_view/${packId}`;
  }

});

// ===================== PACKAGE EDIT MODAL FUNCTIONS =====================
let currentPackageData = null;





async function openPackageEditModal(event) {
  event.stopPropagation();

  const packageId = event.currentTarget.dataset.packageId;
  const pickingId = parseInt(window.location.pathname.split("/").pop());

  try {
    const res = await fetch("/pack_scan/get_package_details", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: { picking_id: pickingId, package_id: parseInt(packageId) }
      })
    });

    const response = await res.json();
    const result = response.result || response;

    if (result?.error) {
      toast.error("❌ " + result.error);
      return;
    }

    currentPackageData = result;
    updateSidePanelUI(currentPackageData);

    // [NEW] SELF-HEALING: Đồng bộ lại data-packed-qty từ Server về Client
    if (result.sync_info && Array.isArray(result.sync_info)) {
      console.log("[UI SYNC] Starting Self-Healing with server data...", result.sync_info);
      result.sync_info.forEach(info => {
        let targetEl = null;

        // 1. Tìm theo Barcode (Robust)
        if (info.product_barcode) {
          const normCode = normalizeCode(info.product_barcode);
          targetEl = [...document.querySelectorAll('#product_list .product-item')]
            .find(el => normalizeCode(el.dataset.barcode) === normCode);
        }

        // 2. Fallback: Tìm theo SKU
        if (!targetEl && info.product_sku) {
          // SKU usually matches exactly, but let's be safe
          targetEl = document.querySelector(`#product_list .product-item[data-default-code="${info.product_sku}"]`);
        }

        // 3. Update nếu tìm thấy
        if (targetEl) {
          const oldPacked = parseFloat(targetEl.getAttribute('data-packed-qty') || 0);
          const serverPacked = parseFloat(info.packed_qty || 0);

          if (Math.abs(oldPacked - serverPacked) > 0.001) {
            console.warn(`[UI SYNC] Correction for ${info.product_sku || info.product_barcode}: Client(${oldPacked}) -> Server(${serverPacked})`);
            targetEl.setAttribute('data-packed-qty', serverPacked);
            // [FIX] Update visual label immediately
            if (typeof updateUnpackedLabel === 'function') {
              updateUnpackedLabel(targetEl);
            }
          }
        }
      });
    }

    if (!Array.isArray(currentPackageData.other_packages)) {
      currentPackageData.other_packages = [];
    }
    const titleEl = document.getElementById('modalPackageName');
    if (titleEl) titleEl.innerText = result.package_name;

    const mergedItems = result.items || [];

    const uniqueProducts = new Set(mergedItems.map(i => i.product_id));
    const badgeEl = document.getElementById('itemCountBadge');
    if (badgeEl) badgeEl.innerText = uniqueProducts.size;


    const itemsList = document.getElementById('packageItemsList');
    if (itemsList) {
      itemsList.innerHTML = ''; // Xóa list cũ

      if (mergedItems.length === 0) {
        itemsList.innerHTML = `
          <div class="empty-state">
            <div class="empty-icon">📦</div>
            <h4 class="empty-title">Chưa có sản phẩm nào</h4>
            <p class="empty-desc">Thêm sản phẩm để quản lý gói hàng</p>
          </div>
        `;
      } else {
        mergedItems.forEach(item => {
          const li = document.createElement('div');
          li.className = 'item-card';
          li.setAttribute('data-move-line-id', item.move_line_id);

          let displayName = item.product_name;
          if (item.product_barcode && !displayName.startsWith('[')) {
            displayName = `[${item.product_barcode}] ${displayName}`;
          }

          li.innerHTML = `
            <div class="item-info">
              <div class="item-details">
                <h4 class="item-name">${displayName}</h4>
                <span class="item-sku">${item.product_sku || 'N/A'}</span>
              </div>
            </div>
            <div class="item-qty-control">
              <button class="qty-btn qty-decrease" data-move-line-id="${item.move_line_id}">−</button>
              <div class="qty-display" data-move-line-id="${item.move_line_id}" data-old-qty="${item.qty_done}">${item.qty_done}</div>
              <button class="qty-btn qty-increase" data-move-line-id="${item.move_line_id}">+</button>
            </div>
            <div class="item-actions">
              <button class="action-btn action-transfer" data-move-line-id="${item.move_line_id}" title="Chuyển sản phẩm">Chuyển</button>
            </div>
          `;

          // 1. Decrease
          console.log(`[DEBUG_RENDER] Item: ${item.product_name} | ID: ${item.move_line_id} | Qty: ${item.qty_done}`);

          li.querySelector('.qty-decrease').addEventListener('click', () => {
            const display = li.querySelector('.qty-display');
            let cur = parseFloat(display.innerText) || 0;
            const newQty = Math.max(0, cur - 1);
            display.innerText = String(newQty);
            // Cập nhật biến tạm (lưu ý: cập nhật vào item gộp này)
            item.qty_done = newQty;
          });

          // 2. Increase
          li.querySelector('.qty-increase').addEventListener('click', () => {
            const display = li.querySelector('.qty-display');
            const cur = parseFloat(display.innerText) || 0;

            // Logic check max available (tính tổng toàn bộ items gốc của server)
            const allProductItems = currentPackageData.all_items || [];
            const availableItems = allProductItems.filter(i => i.product_name === item.product_name);
            let totalAvailable = 0;
            availableItems.forEach(ai => { totalAvailable += ai.qty_available || 0; });

            // Tính tổng đã đóng gói (từ danh sách gốc server, không phải danh sách gộp UI)
            const currentPackageItems = currentPackageData.items || [];
            let totalInPackages = 0;
            currentPackageItems.forEach(ci => {
              if (ci.product_name === item.product_name) {
                totalInPackages += parseFloat(ci.qty_done) || 0;
              }
            });

            const oldQtyStored = parseFloat(display.dataset.oldQty) || 0;
            const currentTotalForProduct = totalInPackages + (cur - oldQtyStored);

            if (currentTotalForProduct >= totalAvailable) {
              toast.warn(`Đã đạt giới hạn tối đa (${totalAvailable})`);
              return;
            }

            const newQty = cur + 1;
            display.innerText = String(newQty);
            item.qty_done = newQty;
          });



          // 4. Transfer
          li.querySelector('.action-transfer').addEventListener('click', (ev) => {
            ev.stopPropagation();
            const display = li.querySelector('.qty-display');
            const currentQty = parseFloat(display.innerText) || item.qty_done;
            openTransferModalForItem(item.move_line_id, currentQty, item.product_name);
          });

          itemsList.appendChild(li);
        });
      }
    }

    // Populate add item select
    const addItemSelect = document.getElementById('addItemSelect');
    if (addItemSelect) {
      addItemSelect.innerHTML = '<option value="">-- Chọn sản phẩm --</option>';
      if (result.all_items && result.all_items.length > 0) {
        result.all_items.forEach(item => {
          // Thêm [Barcode] vào dropdown cho dễ tìm
          let label = item.product_name;

          const code = item.product_sku || item.product_barcode || '';
          if (code && !label.startsWith('[')) {
            label = `[${code}] ${label}`;
          }
          const option = document.createElement('option');
          option.value = item.move_line_id;
          option.innerText = `${label} (Còn: ${item.qty_available})`;
          addItemSelect.appendChild(option);
        });
      }
    }

    // Show modal
    const modal = document.getElementById('packageEditModal');
    if (modal) {
      modal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
    }

  } catch (err) {
    toast.error("❌ Lỗi kết nối: " + err.message);
  }
}
function closePackageEditModal() {
  const modal = document.getElementById('packageEditModal');
  modal.style.display = 'none';
  document.body.style.overflow = 'auto';
  currentPackageData = null;
}
async function removePackageItem(moveLineId) {
  const pickingId = parseInt(window.location.pathname.split("/").pop());
  const strLineId = String(moveLineId);

  // 1. Lấy số lượng sắp xóa từ Modal
  const itemInModal = document.querySelector(`.qty-display[data-move-line-id="${strLineId}"]`);
  const qtyToRemove = itemInModal ? parseFloat(itemInModal.innerText) : 0;

  try {
    const res = await fetch("/pack_scan/remove_package_item", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: {
          picking_id: pickingId,
          package_id: currentPackageData.package_id,
          move_line_id: moveLineId
        }
      })
    });

    const response = await res.json();
    const result = response.result || response;

    if (result?.error) {
      toast.error(result.error);
      return;
    }

    toast.success("Đã xoá sản phẩm khỏi gói!", { ms: 1000 });

    // [FIX QUAN TRỌNG] Cập nhật giao diện danh sách chính
    if (qtyToRemove > 0) {
      // Bước A: Cố tìm theo ID dòng (Trường hợp ID không đổi)
      let mainListEl = document.querySelector(`#product_list .product-item[data-line-id="${strLineId}"]`);

      // Bước B: Nếu không tìm thấy theo ID (do Odoo đã tách dòng làm đổi ID), tìm theo Tên Sản Phẩm
      if (!mainListEl && currentPackageData?.items) {
        // Lấy thông tin tên sản phẩm từ dữ liệu gói hiện tại
        const itemDetail = currentPackageData.items.find(i => String(i.move_line_id) === strLineId);

        if (itemDetail) {
          const allItems = document.querySelectorAll('#product_list .product-item');
          for (const el of allItems) {
            // So sánh tên sản phẩm: Tìm dòng nào chứa tên sản phẩm vừa xóa
            // (Dùng includes vì tên hiển thị có thể chứa cả mã [SKU])
            const prodNameEl = el.querySelector('strong');
            if (prodNameEl && prodNameEl.innerText.includes(itemDetail.product_name)) {
              mainListEl = el;
              break; // Đã tìm thấy đúng dòng sản phẩm bên trái
            }
          }
        }
      }

      // Bước C: Thực hiện cập nhật số liệu nếu tìm thấy dòng tương ứng
      if (mainListEl) {
        const doneInput = mainListEl.querySelector('.done-input');
        const doneEl = mainListEl.querySelector('.done');

        const currentDone = parseFloat(doneInput ? doneInput.value : (doneEl?.innerText || 0));

        const newDone = currentDone; // Keep done count same




        const currentPacked = parseFloat(mainListEl.getAttribute('data-packed-qty') || 0);
        const newPacked = Math.max(0, currentPacked - qtyToRemove);
        mainListEl.setAttribute('data-packed-qty', newPacked);


        const requiredEl = mainListEl.querySelectorAll('span')[1];
        const required = parseFloat(requiredEl?.innerText || 0);
        if (newDone >= required && required > 0) {
          mainListEl.classList.add("completed");
        } else {
          mainListEl.classList.remove("completed");
        }

        highlightElement(mainListEl, "#ffc9c9"); // Reddish for removal
      }
    }
    if (currentPackageData && currentPackageData.package_id) {
      openPackageEditModal({ currentTarget: { dataset: { packageId: currentPackageData.package_id } }, stopPropagation: () => { } });
    }

  } catch (err) {
    toast.error("Lỗi kết nối: " + err.message);
  }
}

async function addItemToPackage() {
  const pickingId = parseInt(window.location.pathname.split("/").pop());
  const moveLineId = parseInt(document.getElementById('addItemSelect').value);
  const qty = parseFloat(document.getElementById('addItemQty').value);

  if (!moveLineId || qty <= 0) {
    toast.warn("Vui lòng chọn sản phẩm và nhập số lượng");
    return;
  }

  try {
    const res = await fetch("/pack_scan/add_item_to_package", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: {
          picking_id: pickingId,
          package_id: currentPackageData.package_id,
          move_line_id: moveLineId,
          qty: qty
        }
      })
    });

    const response = await res.json();
    const result = response.result || response;

    if (result?.error) {
      toast.error(result.error);
      return;
    }

    toast.success(result.message, { ms: 1500 });
    document.getElementById('addItemSelect').value = '';
    document.getElementById('addItemQty').value = '1';
    openPackageEditModal({ currentTarget: { dataset: { packageId: currentPackageData.package_id } }, stopPropagation: () => { } });

  } catch (err) {
    toast.error("Lỗi kết nối: " + err.message);
  }
}
window.addItemToPackage = addItemToPackage;

async function savePackageChanges() {
  const pickingId = parseInt(window.location.pathname.split("/").pop());
  const displayElements = document.querySelectorAll('.qty-display');

  let hasChanges = false;
  const changes = [];

  // 1. Thu thập các thay đổi từ giao diện Modal
  for (let display of displayElements) {
    const moveLineId = parseInt(display.dataset.moveLineId);
    const newQty = parseFloat(display.innerText);
    const oldQty = parseFloat(display.dataset.oldQty); // Số lượng lúc mới mở modal

    if (!isNaN(newQty) && !isNaN(oldQty) && newQty !== oldQty) {
      hasChanges = true;
      changes.push({ moveLineId, newQty, oldQty });
    }
  }

  if (!hasChanges) {
    toast.info("Không có thay đổi nào");
    closePackageEditModal();
    return;
  }

  // 2. Gửi API cập nhật từng dòng
  for (let change of changes) {
    try {
      const res = await fetch("/pack_scan/update_package_item_qty", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "call",
          params: {
            picking_id: pickingId,
            package_id: currentPackageData.package_id,
            move_line_id: change.moveLineId,
            new_qty: change.newQty
          }
        })
      });

      const response = await res.json();
      const result = response.result || response;

      if (result?.error) {
        toast.error(result.error);
        return;
      }

      // [FIX UI] CẬP NHẬT GIAO DIỆN CHÍNH (DONE & PACKED)
      const delta = change.newQty - change.oldQty;
      const strLineId = String(change.moveLineId);

      console.log(`[UI SYNC] ID=${strLineId} Delta=${delta}. Looking for DOM...`);

      // A. Tìm dòng ở màn hình chính theo ID
      let mainListEl = document.querySelector(`#product_list .product-item[data-line-id="${strLineId}"]`);
      if (mainListEl) console.log(`[UI SYNC] Found by ID`);

      // B. Nếu không tìm thấy theo ID (do Odoo tách dòng), tìm theo Barcode/SKU/Tên
      if (!mainListEl && currentPackageData?.items) {
        const itemDetail = currentPackageData.items.find(i => String(i.move_line_id) === strLineId);
        if (itemDetail) {
          console.log(`[UI SYNC] Fallback search for`, itemDetail);
          // 1. Tìm theo Barcode
          if (itemDetail.product_barcode) {
            mainListEl = document.querySelector(`#product_list .product-item[data-barcode="${itemDetail.product_barcode}"]`);
            if (mainListEl) console.log(`[UI SYNC] Found by Barcode`);
          }
          // 2. Tìm theo SKU (Default Code)
          if (!mainListEl && itemDetail.product_sku) {
            mainListEl = document.querySelector(`#product_list .product-item[data-default-code="${itemDetail.product_sku}"]`);
            if (mainListEl) console.log(`[UI SYNC] Found by SKU`);
          }
          // 3. Tìm theo Tên (Fallback cuối cùng)
          if (!mainListEl) {
            const allItems = document.querySelectorAll('#product_list .product-item');
            for (const el of allItems) {
              const nameEl = el.querySelector('strong');
              if (nameEl && nameEl.innerText.includes(itemDetail.product_name)) {
                mainListEl = el;
                console.log(`[UI SYNC] Found by Name`);
                break;
              }
            }
          }
        }
      }

      // C. Thực hiện cập nhật số liệu
      if (mainListEl) {
        // 1. Cập nhật số lượng hiển thị (Done)
        // Delta dương = cộng thêm, Delta âm = trừ đi
        // 1. Cập nhật số lượng hiển thị (Done)
        // Delta dương = cộng thêm, Delta âm = trừ đi
        const doneInput = mainListEl.querySelector('.done-input');
        const doneEl = mainListEl.querySelector('.done');

        const currentDone = parseFloat(doneInput ? doneInput.value : (doneEl?.innerText || 0));

        // LOGIC MỚI: Nếu delta < 0 (Unpack), giữ nguyên Done (vì nó chuyển ra ngoài).
        // Nếu delta > 0 (Thêm vào pack), tăng Done (giả sử là scan thêm).
        const newDone = delta < 0 ? currentDone : Math.max(0, currentDone + delta);

        if (doneInput) {
          doneInput.value = newDone;
          doneInput.dataset.currentQty = newDone; // Sync for safety
        } else if (doneEl) {
          doneEl.innerText = newDone;
        }

        // 2. Cập nhật số lượng đã đóng gói ngầm (Packed Qty)
        // Phải cập nhật cái này để lần sau quét thêm nó tính toán đúng
        const currentPacked = parseFloat(mainListEl.getAttribute('data-packed-qty') || 0);
        const newPacked = Math.max(0, currentPacked + delta);

        mainListEl.setAttribute('data-packed-qty', newPacked);

        // --- DEBUG LOGS ---
        console.log(`[UI SYNC] Update Stats:`, {
          lineId: strLineId,
          currentDone,
          delta,
          newDone,
          currentPacked,
          newPacked,
          unpackedQtyCalculation: newDone - newPacked
        });
        // ------------------

        // 3. Check lại trạng thái completed (Màu xanh)
        const requiredEl = mainListEl.querySelectorAll('span')[1];
        const required = parseFloat(requiredEl?.innerText || 0);

        if (newDone >= required && required > 0) mainListEl.classList.add("completed");
        else mainListEl.classList.remove("completed");

        // [NEW] Hiển thị dòng "Sản phẩm chưa đóng gói"
        const unpackedQty = newDone - parseFloat(mainListEl.getAttribute('data-packed-qty') || 0);
        let unpackedEl = mainListEl.querySelector('.unpacked-info');

        if (unpackedQty > 0) {
          if (!unpackedEl) {
            unpackedEl = document.createElement('div');
            unpackedEl.className = 'unpacked-info';
            unpackedEl.style.cssText = "font-size: 0.8rem; color: #d97706; margin-top: 4px; font-style: italic;";

            // [FIX] Selector robust: tìm div chứa info (thường là div đầu tiên)
            const infoContainer = mainListEl.querySelector('div') || mainListEl;
            infoContainer.appendChild(unpackedEl);
          }
          unpackedEl.innerText = `⚠️ Chưa đóng gói: ${unpackedQty}`;
        } else if (unpackedEl) {
          unpackedEl.remove();
        }

        // Hiệu ứng nháy vàng để báo hiệu đã update thành công
        highlightElement(mainListEl, "#ffd43b");
      } else {
        console.warn("⚠️ Không tìm thấy dòng sản phẩm bên ngoài để update ID:", change.moveLineId);
      }

      // D. Cập nhật data trong currentPackageData để đồng bộ với Side Panel
      if (currentPackageData?.items) {
        const itemIndex = currentPackageData.items.findIndex(i => String(i.move_line_id) === strLineId);
        if (itemIndex > -1) {
          currentPackageData.items[itemIndex].qty = change.newQty;

          // Nếu số lượng về 0 -> Xóa khỏi list items để side panel không hiện nữa
          if (change.newQty <= 0) {
            currentPackageData.items.splice(itemIndex, 1);
          }
        }
      }

    } catch (err) {
      toast.error("Lỗi kết nối: " + err.message);
      return;
    }
  }

  toast.success("Đã lưu thay đổi!", { ms: 1500 });
  updateSidePanelUI(currentPackageData); // Cập nhật lại số tổng trên thẻ gói bên phải
  closePackageEditModal();
}
// COMMENTED OUT: Split package functionality (tách gói thành đơn riêng)
// async function splitPackageFromModal() {
//   console.warn('splitPackageFromModal is disabled - feature under development');
//   toast.info('Tách gói tạm thời chưa khả dụng.', { ms: 2000 });
// }
function openTransferModalForItem(moveLineId, currentQty, productName) {
  console.log(`[DEBUG_TRANSFER_OPEN] Opening for ID: ${moveLineId} | Product: ${productName} | Qty: ${currentQty}`);

  // Lấy danh sách các gói khác để chuyển sang
  // const packs = (currentPackageData && currentPackageData.other_packages) || [];
  const packs = [];
  const currentPackId = currentPackageData.package_id;

  document.querySelectorAll('.package-item-card').forEach(card => {
    const pId = parseInt(card.dataset.packageId);

    // Chỉ lấy gói khác với gói hiện tại (không chuyển cho chính nó)
    if (pId && pId !== currentPackId) {
      const pName = card.querySelector('.package-item-name')?.innerText.trim() || `Pack ${pId}`;
      packs.push({
        package_id: pId,
        package_name: pName
      });
    }
  });
  // Validate: Nếu không có gói nào khác thì báo lỗi
  if (!packs.length) {
    toast.warn('Không có gói nào khác để chuyển sang.');
    return;
  }

  // Tạo nội dung Modal
  const content = document.createElement('div');
  content.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px;">
      <div style="padding:10px;background:#f0f9ff;border-radius:6px;border-left:3px solid #0ea5e9;">
        <strong>Sản phẩm:</strong> ${productName}
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <label style="font-weight:600;color:#374151;">Chọn gói đích:</label>
        <select id="transferTargetSelect" style="width:100%;padding:8px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;">
          <option value="">-- Chọn gói đích --</option>
          ${packs.map(p => `<option value="${p.package_id}">${p.package_name}</option>`).join('')}
        </select>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <label style="font-weight:600;color:#374151;">Số lượng chuyển (tối đa ${currentQty}):</label>
        <input id="transferQtyInput" type="number" min="1" max="${currentQty}" value="${Math.min(1, currentQty)}"
          style="padding:8px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;" />
      </div>
    </div>
  `;

  // Gọi Modal
  createModal('↔️ Chuyển sản phẩm', content, [
    { label: 'Hủy', color: '#6b7280', onclick: () => { } },
    {
      label: 'Chuyển', color: '#0ea5e9', onclick: async () => {
        const targetPackSelect = document.getElementById('transferTargetSelect');
        const targetPackId = targetPackSelect.value;
        const qty = parseFloat(document.getElementById('transferQtyInput').value);

        // Validate Input
        if (!targetPackId) { toast.warn('Vui lòng chọn gói đích'); return; }
        if (!qty || qty <= 0) { toast.warn('Vui lòng nhập số lượng hợp lệ'); return; }
        if (qty > currentQty) { toast.warn(`Số lượng không được vượt quá ${currentQty}`); return; }

        console.log(`[DEBUG_TRANSFER_EXEC] Executing Transfer: LineID=${moveLineId} -> Pack=${targetPackId} | Qty=${qty}`);

        try {
          const pickingId = parseInt(window.location.pathname.split("/").pop());

          // Gọi API Chuyển
          const res = await fetch('/pack_scan/transfer_item_between_packs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify({
              jsonrpc: '2.0',
              method: 'call',
              params: {
                picking_id: pickingId,
                source_package_id: currentPackageData.package_id,
                target_package_id: parseInt(targetPackId),
                move_line_id: parseInt(moveLineId),
                qty: qty
              }
            })
          });

          const response = await res.json();
          const result = response.result || response;

          if (result?.error) {
            toast.error(result.error);
            return;
          }

          toast.success('Đã chuyển sản phẩm!', { ms: 1000 });

          // ============================================================
          // [FIX UI] CẬP NHẬT GIAO DIỆN GÓI ĐÍCH (TARGET PACKAGE)
          // ============================================================
          const targetCard = document.querySelector(`.package-item-card[data-package-id="${targetPackId}"]`);

          if (targetCard) {
            // 1. Cập nhật Badge (Tổng số lượng bên ngoài thẻ)
            const badge = targetCard.querySelector('.badge');
            if (badge) {
              const currentTotal = parseFloat(badge.textContent.trim()) || 0;
              badge.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>
                ${currentTotal + qty}
              `;
            }

            // 2. Xử lý danh sách sản phẩm Preview (Gộp dòng & Fix tên & Style)
            const previewContainer = targetCard.querySelector('.package-items-preview');
            if (previewContainer) {
              // Xóa chữ "empty" nếu có
              const emptyEl = previewContainer.querySelector('.preview-empty');
              if (emptyEl) emptyEl.remove();

              // --- A. TẠO TÊN CHUẨN: [Barcode] Tên ---
              let finalName = productName;
              // Tìm lại dòng gốc trong danh sách chính để lấy barcode
              const lineEl = document.querySelector(`#product_list .product-item[data-line-id="${moveLineId}"]`);
              if (lineEl) {
                const barcode = lineEl.getAttribute('data-barcode') || '';
                const rawName = lineEl.querySelector('strong')?.innerText.trim() || productName;

                console.log(lineEl)

                // Nếu tên chưa có [...] và có barcode thì ghép vào
                if (barcode && !rawName.startsWith('[')) {
                  finalName = `[${barcode}] ${rawName}`;
                } else {
                  finalName = rawName;
                }
              }

              // --- B. KIỂM TRA XEM ĐÃ CÓ DÒNG NÀY CHƯA ĐỂ GỘP ---
              let foundItem = null;
              const existingItems = previewContainer.querySelectorAll('.preview-item');

              for (let item of existingItems) {
                const nameEl = item.querySelector('.preview-item-name');
                const currentName = nameEl.innerText;

                // So sánh tương đối để tìm dòng trùng (bất kể có mã hay chưa)
                if (currentName.includes(productName) || finalName.includes(currentName)) {
                  foundItem = item;
                  break;
                }
              }

              if (foundItem) {
                // === TRƯỜNG HỢP 1: ĐÃ CÓ -> CỘNG DỒN SỐ LƯỢNG ===
                const qtyEl = foundItem.querySelector('.preview-item-qty');
                if (qtyEl) {
                  // Lấy số hiện tại (bỏ chữ x đi)
                  const currentQtyVal = parseFloat(qtyEl.innerText.toLowerCase().replace('x', '')) || 0;
                  const newTotalQty = currentQtyVal + qty;

                  // Cập nhật số lượng mới (Format: xSố)
                  qtyEl.innerText = `x${newTotalQty}`;
                }

                // Cập nhật luôn cái tên chuẩn (có barcode) cho dòng cũ
                const nameEl = foundItem.querySelector('.preview-item-name');
                if (nameEl) nameEl.innerText = finalName;

                // Hiệu ứng nháy dòng đó (Vàng nhạt)
                foundItem.style.transition = 'background 0.3s';
                foundItem.style.backgroundColor = '#fff3cd';
                setTimeout(() => foundItem.style.backgroundColor = 'transparent', 500);

              } else {
                // === TRƯỜNG HỢP 2: CHƯA CÓ -> THÊM DÒNG MỚI (PREPEND) ===
                const newItemHtml = `
                    <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center; animation: fadeIn 0.5s;">
                      <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057; font-size: 0.85rem;">${finalName}</span>
                      <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">x${qty}</span>
                    </div>
                   `;
                previewContainer.insertAdjacentHTML('afterbegin', newItemHtml);
              }
            }

            // Hiệu ứng nháy sáng thẻ Package Đích
            targetCard.style.transition = 'background-color 0.5s';
            targetCard.style.backgroundColor = '#e7f5ff';
            setTimeout(() => targetCard.style.backgroundColor = 'white', 1000);
          }

          // --- 3. Reload Modal Gói Nguồn (Source Package) ---
          // Để cập nhật lại số lượng đã bị trừ đi ở gói hiện tại
          openPackageEditModal({
            currentTarget: { dataset: { packageId: currentPackageData.package_id } },
            stopPropagation: () => { }
          });

        } catch (err) {
          toast.error('Lỗi kết nối: ' + err.message);
        }
      }
    }
  ]);
}

function renderNewPackageToPanel(pkgId, pkgName, itemsData) {
  // 1. Tìm list container
  let list = document.querySelector('.panel-packages-list');
  const emptyState = document.querySelector('.panel-empty-state');

  // 2. Tính tổng số lượng item mới
  const newItemsQty = itemsData.reduce((sum, i) => sum + i.qty, 0);

  // ============================================================
  // HELPER: Hàm lấy tên chuẩn [Barcode] Tên (KHÔNG update data-packed-qty nữa)
  // ============================================================
  const getProductInfo = (item) => {
    // Ưu tiên lấy tên từ item đã enriched
    let finalName = item.name || 'Sản phẩm...';

    // Nếu có barcode, ghép vào theo chuẩn
    if (item.barcode && !finalName.startsWith('[')) {
      finalName = `[${item.barcode}] ${finalName}`;
    }

    // Fallback: Nếu không có name/barcode trong item, thử tìm DOM (Legacy)
    if ((!item.name || !item.barcode) && item.move_line_id) {
      const lineEl = document.querySelector(`[data-line-id="${item.move_line_id}"]`);
      if (lineEl) {
        const rawName = lineEl.querySelector('strong')?.innerText.trim() || '';
        const barcode = lineEl.getAttribute('data-barcode') || '';
        if (rawName) {
          finalName = (barcode && !rawName.startsWith('[')) ? `[${barcode}] ${rawName}` : rawName;
        }
      }
    }
    return finalName;
  };

  // 3. Kiểm tra xem gói đã tồn tại chưa
  const existingCard = document.querySelector(`.package-item-card[data-package-id="${pkgId}"]`);

  if (existingCard) {
    // === TRƯỜNG HỢP A: ĐÃ CÓ GÓI -> CẬP NHẬT (MERGE) ===

    // a. Cập nhật Badge tổng
    const badge = existingCard.querySelector('.badge');
    if (badge) {
      const currentTotal = parseFloat(badge.textContent.trim()) || 0;
      badge.innerHTML = `
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>
          ${currentTotal + newItemsQty}
      `;
    }

    // b. Xử lý từng item: Tìm xem đã có dòng đó chưa để cộng dồn
    const previewContainer = existingCard.querySelector('.package-items-preview');
    if (previewContainer) {
      const emptyEl = previewContainer.querySelector('.preview-empty');
      if (emptyEl) emptyEl.remove();

      itemsData.forEach(item => {
        if (item.qty <= 0) return;
        const name = getProductInfo(item);

        // Tìm dòng cũ trùng tên
        let foundRow = null;
        // Duyệt qua các dòng hiện có để tìm
        for (let row of previewContainer.querySelectorAll('.preview-item')) {
          if (row.querySelector('.preview-item-name').innerText === name) {
            foundRow = row;
            break;
          }
        }




        if (foundRow) {
          // Nếu có rồi: Cộng dồn số lượng
          const qtyEl = foundRow.querySelector('.preview-item-qty');
          if (qtyEl) {
            const oldQty = parseFloat(qtyEl.innerText.replace('x', '')) || 0;
            qtyEl.innerText = `x${oldQty + item.qty}`;
          }

          // Nháy màu
          foundRow.style.transition = 'background 0.3s';
          foundRow.style.backgroundColor = '#fff3cd';
          setTimeout(() => foundRow.style.backgroundColor = 'transparent', 500);
        } else {

          // Nếu chưa có: Thêm mới lên đầu
          const newHtml = `
              <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center; animation: fadeIn 0.5s;">
                <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057; font-size: 0.85rem;">${name}</span>
                <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">x${item.qty}</span>
              </div>`;
          previewContainer.insertAdjacentHTML('afterbegin', newHtml);
        }
      });
    }

    // Hiệu ứng card
    existingCard.style.transition = 'background-color 0.5s ease';
    existingCard.style.backgroundColor = '#e7f5ff';
    setTimeout(() => { existingCard.style.backgroundColor = 'white'; }, 800);
    existingCard.parentElement.prepend(existingCard);

  } else {
    // === TRƯỜNG HỢP B: TẠO GÓI MỚI (CREATE) ===

    // a. Gộp các item trùng tên trong danh sách itemsData trước khi render (Aggregation)
    // Ví dụ: Input có 2 dòng "Sản phẩm A" qty 1 -> Gộp thành 1 dòng qty 2
    const aggregatedItems = {};

    itemsData.forEach(item => {
      if (item.qty <= 0) return;
      const name = getProductInfo(item);
      if (aggregatedItems[name]) {
        aggregatedItems[name] += item.qty;
      } else {
        aggregatedItems[name] = item.qty;
      }
    });

    // b. Tạo HTML từ danh sách đã gộp
    let previewHtml = '';
    for (const [name, qty] of Object.entries(aggregatedItems)) {
      previewHtml += `
          <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center;">
            <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057; font-size: 0.85rem;">${name}</span>
            <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">x${qty}</span>
          </div>
        `;
    }

    // c. Tạo khung thẻ
    if (!list) {
      if (emptyState) emptyState.remove();
      list = document.createElement('ul');
      list.className = 'panel-packages-list';
      list.style.cssText = "list-style: none; padding: 0; margin: 0;";
      const panelBody = document.querySelector('.pack-side-panel .panel-body');
      const title = panelBody.querySelector('.panel-section-title');
      if (title) title.after(list); else panelBody.prepend(list);
    }

    const li = document.createElement('li');
    li.className = 'package-item-card';
    li.dataset.packageId = pkgId;
    li.style.cssText = "background: white; border-radius: 10px; padding: 1rem; margin-bottom: 1rem; box-shadow: 0 4px 12px rgba(0,0,0,0.03); border: 1px solid #f1f3f5; transition: all 0.2s ease; animation: fadeIn 0.5s ease;";

    li.innerHTML = `
        <div class="package-item-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; padding-bottom: 0.75rem; border-bottom: 1px solid #f8f9fa;">
          <strong class="package-item-name" style="font-size: 0.95rem; color: #212529; font-weight: 600;">${pkgName}</strong>
          <span class="badge" style="background: #e7f5ff; color: #1c7ed6; padding: 0.25rem 0.6rem; border-radius: 6px; font-size: 0.75rem; font-weight: 600; display: flex; align-items: center; gap: 0.25rem;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>
            ${newItemsQty}
          </span>
        </div>
        
        <div class="package-items-preview" style="margin-bottom: 1rem; font-size: 0.85rem; color: #495057;">
          ${previewHtml}
        </div>

        <button class="btn-package-edit" data-package-id="${pkgId}" style="width: 100%; padding: 0.6rem; background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; color: #495057; font-weight: 600; font-size: 0.85rem; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 0.5rem; transition: all 0.2s;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
          Chỉnh sửa
        </button>
      `;

    li.querySelector('.btn-package-edit').addEventListener('click', openPackageEditModal);
    list.prepend(li);
  }
}


// ===================== PANEL VISIBILITY TOGGLE =====================
function togglePanelVisibility(button) {
  const panel = button.closest('.pack-side-panel');
  if (!panel) return;

  const isCollapsed = panel.classList.toggle('collapsed');
  button.textContent = isCollapsed ? 'Hiện' : 'Ẩn';
}

// ===================== UPDATE SIDE PANEL UI =====================
/**
 * Cập nhật giao diện thẻ gói bên Side Panel sau khi chỉnh sửa
 * (Thay thế hoàn toàn nội dung preview bằng data mới)
 */
function updateSidePanelUI(pkgData) {
  if (!pkgData || !pkgData.package_id) return;

  const pkgId = pkgData.package_id;
  const card = document.querySelector(`.package-item-card[data-package-id="${pkgId}"]`);

  if (!card) {
    console.warn("Không tìm thấy thẻ gói để cập nhật:", pkgId);
    // Nếu chưa có (ví dụ gói mới tạo), có thể gọi renderNewPackageToPanel?
    // Nhưng ở đây là update sau khi edit, nên thường là đã có.
    return;
  }

  // 1. Tính toán lại dữ liệu
  const items = pkgData.items || [];
  const totalQty = items.reduce((sum, item) => sum + (parseFloat(item.qty) || parseFloat(item.qty_done) || 0), 0);

  // 2. Cập nhật Badge tổng
  const badge = card.querySelector('.badge');
  if (badge) {
    badge.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>
        ${totalQty}
      `;
  }

  // 3. Re-render Preview List
  // Gộp các item trùng tên trước khi hiển thị
  const aggregatedItems = {};
  items.forEach(item => {
    const rawQty = parseFloat(item.qty) || parseFloat(item.qty_done) || 0;
    if (rawQty <= 0) return;

    // Logic lấy tên hiển thị (ưu tiên tên đã xử lý hoặc raw)
    let displayName = item.product_name;
    // Nếu muốn hiển thị Barcode chuẩn:
    // ... (Có thể dùng logic getProductInfo nhưng cần DOM line, ở đây dùng data có sẵn)
    if (item.product_barcode && !displayName.startsWith('[')) {
      displayName = `[${item.product_barcode}] ${displayName}`;
    }

    if (aggregatedItems[displayName]) {
      aggregatedItems[displayName] += rawQty;
    } else {
      aggregatedItems[displayName] = rawQty;
    }
  });

  const previewContainer = card.querySelector('.package-items-preview');
  if (previewContainer) {
    let html = '';
    for (const [name, qty] of Object.entries(aggregatedItems)) {
      html += `
          <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center;">
            <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057; font-size: 0.85rem;">${name}</span>
            <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">x${qty}</span>
          </div>
       `;
    }

    if (!html) {
      html = '<div class="preview-empty" style="font-style: italic; color: #adb5bd;">Gói rỗng</div>';

    }

    previewContainer.innerHTML = html;

    // Hiệu ứng nháy để báo cập nhật
    card.style.transition = 'background-color 0.3s';
    card.style.backgroundColor = '#fff9db'; // Màu vàng nhạt
    setTimeout(() => card.style.backgroundColor = 'white', 600);
  }
}