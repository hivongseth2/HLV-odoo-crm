/**
 * scan_pack.js — Core Pack Scan Controller (DOMContentLoaded handler)
 * Barcode scanning, manual qty input, updateQty, complete picking,
 * partial pack, unpack-all, print labels, and page initialization.
 *
 * Depends on:
 *   toast.js          — toast notifications
 *   recording.js      — startRecording, stopRecording, diag
 *   server_sync.js    — applyServerSyncInfo, updateUnpackedLabel
 *   ui_utils.js       — optimizePackageUI
 *   side_panel.js     — renderNewPackageToPanel
 */

document.addEventListener("DOMContentLoaded", function () {

  // §2.1 — DOM references & focus management
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
  // §2.2 — Barcode input & debounce

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



  // §2.3 — Manual qty input handlers
  window.handleManualQtyKey = function (event, el) {
    if (event.key === 'Enter') {
      el.blur(); // Trigger change
      setFocus(); // Focus back to barcode input
    }
  };

  window.handleManualQtyChange = async function (el) {
    const newVal = parseFloat(el.value) || 0;
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
      await updateQty(barcode, delta, lineId, moveId, true);
    } catch (e) {
      // Fail: Revert UI
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

  // §2.4 — Barcode helpers & normalizeCode
  function normalizeCode(s) {
    // Bỏ kí tự điều khiển ASCII, khoảng trắng, NBSP, BOM, zero-width, v.v.
    return String(s ?? '')
      .replace(/[\u0000-\u001F\u007F-\u009F]/g, '')   // control chars
      .replace(/[\u200B-\u200D\u2060\uFEFF]/g, '')    // zero-width & BOM
      .replace(/\s+/g, '')                             // mọi whitespace (kể cả NBSP)
      .trim();
  }
  window.normalizeCode = normalizeCode;

  // §2.5 — findLineToUpdate
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
      const input = el.querySelector(".done-input");
      const doneVal = input ? input.value : (el.querySelector(".done")?.innerText || 0);
      const done = parseFloat(doneVal) || 0;

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
  window.highlightElement = function (el, color = "#ffeb3b") {
    if (!el) return;

    el.style.transition = "none";
    el.style.backgroundColor = "transparent";

    void el.offsetWidth;

    el.style.transition = "background-color 0.4s ease-out";
    el.style.removeProperty("background-color");

    el.style.setProperty("background-color", color, "important");

    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    setTimeout(() => {
      el.style.transition = "background-color 1.5s ease-out";
      el.style.backgroundColor = "";
      setTimeout(() => { el.style.transition = ""; }, 1500);
    }, 600);
  };

  // §2.6 — updateQty (core scan → server flow)
  async function updateQty(barcode, delta = 1, lineId = null, moveId = null, skipValidation = false) {
    if (!lineId) {
      const found = findLineToUpdate(barcode);
      lineId = found?.lineId || null;
      moveId = found?.moveId || null;
    }
    if (lineId && !moveId) {
      const el = document.querySelector(`[data-line-id="${lineId}"]`);
      if (el) moveId = el.dataset.moveId || null;
    }

    // [NEW] Client-side Over-Quantity Validation
    if (lineId && !skipValidation) {
      const checkEl = moveId
        ? document.querySelector(`[data-move-id="${moveId}"]`)
        : document.querySelector(`[data-line-id="${lineId}"]`);
      if (checkEl) {
        const maxQty = parseFloat(checkEl.getAttribute('data-max-qty') || 0);
        const input = checkEl.querySelector(".done-input");
        const currentDone = parseFloat(
          input ? (input.dataset.currentQty !== undefined && input.dataset.currentQty !== ''
            ? input.dataset.currentQty
            : input.value)
            : (checkEl.querySelector(".done")?.innerText || 0)
        ) || 0;

        if (maxQty > 0 && (currentDone + delta) > maxQty + 0.001) {
          toast.warn(`❌ Không được nhập quá số lượng yêu cầu (${maxQty})!`);
          playError();
          if (input) {
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

      if (result?.error) {
        toast.error(result.error);
        playError();
        setFocus();
        throw new Error(result.error);
      }
      if (!result?.scanned?.length) {
        toast.warn('Không có dòng nào được cập nhật');
        playError();
        setFocus();
        throw new Error("No lines updated");
      }

      result.scanned.forEach(item => {
        let el = item.move_id ? document.querySelector(`[data-move-id="${item.move_id}"]`) : null;
        if (!el) el = document.querySelector(`[data-line-id="${item.line_id}"]`);

        if (!el && item.barcode) {
          const code = normalizeCode(item.barcode).toUpperCase();
          const candidates = [...document.querySelectorAll('#product_list li.product-item')]
            .filter(e => normalizeCode(e.dataset.barcode).toUpperCase() === code);

          const targetDone = parseFloat(item.done_qty || 0);
          const targetMax = parseFloat(item.required_qty || 0);

          let bestMatch = null;
          let minDiff = Infinity;

          for (const c of candidates) {
            if (String(c.dataset.lineId) === String(item.line_id)) {
              bestMatch = c;
              break;
            }

            let mMax = parseFloat(c.dataset.maxQty || 0);

            if (mMax === 0) {
              const doneInp = c.querySelector('.done-input');
              const reqEl = doneInp ? doneInp.nextElementSibling.nextElementSibling : c.querySelectorAll("span")[1];
              if (reqEl) mMax = parseFloat(reqEl.innerText.replace(',', '.') || 0);
            }

            const mDoneInput = c.querySelector('.done-input');
            const mDone = parseFloat(mDoneInput ? (mDoneInput.value || 0) : (c.querySelector('.done')?.innerText || 0));

            const diff = Math.abs(mDone - targetDone);

            if (diff < minDiff) {
              minDiff = diff;
              bestMatch = c;
            } else if (diff === minDiff) {
              if (mMax === targetMax) bestMatch = c;
            }
          }

          let match = bestMatch;

          if (!match && candidates.length > 0) {
            match = candidates[candidates.length - 1];
          }

          if (match) {
            console.log(`[SCAN] Force updating row ${match.dataset.lineId} -> ${item.line_id}`);
            el = match;

            el.setAttribute('data-line-id', item.line_id);
            el.dataset.lineId = String(item.line_id);

            el.setAttribute('data-packed-qty', item.packed_qty || 0);
            el.dataset.packedQty = item.packed_qty || 0;

            const input = el.querySelector(".done-input");
            if (input) {
              input.dataset.lineId = String(item.line_id);
            }

            highlightElement(el, "#dbe4ff");
          } else {
            console.warn("No candidates found to update for", item.barcode);
          }
        }

        if (!el) { console.warn('No DOM line for', item); return; }

        if (item.line_id && el.dataset.lineId !== String(item.line_id)) {
          el.setAttribute('data-line-id', item.line_id);
          el.dataset.lineId = String(item.line_id);
          const doneInp = el.querySelector('.done-input');
          if (doneInp) doneInp.dataset.lineId = String(item.line_id);
        }

        const requiredEl = el.querySelectorAll('span')[1];
        const required = parseFloat((requiredEl?.innerText || '0').replace(',', '.')) || 0;

        const doneInput = el.querySelector('.done-input');

        if (doneInput) {
          doneInput.value = item.done_qty;
          doneInput.dataset.currentQty = item.done_qty;
        } else {
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
        updateUnpackedLabel(el);

        if (item.done_qty >= required) el.classList.add("completed");
        else el.classList.remove("completed");

        highlightElement(el, "#ffd43b");
      });

      // Show "Làm lại" nếu có qty_done > 0
      toggleUnpackBtn();

    } catch (err) {
      toast.error("Lỗi kết nối: " + err.message);
      playError();
      setFocus();
    }
  }



  // §2.7 — Complete picking
  completeBtn?.addEventListener("click", async function () {
    await flushActiveInput();

    const items = document.querySelectorAll("#product_list .product-item");
    let isValid = true, missingProducts = [];
    items.forEach(item => {
      const name = item.querySelector("strong").innerText;

      const input = item.querySelector(".done-input");
      const doneVal = input ? input.value : (item.querySelector(".done")?.innerText || 0);
      const done = parseFloat(doneVal) || 0;

      const requiredEl = input ? input.nextElementSibling.nextElementSibling : item.querySelectorAll("span")[1];
      const required = parseFloat(requiredEl?.innerText || 0);

      if (done < required) { isValid = false; missingProducts.push(`${name} (${done}/${required})`); }
    });

    if (!isValid) {
      toast.warn("Chưa quét đủ:\n- " + missingProducts.join("\n- "), { ms: 3500 });
      return;
    }

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
        await new Promise(resolve => setTimeout(resolve, 500));
      }
    } catch (e) {
      console.warn("Lỗi kiểm tra package:", e);
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

    await stopRecording();

    toast.success("Phiếu đã hoàn tất! Đang chuyển trang...", { ms: 1200 });
    setTimeout(() => { window.location.href = "/custom_barcode_scan/ui"; }, 600);
  });

  const btnSwitch = document.getElementById('btnDriveSwitch');
  if (btnSwitch) {
    btnSwitch.addEventListener('click', () => {
      window.open('/gdrive/oauth2/disconnect', '_blank', 'noopener');
    });
  }

  // §2.8 — Partial pack / Unpack-all buttons
  document.getElementById('btnPartialPack')?.addEventListener('click', async function () {
    await flushActiveInput();

    const autoPackageBarcode = `AUTO-PKG-${Date.now()}`;
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

  // Nút Bỏ đóng gói toàn bộ
  document.getElementById('btnUnpackAll')?.addEventListener('click', async function () {
    if (!confirm('Bạn có chắc muốn bỏ đóng gói TOÀN BỘ sản phẩm trong phiếu này?')) return;
    try {
      const res = await fetch('/pack_scan/unpack_all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { picking_id: pickingId } }),
      });
      const json = await res.json();
      const data = json.result || json;
      if (data.error) {
        toast.error(data.error);
      } else {
        toast.success(data.message || 'Đã bỏ đóng gói thành công!');
        // Reset toàn bộ DOM về 0 (không reload để không cắt video)
        document.querySelectorAll('#product_list .product-item').forEach(el => {
          const input = el.querySelector('.done-input');
          if (input) {
            input.value = 0;
            input.dataset.currentQty = 0;
          }
          el.setAttribute('data-packed-qty', 0);
          el.querySelector('.pkg-indicator')?.remove();
          el.querySelector('.unpacked-info')?.remove();
          el.classList.remove('completed');
        });
        // Xóa tất cả thẻ kiện trong side panel
        document.querySelector('.panel-packages-list')?.remove();
        // Ẩn nút "Làm lại" vì qty_done đã reset về 0
        toggleUnpackBtn();
      }
    } catch (e) {
      toast.error('Lỗi khi bỏ đóng gói: ' + e.message);
    }
  });


  input?.addEventListener("keypress", async function (event) {

    if (event.key !== "Enter" && event.keyCode !== 13) return;

    const raw = this.value.trim();
    if (!raw) return;
    this.value = "";

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

    const barcode = raw;

    if (barcode !== 'CMD-CREATE-PACK' && !barcode.startsWith("AUTO-PKG-") && !barcode.startsWith("PACK")) {

      const foundLine = findLineToUpdate(barcode);

      if (foundLine) {
        const lineEl = foundLine.moveId
          ? document.querySelector(`[data-move-id="${foundLine.moveId}"]`)
          : document.querySelector(`[data-line-id="${foundLine.lineId}"]`);
        if (lineEl) {
          const required = parseFloat(lineEl.querySelectorAll("span")[1]?.innerText || 0);
          if (required < 10) {
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

      if (isProcessingPack) {
        console.warn("Packing already in progress...");
        return;
      }

      const items = [];
      document.querySelectorAll("#product_list .product-item").forEach(el => {
        const lineId = parseInt(el.dataset.lineId);
        const name = el.querySelector("strong")?.innerText;

        const input = el.querySelector(".done-input");
        const doneVal = input ? input.value : (el.querySelector(".done")?.innerText || 0);
        const currentDone = parseFloat(doneVal) || 0;

        const alreadyPacked = parseFloat(el.dataset.packedQty || 0);
        const qtyToPack = currentDone - alreadyPacked;

        console.log(`[DEBUG_PACK] ${name} | Line: ${lineId} | Done: ${currentDone} | Packed: ${alreadyPacked} | ToPack: ${qtyToPack}`);

        const barcode = el.dataset.barcode || "";
        if (lineId && qtyToPack > 0) {
          items.push({
            move_line_id: lineId,
            qty: qtyToPack,
            name: name,
            barcode: barcode
          });
        }
      });

      if (items.length === 0) {
        toast.warn("Không có sản phẩm nào mới để đóng gói (Tất cả đã nằm trong gói).");
        playError();
        return;
      }

      const pkgCode = (barcode === 'CMD-CREATE-PACK') ? `AUTO-PKG-${Date.now()}` : barcode;

      if (barcode === 'CMD-CREATE-PACK') {
        toast.info(`Đang tạo gói hàng tự động...`, { ms: 1000 });
      }

      isProcessingPack = true;
      try {
        const res = await fetch('/pack_scan/create_partial_pack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          body: JSON.stringify({
            jsonrpc: '2.0',
            method: 'call',
            params: {
              picking_id: pickingId,
              package_barcode: pkgCode,
              move_line_data: items
            }
          })
        });

        const response = await res.json();
        const result = response.result || response;

        if (result?.package_id) {
          toast.success(`Tạo gói hàng ${result.package_name} thành công!`);

          // Update packed_qty trên DOM từ sync_info
          if (result.sync_info) {
            result.sync_info.forEach(info => {
              document.querySelectorAll('#product_list .product-item').forEach(el => {
                if (el.dataset.barcode === info.product_barcode) {
                  el.setAttribute('data-packed-qty', info.packed_qty);
                  updateUnpackedLabel(el);
                }
              });
            });
          }

          // Fallback: clear "chưa đóng gói" cho tất cả items vừa đóng
          items.forEach(item => {
            document.querySelectorAll('#product_list .product-item').forEach(el => {
              if (el.dataset.barcode === item.barcode) {
                // packed_qty = currentDone → unpacked = 0
                const input = el.querySelector('.done-input');
                const currentDone = parseFloat(input ? input.value : 0) || 0;
                el.setAttribute('data-packed-qty', currentDone);
                updateUnpackedLabel(el);
              }
            });
          });

          // Cập nhật pkg-badge trên dòng sản phẩm
          items.forEach(item => {
            document.querySelectorAll('#product_list .product-item').forEach(el => {
              if (el.dataset.barcode === item.barcode) {
                let indicator = el.querySelector('.pkg-indicator');
                if (!indicator) {
                  indicator = document.createElement('div');
                  indicator.className = 'pkg-indicator';
                  el.querySelector('div')?.appendChild(indicator);
                }
                // Kiểm tra badge cho kiện này đã có chưa
                const existing = indicator.querySelector(`[data-pkg-id="${result.package_id}"]`);
                if (!existing) {
                  const badge = document.createElement('span');
                  badge.className = 'pkg-badge pkg-badge-done';
                  badge.dataset.pkgId = result.package_id;
                  badge.textContent = '\uD83D\uDCE6 ' + result.package_name;
                  indicator.appendChild(badge);
                }
              }
            });
          });

          // Render gói mới vào side panel (không reload)
          renderNewPackageToPanel(result.package_id, result.package_name, items);
        } else {
          toast.error(result?.error || "Lỗi tạo gói hàng");
          playError();
        }
      } catch (e) {
        toast.error("Lỗi kết nối: " + e.message);
        playError();
      } finally {
        isProcessingPack = false;
      }
      return;
    }

    // D. Logic quét sản phẩm thông thường (Cộng dồn số lượng)
    await updateQty(barcode);
  });

  // §2.9 — Print label buttons
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

  // Helper: show/hide "Làm lại" button based on any qty_done > 0
  function toggleUnpackBtn() {
    const btn = document.getElementById('btnUnpackAll');
    if (!btn) return;
    const hasAnyDone = [...document.querySelectorAll('#product_list .done-input')]
      .some(inp => parseFloat(inp.value || 0) > 0);
    const hasPackages = !!document.querySelector('.panel-packages-list .package-item-card');
    btn.style.display = (hasAnyDone || hasPackages) ? '' : 'none';
  }
  window.toggleUnpackBtn = toggleUnpackBtn;

  // §2.10 — Page init
  setFocus();
  diag();
  setTimeout(optimizePackageUI, 100);
  setTimeout(() => {
    document.querySelectorAll('#product_list .product-item').forEach(el => updateUnpackedLabel(el));
  }, 150);
  setTimeout(startRecording, 400);
  setTimeout(toggleUnpackBtn, 200);
});
