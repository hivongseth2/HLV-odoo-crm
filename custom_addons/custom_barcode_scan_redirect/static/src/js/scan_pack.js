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

    // C. LOGIC MỚI: Xử lý mã lệnh tạo gói (CMD-CREATE-PACK hoặc AUTO-PKG-...)
    if (barcode === 'CMD-CREATE-PACK' || barcode.startsWith("AUTO-PKG-") || barcode.startsWith("PACK")) {

      // 1. Thu thập các dòng đã quét (qty > 0) ở danh sách bên trái
      const items = [];
      document.querySelectorAll("#product_list .product-item").forEach(el => {
        const lineId = parseInt(el.dataset.lineId);
        const currentDone = parseFloat(el.querySelector(".done")?.innerText || 0);
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

        // --- NÚT GIẢM SỐ LƯỢNG (FIX LỖI CỘNG DỒN) ---
        li.querySelector('.qty-decrease').addEventListener('click', () => {
          const display = li.querySelector('.qty-display');
          let cur = parseFloat(display.innerText) || 0;

          // Logic chuẩn: Lấy số hiện tại TRỪ đi 1 (tối thiểu là 0)
          const newQty = Math.max(0, cur - 1);

          display.innerText = String(newQty);

          // Cập nhật dữ liệu vào biến tạm
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
            toast.warn(`Không thể tăng thêm. Đã đạt giới hạn tối đa cho sản phẩm này, vui lòng quét thêm sản phẩm nếu muốn tăng thêm`, { ms: 2000 });
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
        const doneEl = mainListEl.querySelector('.done');
        const currentDone = parseFloat(doneEl.innerText || 0);
        const newDone = Math.max(0, currentDone - qtyToRemove);
        doneEl.innerText = newDone;

        // 2. Giảm số lượng "Đã đóng gói" (Packed Qty - dữ liệu ẩn)
        const currentPacked = parseFloat(mainListEl.getAttribute('data-packed-qty') || 0);
        const newPacked = Math.max(0, currentPacked - qtyToRemove);
        mainListEl.setAttribute('data-packed-qty', newPacked);

        // 3. Cập nhật màu sắc (xanh/đen)
        const requiredEl = mainListEl.querySelectorAll('span')[1];
        const required = parseFloat(requiredEl?.innerText || 0);
        if (newDone >= required && required > 0) {
          mainListEl.classList.add("completed");
        } else {
          mainListEl.classList.remove("completed");
        }

        // Highlight nhẹ dòng vừa update để user dễ thấy
        mainListEl.style.backgroundColor = "#fff3cd";
        setTimeout(() => mainListEl.style.backgroundColor = "", 1000);
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
      // (Logic này cực quan trọng để fix lỗi bạn đang gặp)
      if (!mainListEl && currentPackageData?.items) {
        const itemDetail = currentPackageData.items.find(i => String(i.move_line_id) === strLineId);
        if (itemDetail) {
          const allItems = document.querySelectorAll('#product_list .product-item');
          for (const el of allItems) {
            const nameEl = el.querySelector('strong');
            // So sánh tên (dùng includes để khớp tương đối)
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
        const doneEl = mainListEl.querySelector('.done');
        const currentDone = parseFloat(doneEl.innerText || 0);
        const newDone = Math.max(0, currentDone + delta);
        doneEl.innerText = newDone;

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
        mainListEl.style.transition = "background 0.5s";
        mainListEl.style.backgroundColor = "#fff3cd";
        setTimeout(() => mainListEl.style.backgroundColor = "", 1000);
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
  const packs = (currentPackageData && currentPackageData.other_packages) || [];

  // Validate dữ liệu gói
  if (!packs.length) {
    toast.warn('Không có gói nào khác để chuyển sang.');
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

  createModal('↔️ Chuyển sản phẩm', content, [
    { label: 'Hủy', color: '#6b7280', onclick: () => { } },
    {
      label: 'Chuyển', color: '#0ea5e9', onclick: async () => {
        const targetPackSelect = document.getElementById('transferTargetSelect');
        const targetPackId = targetPackSelect.value;
        const targetPackName = targetPackSelect.options[targetPackSelect.selectedIndex].text;
        const qty = parseFloat(document.getElementById('transferQtyInput').value);

        // Validate input
        if (!targetPackId) { toast.warn('Vui lòng chọn gói đích'); return; }
        if (!qty || qty <= 0) { toast.warn('Vui lòng nhập số lượng hợp lệ'); return; }
        if (qty > currentQty) { toast.warn(`Số lượng không được vượt quá ${currentQty}`); return; }

        try {
          const pickingId = parseInt(window.location.pathname.split("/").pop());

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
          if (result?.error) { toast.error(result.error); return; }

          toast.success('Đã chuyển sản phẩm!', { ms: 1000 });

          // --- [FIX UI] 1. Cập nhật Gói Đích (Target Package) ở Side Panel ---
          const targetCard = document.querySelector(`.package-item-card[data-package-id="${targetPackId}"]`);
          if (targetCard) {
            // a. Cập nhật Badge số lượng của gói đích
            const badge = targetCard.querySelector('.badge');
            if (badge) {
              const currentTotal = parseFloat(badge.textContent.trim()) || 0;
              badge.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>
                ${currentTotal + qty}
              `;
            }

            // b. Thêm dòng Preview vào gói đích
            const previewContainer = targetCard.querySelector('.package-items-preview');
            if (previewContainer) {
              // Xóa "empty" text nếu có
              const emptyEl = previewContainer.querySelector('.preview-empty');
              if (emptyEl) emptyEl.remove();

              // Tạo html item mới
              const newItemHtml = `
                <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center; animation: fadeIn 0.5s;">
                  <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057;">${productName}</span>
                  <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #dbe4ff; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">+${qty}</span>
                </div>
               `;
              previewContainer.insertAdjacentHTML('afterbegin', newItemHtml);
            }

            // Hiệu ứng nháy sáng cho gói đích
            targetCard.style.transition = 'background-color 0.5s';
            targetCard.style.backgroundColor = '#e7f5ff';
            setTimeout(() => targetCard.style.backgroundColor = 'white', 1000);
          }

          // --- 2. Reload Modal Gói Nguồn (Source Package) ---
          // Hàm này sẽ tự động fetch lại data và cập nhật UI của gói hiện tại (Gói nguồn)
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

  // 2. Tính số lượng các sản phẩm VỪA MỚI quét thêm vào
  const newItemsQty = itemsData.reduce((sum, i) => sum + i.qty, 0);

  // 3. Tạo HTML cho các dòng sản phẩm mới (để dùng cho cả 2 trường hợp: thêm mới hoặc update)
  let previewHtml = '';
  itemsData.forEach(item => {
    // Cập nhật dữ liệu ngầm packedQty bên danh sách trái (để tính toán logic trừ lùi)
    const lineEl = document.querySelector(`[data-line-id="${item.move_line_id}"]`);
    let prodName = 'Sản phẩm...';

    if (lineEl) {
      const currentPacked = parseFloat(lineEl.getAttribute('data-packed-qty') || 0);
      lineEl.setAttribute('data-packed-qty', currentPacked + item.qty);
      prodName = lineEl.querySelector('strong')?.innerText || prodName;
    }

    previewHtml += `
        <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center;">
          <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057;">${prodName}</span>
          <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #dbe4ff; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">+${item.qty}</span>
        </div>
      `;
  });

  // --- [FIX] KIỂM TRA XEM GÓI NÀY ĐÃ CÓ TRÊN MÀN HÌNH CHƯA ---
  // Lưu ý: pkgId cần chuyển về string để so sánh chính xác trong selector
  const existingCard = document.querySelector(`.package-item-card[data-package-id="${pkgId}"]`);

  if (existingCard) {
    // === TRƯỜNG HỢP A: ĐÃ CÓ GÓI -> CẬP NHẬT (GỘP) ===

    // 1. Cập nhật Badge số lượng tổng
    const badge = existingCard.querySelector('.badge');
    if (badge) {
      // Lấy text hiện tại (VD: " 10"), xóa khoảng trắng, ép kiểu số
      // Clone node để lấy text thuần mà không lấy icon svg
      const currentText = badge.textContent.trim();
      const currentTotal = parseFloat(currentText) || 0;
      const updatedTotal = currentTotal + newItemsQty;

      badge.innerHTML = `
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>
          ${updatedTotal}
      `;
    }

    // 2. Chèn thêm dòng preview vào đầu danh sách cũ
    const previewContainer = existingCard.querySelector('.package-items-preview');
    if (previewContainer) {
      // Xóa thông báo "empty" nếu có
      const emptyPreview = previewContainer.querySelector('.preview-empty');
      if (emptyPreview) emptyPreview.remove();

      // Chèn nội dung mới lên đầu (prepend)
      previewContainer.insertAdjacentHTML('afterbegin', previewHtml);
    }

    // 3. Hiệu ứng nháy sáng báo hiệu vừa update
    existingCard.style.transition = 'background-color 0.5s ease';
    existingCard.style.backgroundColor = '#fff9db'; // Màu vàng nhạt
    setTimeout(() => { existingCard.style.backgroundColor = 'white'; }, 800);

    // 4. Di chuyển card lên đầu danh sách (để dễ thấy nhất)
    existingCard.parentElement.prepend(existingCard);

  } else {
    // === TRƯỜNG HỢP B: CHƯA CÓ GÓI -> TẠO MỚI ===

    // Nếu chưa có list container (đang empty state) thì tạo mới
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
    li.dataset.packageId = pkgId; // Gán ID để lần sau tìm thấy
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

    // Gán lại sự kiện click cho nút chỉnh sửa của thẻ mới
    li.querySelector('.btn-package-edit').addEventListener('click', openPackageEditModal);

    // Thêm thẻ mới vào đầu danh sách
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