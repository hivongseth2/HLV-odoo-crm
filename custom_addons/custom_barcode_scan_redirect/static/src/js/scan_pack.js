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

  const BARCODE_MAP_POINT_ONE = {
    "452424752161": "45242475216",//4361
    "452424752301": "45242475230", //4364
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

      if (result?.error) { toast.error(result.error); playError(); setFocus(); return; }
      if (!result?.scanned?.length) { toast.warn('Không có dòng nào được cập nhật'); playError(); setFocus(); return; }

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

        const doneEl = el.querySelector('.done');
        const requiredEl = el.querySelectorAll('span')[1];
        const required = parseFloat((requiredEl?.innerText || '0').replace(',', '.')) || 0;

        doneEl.innerText = item.done_qty;
        if (item.done_qty >= required) el.classList.add("completed");
        else el.classList.remove("completed");
      });

    } catch (err) {
      toast.error("Lỗi kết nối: " + err.message);
      playError();
      setFocus();
    }
  }

  list?.querySelectorAll(".btn-plus").forEach(btn =>
    btn.addEventListener("click", () =>
      updateQty(btn.dataset.barcode, 1, btn.dataset.lineId)
    )
  );
  list?.querySelectorAll(".btn-minus").forEach(btn =>
    btn.addEventListener("click", () =>
      updateQty(btn.dataset.barcode, -1, btn.dataset.lineId)
    )
  );

  completeBtn?.addEventListener("click", async function () {
    const items = document.querySelectorAll("#product_list .product-item");
    let isValid = true, missingProducts = [];
    items.forEach(item => {
      const name = item.querySelector("strong").innerText;
      const doneEl = item.querySelector(".done");
      const spanEls = item.querySelectorAll("span");
      const done = parseFloat(doneEl?.innerText || 0);
      const required = parseFloat(spanEls[1]?.innerText || 0);
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
    }
    toast.info(`Mã barcode tạo: ${autoPackageBarcode}`, { ms: 4000 });
  });

  // Handle Barcode Input (Enter/Scan)
  input?.addEventListener("keypress", async function (event) {

    // Only process when Enter key is pressed
    if (event.key !== "Enter" && event.keyCode !== 13) return;
    const barcode = this.value.trim();
    if (!barcode) return;
    this.value = ""; // Clear input

    // --- LOGIC MỚI: Quét mã 'createpacked' để tự động đóng gói ---
    if (barcode === 'CMD-CREATE-PACK') {
      const autoPackageBarcode = `AUTO-PKG-${Date.now()}`;

      const items = [];
      document.querySelectorAll("#product_list .product-item").forEach(el => {
        const lineId = parseInt(el.dataset.lineId);
        const done = parseFloat(el.querySelector(".done")?.innerText || 0);
        if (lineId && done > 0) {
          items.push({ move_line_id: lineId, qty: done });
        }
      });

      if (items.length === 0) {
        toast.warn("Chưa có sản phẩm nào được quét để đóng gói!");
        playError();
        return;
      }

      try {
        toast.info(`Đang tạo gói hàng tự động: ${autoPackageBarcode}...`, { ms: 2000 });
        const res = await fetch('/pack_scan/create_partial_pack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          body: JSON.stringify({
            jsonrpc: '2.0',
            method: 'call',
            params: {
              picking_id: pickingId,
              move_line_data: items,
              package_barcode: autoPackageBarcode
            }
          })
        });
        const response = await res.json();
        const result = response.result || response;

        if (result?.success) {
          toast.success(result.message);
          playSuccess();
          // Reload to reflect changes
          setTimeout(() => window.location.reload(), 1000);
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
    // -----------------------------------------------------------

    // 1. Check if it is a Package Creation Barcode (Manual scan of generated code)
    if (barcode.startsWith("AUTO-PKG-") || barcode.startsWith("PACK")) {
      const items = [];
      document.querySelectorAll("#product_list .product-item").forEach(el => {
        const lineId = parseInt(el.dataset.lineId);
        const done = parseFloat(el.querySelector(".done")?.innerText || 0);
        if (lineId && done > 0) {
          items.push({ move_line_id: lineId, qty: done });
        }
      });

      if (items.length === 0) {
        toast.warn("Chưa có sản phẩm nào được quét để đóng gói!");
        playError();
        return;
      }

      try {
        const res = await fetch('/pack_scan/create_partial_pack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          body: JSON.stringify({
            jsonrpc: '2.0',
            method: 'call',
            params: {
              picking_id: pickingId,
              move_line_data: items,
              package_barcode: barcode
            }
          })
        });
        const response = await res.json();
        const result = response.result || response;

        if (result?.success) {
          toast.success(result.message);
          playSuccess();
          // Reload to reflect changes (items moved to package)
          setTimeout(() => window.location.reload(), 1000);
        } else {
          toast.error(result?.error || "Lỗi tạo gói hàng");
          playError();
        }
      } catch (e) {
        toast.error("Lỗi kết nối: " + e.message);
        playError();
      }

    } else {
      // 2. Normal Product Scanning
      await updateQty(barcode);
    }
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

const MAX_DURATION_MS = 5 * 60 * 1000; // 5 phút
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

  // Update Qty Badge
  const badge = card.querySelector('.badge');
  if (badge) {
    const totalQty = (packageData.items || []).reduce((sum, item) => sum + (parseFloat(item.qty_done) || 0), 0);
    badge.innerHTML = `
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 0 0 1-8 0"></path></svg>
      ${totalQty}
    `;
  }

  // Update Preview List
  const preview = card.querySelector('.package-items-preview');
  if (preview) {
    if (!packageData.items || packageData.items.length === 0) {
      preview.innerHTML = `<div class="preview-empty" style="text-align: center; color: #adb5bd; font-style: italic; padding: 0.5rem;">Chưa có chi tiết sản phẩm</div>`;
    } else {
      let html = '';
      // Group items by product name to match the preview style if needed, 
      // but listing items is also fine.
      packageData.items.forEach(item => {
        if (item.qty_done > 0) {
          html += `
            <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center;">
              <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057;">${item.product_name}</span>
              <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">x${item.qty_done}</span>
            </div>
          `;
        }
      });
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

    // Ensure other_packages is an array
    if (!Array.isArray(currentPackageData.other_packages)) {
      currentPackageData.other_packages = [];
    }

    // ⭐ DEBUG: Log để kiểm tra structure
    console.log('✅ Package data loaded:', {
      package_id: currentPackageData.package_id,
      package_name: currentPackageData.package_name,
      items_count: currentPackageData.items?.length || 0,
      other_packages_count: currentPackageData.other_packages?.length || 0,
      other_packages_detail: currentPackageData.other_packages,
      all_items_count: currentPackageData.all_items?.length || 0,
      all_items_detail: currentPackageData.all_items
    });

    document.getElementById('modalPackageName').innerText = result.package_name;

    const itemCountBadge = document.getElementById('itemCountBadge');
    if (itemCountBadge) {
      itemCountBadge.innerText = result.items.length;
    }

    const itemsList = document.getElementById('packageItemsList');
    itemsList.innerHTML = '';

    if (result.items.length === 0) {
      itemsList.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">📦</div>
          <h4 class="empty-title">Chưa có sản phẩm nào</h4>
          <p class="empty-desc">Thêm sản phẩm để quản lý gói hàng</p>
        </div>
      `;
    } else {
      // Deduplicate items by move_line_id
      const uniqueById = {};
      result.items.forEach(it => {
        const key = String(it.move_line_id);
        if (!uniqueById[key]) {
          uniqueById[key] = it;
        }
      });
      const uniqueItems = Object.values(uniqueById);

      uniqueItems.forEach(item => {
        const li = document.createElement('div');
        li.className = 'item-card';
        li.setAttribute('data-move-line-id', item.move_line_id);
        li.innerHTML = `
          <div class="item-info">
            <div class="item-details">
              <h4 class="item-name">${item.product_name}</h4>
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

        // Qty decrease button
        li.querySelector('.qty-decrease').addEventListener('click', () => {
          const display = li.querySelector('.qty-display');
          const cur = parseFloat(display.innerText) || 0;
          const newQty = Math.max(0, cur - 1);
          display.innerText = String(newQty);
          if (currentPackageData && Array.isArray(currentPackageData.items)) {
            const foundItem = currentPackageData.items.find(i => Number(i.move_line_id) === Number(item.move_line_id));
            if (foundItem) foundItem.qty_done = newQty;
          }
        });

        // Qty increase button
        li.querySelector('.qty-increase').addEventListener('click', () => {
          const display = li.querySelector('.qty-display');
          const cur = parseFloat(display.innerText) || 0;

          // Get original move item data to check max allowed
          const orig = currentPackageData.items.find(i => Number(i.move_line_id) === Number(item.move_line_id));
          if (!orig) return;

          // Get the original qty_done before package (stored in data)
          const oldQtyStored = parseFloat(display.dataset.oldQty) || 0;

          // Calculate total available qty for this product from all move_lines
          const allProductItems = currentPackageData.all_items || [];
          const availableItems = allProductItems.filter(i => i.product_name === item.product_name);
          let totalAvailable = 0;
          availableItems.forEach(ai => {
            totalAvailable += ai.qty_available || 0;
          });

          // Calculate current qty in all packages for this product
          const currentPackageItems = currentPackageData.items || [];
          let totalInPackages = 0;
          currentPackageItems.forEach(ci => {
            if (ci.product_name === item.product_name) {
              totalInPackages += parseFloat(ci.qty_done) || 0;
            }
          });

          // Calculate max allowed for this item
          const maxAllowed = totalAvailable;
          const currentTotalForProduct = totalInPackages + (cur - oldQtyStored);

          if (currentTotalForProduct >= maxAllowed) {
            toast.warn(`Không thể tăng thêm. Đã đạt giới hạn tối đa (${maxAllowed}) cho sản phẩm này`, { ms: 2000 });
            return;
          }

          const newQty = cur + 1;
          display.innerText = String(newQty);
          if (currentPackageData && Array.isArray(currentPackageData.items)) {
            const foundItem = currentPackageData.items.find(i => Number(i.move_line_id) === Number(item.move_line_id));
            if (foundItem) foundItem.qty_done = newQty;
          }
        });

        // Remove button
        li.querySelector('.action-remove').addEventListener('click', async () => {
          if (confirm('Bạn chắc chắn muốn xoá sản phẩm này khỏi gói?')) {
            await removePackageItem(item.move_line_id);
          }
        });

        // Transfer button - chuyển sản phẩm sang pack khác
        li.querySelector('.action-transfer').addEventListener('click', (ev) => {
          ev.stopPropagation();
          const display = li.querySelector('.qty-display');
          const currentQty = parseFloat(display.innerText) || item.qty_done;
          openTransferModalForItem(item.move_line_id, currentQty, item.product_name);
        });

        itemsList.appendChild(li);
      });
    }

    // Populate add item select
    const addItemSelect = document.getElementById('addItemSelect');
    addItemSelect.innerHTML = '<option value="">-- Chọn sản phẩm --</option>';

    if (result.all_items && result.all_items.length > 0) {
      result.all_items.forEach(item => {
        const option = document.createElement('option');
        option.value = item.move_line_id;
        option.innerText = `${item.product_name} (Còn: ${item.qty_available})`;
        addItemSelect.appendChild(option);
      });
    }

    // Show modal
    const modal = document.getElementById('packageEditModal');
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';

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

    toast.success("Đã xoá sản phẩm!", { ms: 1500 });
    openPackageEditModal({ currentTarget: { dataset: { packageId: currentPackageData.package_id } }, stopPropagation: () => { } });

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

  for (let display of displayElements) {
    const moveLineId = parseInt(display.dataset.moveLineId);
    const newQty = parseFloat(display.innerText);
    const oldQty = parseFloat(display.dataset.oldQty);

    if (!isNaN(newQty) && !isNaN(oldQty) && newQty !== oldQty) {
      hasChanges = true;
      changes.push({ moveLineId, newQty });
    }
  }

  if (!hasChanges) {
    toast.info("Không có thay đổi nào");
    return;
  }

  // Send all changes
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

    } catch (err) {
      toast.error("Lỗi kết nối: " + err.message);
      return;
    }
  }

  toast.success("Đã lưu thay đổi!", { ms: 1500 });
  updateSidePanelUI(currentPackageData);
  closePackageEditModal();
}

// COMMENTED OUT: Split package functionality (tách gói thành đơn riêng)
// async function splitPackageFromModal() {
//   console.warn('splitPackageFromModal is disabled - feature under development');
//   toast.info('Tách gói tạm thời chưa khả dụng.', { ms: 2000 });
// }

function openTransferModalForItem(moveLineId, currentQty, productName) {
  console.log('🔍 openTransferModalForItem called:', {
    currentPackageData: currentPackageData,
    moveLineId: moveLineId,
    currentQty: currentQty,
    productName: productName
  });

  const packs = (currentPackageData && currentPackageData.other_packages) || [];
  console.log('📦 Available packs:', packs);

  // ⭐ Validate packages data structure
  if (!packs.length) {
    toast.warn('Không có gói mục tiêu để chuyển. Vui lòng tạo gói khác trước.');
    return;
  }

  // ⭐ Check xem packages có đúng structure không
  const invalidPacks = packs.filter(p => !p.package_id || !p.package_name);
  if (invalidPacks.length > 0) {
    console.error('❌ Invalid package structure detected:', invalidPacks);
    console.error('📦 Full packages data:', packs);
    toast.error('Lỗi: Dữ liệu package không hợp lệ. Vui lòng reload trang.');
    return;
  }

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

  createModal('↔️ Chuyển sản phẩm sang gói khác', content, [
    { label: 'Hủy', color: '#6b7280', onclick: () => { } },
    {
      label: 'Chuyển', color: '#0ea5e9', onclick: async () => {
        const targetPack = document.getElementById('transferTargetSelect').value;
        const qty = parseFloat(document.getElementById('transferQtyInput').value);

        console.log('📤 Transfer request:', { targetPack, qty, moveLineId });

        // ⭐ Validate input
        if (!targetPack) {
          toast.warn('Vui lòng chọn gói đích');
          return;
        }

        if (!qty || qty <= 0) {
          toast.warn('Vui lòng nhập số lượng hợp lệ');
          return;
        }

        if (qty > currentQty) {
          toast.warn(`Số lượng không được vượt quá ${currentQty}`);
          return;
        }

        try {
          const pickingId = parseInt(window.location.pathname.split("/").pop());

          console.log('📤 Sending transfer request:', {
            picking_id: pickingId,
            source_package_id: currentPackageData.package_id,
            target_package_id: parseInt(targetPack),
            move_line_id: parseInt(moveLineId),
            qty: qty
          });

          const res = await fetch('/pack_scan/transfer_item_between_packs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify({
              jsonrpc: '2.0',
              method: 'call',
              params: {
                picking_id: pickingId,
                source_package_id: currentPackageData.package_id,
                target_package_id: parseInt(targetPack),
                move_line_id: parseInt(moveLineId),
                qty: qty
              }
            })
          });

          const response = await res.json();
          console.log('📥 Transfer response:', response);

          const result = response.result || response;
          if (result?.error) {
            toast.error(result.error);
            return;
          }

          toast.success(result.message || 'Đã chuyển sản phẩm!', { ms: 1500 });

          // Refresh modal
          openPackageEditModal({
            currentTarget: { dataset: { packageId: currentPackageData.package_id } },
            stopPropagation: () => { }
          });
        } catch (err) {
          console.error('❌ Transfer error:', err);
          toast.error('Lỗi kết nối: ' + err.message);
        }
      }
    }
  ]);
}

// ===================== PANEL VISIBILITY TOGGLE =====================
function togglePanelVisibility(button) {
  const panel = button.closest('.pack-side-panel');
  if (!panel) return;

  const isCollapsed = panel.classList.toggle('collapsed');
  button.textContent = isCollapsed ? 'Hiện' : 'Ẩn';
}