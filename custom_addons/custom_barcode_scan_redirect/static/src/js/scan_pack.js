// Toast helper - Global scope để accessible từ mọi nơi
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

  // === SMART AUTO-FOCUS ===
  // Always keep focus on Barcode Scanner Input, unless user is typing manually
  const enforceFocus = () => {
    // 1. Check if ANY modal is currently visible (robust check)
    // We check for .modal-overlay that does NOT have "display: none"
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

  /* --- CUSTOM LOGIC: Scanner Detection & Manual Input Handlers --- */
  let lastKeyTime = 0;
  let fastKeyCount = 0;

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

  // Expose handlers for manual input
  window.handleManualQtyChange = async function (el) {
    const qty = parseFloat(el.value);
    if (isNaN(qty) || qty < 0) return;

    const lineId = el.dataset.lineId;
    const barcode = el.dataset.barcode;
    const lineEl = document.querySelector(`.product-item[data-line-id="${lineId}"]`);
    if (!lineEl) { toast.error("Không tìm thấy dòng sản phẩm"); return; }

    // Get old value from data attribute (robust against focus issues)
    // "dataset.currentQty" comes from server initial render or previous updateQty
    let currentDone = parseFloat(el.dataset.currentQty);
    if (isNaN(currentDone)) currentDone = 0;

    // Safety check: if inputs are weird

    // --- VALIDATION: Prevent Excess Input ---
    const requiredEl = el.nextElementSibling ? el.nextElementSibling.nextElementSibling : null;
    const required = parseFloat(requiredEl ? requiredEl.innerText : 999999);

    if (qty > required) {
      toast.error(`Không được nhập quá số lượng yêu cầu (${required})`);
      playError();
      el.value = currentDone; // Revert to old value
      el.dataset.currentQty = currentDone; // Ensure dataset is sync
      // Force Refocus and select to easy edit?
      el.select();
      return; // Abort update
    }
    // ----------------------------------------

    const delta = qty - currentDone;
    // Update old value can wait for updateQty? NO. 
    // updateQty is async. If we don't block user, they might type again. 
    // But we disabled input.
    // However, if we fail to update, we should maybe revert?
    // Let's rely on updateQty to fix the state.

    if (delta !== 0) {
      // Optimistically update old value so next change is relative to this one? 
      // No, updateQty is async. If user types again before it finishes...?
      // Ideally we disable input while updating.
      el.disabled = true;
      try {
        await updateQty(barcode, delta, lineId);
        // On success, updateQty refreshes the input.
      } catch (err) {
        console.error("Update failed", err);
        // Revert on error
        el.value = currentDone;
        toast.error("Cập nhật thất bại. Vui lòng thử lại.");
        playError();
      } finally {
        // If updateQty returned early due to internal error checks (which trigger toast but resolves promise)
        // We need to verify if value actually changed or if we should revert?
        // Actually updateQty calls setFocus/toast internally on error result.
        // We just need to check if input is still desynced?
        // Better yet: updateQty should THROW if result.error so we catch here.
        // BUT updateQty is void/async. Let's make it throw or return false.

        // RE-READ dataset just in case updateQty success updated it
        if (el.dataset.currentQty) {
          el.value = el.dataset.currentQty;
        }

        el.disabled = false;
        el.focus(); // Keep focus?
      }
    }
  };

  window.handleManualQtyKey = function (event, el) {
    if (event.key === 'Enter') {
      el.blur(); // Trigger change
      setFocus(); // Focus back to barcode input
    }
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

  function normalizeCode(s) {
    // Bỏ kí tự điều khiển ASCII, khoảng trắng, NBSP, BOM, zero-width, v.v.
    return String(s ?? '')
      .replace(/[\u0000-\u001F\u007F-\u009F]/g, '')   // control chars
      .replace(/[\u200B-\u200D\u2060\uFEFF]/g, '')    // zero-width & BOM
      .replace(/\s+/g, '')                             // mọi whitespace (kể cả NBSP)
      .trim();
  }

  function findLineToUpdate(barcode) {
    const elements = [...document.querySelectorAll(`[data-barcode="${barcode}"]`)];
    for (const el of elements) {
      // Changed: Support done-input or fallback to .done
      const input = el.querySelector(".done-input");
      const doneVal = input ? input.value : (el.querySelector(".done")?.innerText || 0);
      const done = parseFloat(doneVal);


      // Attempt to find required element relative to input (if input exists)
      const requiredEl = input ? input.nextElementSibling.nextElementSibling : el.querySelectorAll("span")[1];

      const required = parseFloat(requiredEl?.innerText || 0);

      if (done < required) {
        return el.dataset.lineId;
      }
    }
    return null; // tất cả đã đủ
  }

  // Helper to flash element
  // Helper to flash element (EXPOSED TO WINDOW for global access)
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

  async function updateQty(barcode, delta = 1, lineId = null) {
    if (!lineId) {
      lineId = findLineToUpdate(barcode);
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
            line_id: lineId
          }
        })
      });
      const response = await res.json();
      const result = response.result;

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
        // cố gắng tìm theo line_id, nếu không có thì rớt về tìm theo barcode
        let el = document.querySelector(`[data-line-id="${item.line_id}"]`);
        if (!el && item.barcode) {
          const code = normalizeCode(item.barcode);
          el = [...document.querySelectorAll('#product_list li.product-item')]
            .find(e => normalizeCode(e.dataset.barcode) === code) || null;
          if (el && item.line_id) el.dataset.lineId = String(item.line_id); // gắn lại cho những lần sau
        }
        if (!el) { console.warn('No DOM line for', item); return; }

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

  // Listeners for +/- buttons removed as buttons are hidden/removed from UI.


  completeBtn?.addEventListener("click", async function () {
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
  document.getElementById('btnPartialPack')?.addEventListener('click', function () {
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
    toast.info(`Mã barcode tạo: ${autoPackageBarcode}`, { ms: 4000 });
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

    // --- CHECK RESTRICTION FOR MANUAL INPUT ---
    // Kiểm tra nếu là barcode thường (không phải lệnh) và số lượng < 10
    if (barcode !== 'CMD-CREATE-PACK' && !barcode.startsWith("AUTO-PKG-") && !barcode.startsWith("PACK")) {
      // Tìm dòng sản phẩm tương ứng
      // Lưu ý: findLineToUpdate trả về lineId (string) hoặc null
      const lineId = findLineToUpdate(barcode);

      // Nếu tìm thấy dòng cần update (chưa done), kiểm tra required qty
      if (lineId) {
        const lineEl = document.querySelector(`[data-line-id="${lineId}"]`);
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
    // ------------------------------------------

    // C. LOGIC MỚI: Xử lý mã lệnh tạo gói (CMD-CREATE-PACK hoặc AUTO-PKG-...)
    if (barcode === 'CMD-CREATE-PACK' || barcode.startsWith("AUTO-PKG-") || barcode.startsWith("PACK")) {

      // 1. Thu thập các dòng đã quét (qty > 0) ở danh sách bên trái
      const items = [];
      document.querySelectorAll("#product_list .product-item").forEach(el => {
        const lineId = parseInt(el.dataset.lineId);

        const input = el.querySelector(".done-input");
        const doneVal = input ? input.value : (el.querySelector(".done")?.innerText || 0);
        const currentDone = parseFloat(doneVal);

        const alreadyPacked = parseFloat(el.dataset.packedQty || 0); // Lấy số đã đóng gói từ data attribute

        // Tính số lượng trôi nổi (chưa vào gói)
        const qtyToPack = currentDone - alreadyPacked;

        // Chỉ lấy nếu còn hàng chưa đóng gói
        if (lineId && qtyToPack > 0) {
          items.push({ move_line_id: lineId, qty: qtyToPack });
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
        toast.info(`Đang tạo gói hàng tự động...`, { ms: 2000 });
      }

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
              move_line_data: items,
              package_barcode: pkgCode
            }
          })
        });
        const response = await res.json();
        const result = response.result || response;

        if (result?.success) {
          toast.success(result.message);
          playSuccess();

          // 5. CẬP NHẬT UI: Thêm gói mới vào Side Panel ngay lập tức
          renderNewPackageToPanel(result.package_id, result.package_name, items);


        } else {
          toast.error(result?.error || "Lỗi tạo gói hàng");
          playError();
        }
      } catch (e) {
        toast.error("Lỗi kết nối: " + e.message);
        playError();
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

  setFocus();
  diag();
  setTimeout(optimizePackageUI, 100); // Delay nhẹ 100ms để đảm bảo DOM đã render xong
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

// ====== Recording Module ======
let mediaStream = null;
let mediaRecorder = null;
let isRecording = false;
let chunkBusy = Promise.resolve();

const MAX_DURATION_MS = 15 * 60 * 1000; // 5 phút
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

      nameEl.innerText = name;
      nameEl.style.color = "#495057";
      nameEl.style.fontSize = "0.85rem";

      qtyEl.innerText = `x${data.qty}`;
      qtyEl.style.cssText = "font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;";

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

  // COMMENTED OUT: Transfer functionality between sibling packs (tách đơn)
  // if (transferBtn) {
  //   const sourcePack = parseInt(transferBtn.dataset.packId);
  //   const targetPack = pickingId;
  //   
  //   createModal(
  //     '↔️ Chuyển sản phẩm',
  //     'Tính năng chuyển sản phẩm giữa các pack. Chọn sản phẩm để chuyển.',
  //     [
  //       { label: 'Hủy', color: '#999', onclick: () => {} },
  //       { label: 'Chuyển', color: '#ffa500', onclick: async () => {
  //           toast.info('Tính năng này sẽ được hoàn thiện trong phiên bản tiếp theo', { ms: 2000 });
  //         }
  //       }
  //     ]
  //   );
  // }
});

// ===================== PACKAGE EDIT MODAL FUNCTIONS =====================
let currentPackageData = null;


function updateSidePanelUI(packageData) {
  if (!packageData || !packageData.package_id) return;
  const card = document.querySelector(`.package-item-card[data-package-id="${packageData.package_id}"]`);
  if (!card) return;

  // 1. Cập nhật Badge
  const badge = card.querySelector('.badge');
  if (badge) {
    const totalQty = (packageData.items || []).reduce((sum, item) => sum + (parseFloat(item.qty_done) || 0), 0);
    const iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>`;
    badge.innerHTML = `${iconSvg} ${totalQty}`;
  }

  // 2. Cập nhật Preview List
  const preview = card.querySelector('.package-items-preview');
  if (preview) {
    if (!packageData.items || packageData.items.length === 0) {
      preview.innerHTML = `<div class="preview-empty" style="text-align: center; color: #adb5bd; font-style: italic; padding: 0.5rem;">Chưa có chi tiết sản phẩm</div>`;
    } else {

      const aggregatedItems = {};

      packageData.items.forEach(item => {
        const qty = parseFloat(item.qty_done) || 0;
        if (qty <= 0) return;

        // --- CÁCH MỚI: LẤY MÃ TỪ DATA ATTRIBUTE (SẠCH & CHUẨN) ---
        let displayName = item.product_name || '';

        // Tìm dòng sản phẩm bên trái để lấy data-default-code
        const lineEl = document.querySelector(`#product_list .product-item[data-line-id="${item.move_line_id}"]`);

        if (lineEl) {
          // Lấy mã nội bộ trực tiếp từ attribute chúng ta vừa thêm ở XML
          const defaultCode = lineEl.getAttribute('data-default-code');

          // Nếu có mã và tên chưa có [...] thì ghép vào
          if (defaultCode && !displayName.startsWith('[')) {
            displayName = `[${defaultCode}] ${displayName}`;
          }
        }
        // Fallback: Nếu không tìm thấy DOM (hiếm), giữ nguyên tên gốc

        // Cộng dồn
        if (aggregatedItems[displayName]) {
          aggregatedItems[displayName] += qty;
        } else {
          aggregatedItems[displayName] = qty;
        }
      });


      console.log('786', aggregatedItems);


      let html = '';
      for (const [name, qty] of Object.entries(aggregatedItems)) {
        html += `
          <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center;">
            <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057; font-size: 0.85rem;">${name}</span>
            <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">x${qty}</span>
          </div>
        `;
      }
      preview.innerHTML = html;
    }
  }
}


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

    // Xử lý các trường null/undefined
    if (!Array.isArray(currentPackageData.other_packages)) {
      currentPackageData.other_packages = [];
    }

    // Cập nhật Tiêu đề Modal
    const titleEl = document.getElementById('modalPackageName');
    if (titleEl) titleEl.innerText = result.package_name;

    // ============================================================
    // BƯỚC 1: GỘP CÁC DÒNG TRÙNG SẢN PHẨM (AGGREGATION)
    // ============================================================
    const aggregatedMap = {};

    result.items.forEach(item => {
      // Dùng product_id để định danh sản phẩm trùng
      const key = item.product_id || item.product_name;

      if (aggregatedMap[key]) {
        // Đã có -> Cộng dồn số lượng
        aggregatedMap[key].qty_done += parseFloat(item.qty_done) || 0;
        // move_line_id giữ nguyên của dòng đầu tiên để làm ID đại diện thao tác
      } else {
        // Chưa có -> Tạo mới (Clone object để không ảnh hưởng data gốc)
        aggregatedMap[key] = { ...item };
        aggregatedMap[key].qty_done = parseFloat(item.qty_done) || 0;
      }
    });

    // Chuyển Map thành Mảng để render
    const mergedItems = Object.values(aggregatedMap);

    // Cập nhật Badge số lượng loại sản phẩm (Unique products)
    const badgeEl = document.getElementById('itemCountBadge');
    if (badgeEl) badgeEl.innerText = mergedItems.length;

    // ============================================================
    // BƯỚC 2: RENDER DANH SÁCH ĐÃ GỘP
    // ============================================================
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

          // [FIX NAME] Logic hiển thị tên có [Barcode] trong Modal
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
              <button class="action-btn action-remove" data-move-line-id="${item.move_line_id}" title="Xóa sản phẩm">Xóa</button>
              <button class="action-btn action-transfer" data-move-line-id="${item.move_line_id}" title="Chuyển sản phẩm">Chuyển</button>
            </div>
          `;

          // --- GÁN SỰ KIỆN NÚT BẤM (GIỮ NGUYÊN LOGIC CŨ) ---

          // 1. Decrease
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

          // 3. Remove
          li.querySelector('.action-remove').addEventListener('click', async () => {
            if (confirm('Bạn chắc chắn muốn xoá sản phẩm này khỏi gói?')) {
              await removePackageItem(item.move_line_id);
            }
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
        // 1. Giảm số lượng hiển thị (Done)
        // 1. Giảm số lượng hiển thị (Done)
        const doneInput = mainListEl.querySelector('.done-input');
        const doneEl = mainListEl.querySelector('.done');

        const currentDone = parseFloat(doneInput ? doneInput.value : (doneEl?.innerText || 0));
        // LOGIC CŨ: newDone = currentDone - qtyToRemove; -> Sai vì bây giờ UNPACK chứ không XÓA
        // LOGIC MỚI: newDone giữ nguyên (vì hàng nhả ra khỏi pack vẫn tính là Done)
        // Chỉ giảm data-packed-qty

        const newDone = currentDone; // Keep done count same


        /* 
           Tuy nhiên, UI cần phản hồi gì?
           "Đã đóng gói" (data-packed-qty) GIẢM.
           "Đã quét" (value input) GIỮ NGUYÊN.
        */

        // 2. Giảm số lượng "Đã đóng gói" (Packed Qty - dữ liệu ẩn)
        const currentPacked = parseFloat(mainListEl.getAttribute('data-packed-qty') || 0);
        const newPacked = Math.max(0, currentPacked - qtyToRemove);
        mainListEl.setAttribute('data-packed-qty', newPacked);

        // [OPTIONAL] Nếu muốn hiển thị rõ hơn, có thể flash màu khác


        // 3. Cập nhật màu sắc (xanh/đen)
        const requiredEl = mainListEl.querySelectorAll('span')[1];
        const required = parseFloat(requiredEl?.innerText || 0);
        if (newDone >= required && required > 0) {
          mainListEl.classList.add("completed");
        } else {
          mainListEl.classList.remove("completed");
        }

        // Highlight nhẹ dòng vừa update để user dễ thấy
        highlightElement(mainListEl, "#ffc9c9"); // Reddish for removal
      }
    }

    // Render lại modal
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

      // A. Tìm dòng ở màn hình chính theo ID
      let mainListEl = document.querySelector(`#product_list .product-item[data-line-id="${strLineId}"]`);

      // B. Nếu không tìm thấy theo ID (do Odoo tách dòng), tìm theo Tên sản phẩm
      if (!mainListEl && currentPackageData?.items) {
        const itemDetail = currentPackageData.items.find(i => String(i.move_line_id) === strLineId);
        if (itemDetail) {
          const allItems = document.querySelectorAll('#product_list .product-item');
          for (const el of allItems) {
            const nameEl = el.querySelector('strong');
            if (nameEl && nameEl.innerText.includes(itemDetail.product_name)) {
              mainListEl = el;
              break;
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
        const newDone = Math.max(0, currentDone + delta);

        if (doneInput) {
          doneInput.value = newDone;
          doneInput.dataset.currentQty = newDone; // Sync for safety
        } else if (doneEl) {
          doneEl.innerText = newDone;
        }

        // 2. Cập nhật số lượng đã đóng gói ngầm (Packed Qty)
        // Phải cập nhật cái này để lần sau quét thêm nó tính toán đúng
        const currentPacked = parseFloat(mainListEl.getAttribute('data-packed-qty') || 0);
        mainListEl.setAttribute('data-packed-qty', Math.max(0, currentPacked + delta));

        // 3. Check lại trạng thái completed (Màu xanh)
        const requiredEl = mainListEl.querySelectorAll('span')[1];
        const required = parseFloat(requiredEl?.innerText || 0);

        if (newDone >= required && required > 0) mainListEl.classList.add("completed");
        else mainListEl.classList.remove("completed");

        // Hiệu ứng nháy vàng để báo hiệu đã update thành công
        highlightElement(mainListEl, "#ffd43b");
      } else {
        console.warn("⚠️ Không tìm thấy dòng sản phẩm bên ngoài để update ID:", change.moveLineId);
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
                // Lấy số hiện tại (bỏ chữ x đi)
                const currentQtyVal = parseFloat(qtyEl.innerText.toLowerCase().replace('x', '')) || 0;
                const newTotalQty = currentQtyVal + qty;

                // Cập nhật số lượng mới (Format: xSố)
                qtyEl.innerText = `x${newTotalQty}`;

                // Cập nhật luôn cái tên chuẩn (có barcode) cho dòng cũ
                const nameEl = foundItem.querySelector('.preview-item-name');
                nameEl.innerText = finalName;

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
  // HELPER: Hàm lấy tên chuẩn [Barcode] Tên và cập nhật data ẩn
  // ============================================================
  const getProductInfo = (item) => {
    const lineEl = document.querySelector(`[data-line-id="${item.move_line_id}"]`);
    let finalName = 'Sản phẩm...';

    if (lineEl) {
      // Cập nhật packed-qty ẩn
      const currentPacked = parseFloat(lineEl.getAttribute('data-packed-qty') || 0);
      lineEl.setAttribute('data-packed-qty', currentPacked + item.qty);

      // Logic lấy tên và barcode
      const rawName = lineEl.querySelector('strong')?.innerText.trim() || '';
      const barcode = lineEl.getAttribute('data-barcode') || '';

      if (rawName && !rawName.startsWith('[') && barcode) {
        finalName = `[${barcode}] ${rawName}`;
      } else {
        finalName = rawName || finalName;
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
          const oldQty = parseFloat(qtyEl.innerText.replace('x', '')) || 0;
          qtyEl.innerText = `x${oldQty + item.qty}`;
          console.log('1541', foundRow);

          // Nháy màu
          foundRow.style.transition = 'background 0.3s';
          foundRow.style.backgroundColor = '#fff3cd';
          setTimeout(() => foundRow.style.backgroundColor = 'transparent', 500);
        } else {
          console.log('1555', name);

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