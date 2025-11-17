document.addEventListener("DOMContentLoaded", function () {

  // Toast helper (tự tạo host nếu thiếu)
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

        playSuccess(); setFocus();
      });

  }

  input?.addEventListener("keypress", function (e) {
    if (e.key !== "Enter") return;
    const raw = input.value.trim();
    if (!raw) return;

    // nếu trùng tên pick để auto hoàn tất
    if (typeof originPickName !== 'undefined' && raw === originPickName) {
      completeBtn?.click();
      input.value = "";
      return;
    }

    // mapping: nếu quét “key” thì cộng 0.1 vào barcode mục tiêu
    const targetBarcode = BARCODE_MAP_POINT_ONE[raw];
    if (targetBarcode) {
      updateQty(targetBarcode, 0.1);
    } else if (isProductBarcode(raw)) {
      updateQty(raw, 1);
    } else {
      handlePackageBarcode(raw);
    }

    input.value = "";
  });

  function isProductBarcode(barcode) {
    const exists = [...document.querySelectorAll('[data-barcode]')]
      .some(el => normalizeCode(el.dataset.barcode) === normalizeCode(barcode));
    return exists;
  }

  async function handlePackageBarcode(packageBarcode) {
    const items = document.querySelectorAll("#product_list .product-item");
    const completedItems = [];
    items.forEach(item => {
      const doneEl = item.querySelector(".done");
      const requiredEl = item.querySelectorAll("span")[1];
      const done = parseFloat(doneEl?.innerText || 0);
      const required = parseFloat(requiredEl?.innerText || 0);
      const lineId = item.dataset.lineId;
      if (done >= required && required > 0) {
        completedItems.push({ move_line_id: parseInt(lineId), qty: done });
      }
    });
    if (completedItems.length === 0) {
      toast.warn("⚠️ Không có sản phẩm nào hoàn tất để tạo kiện", { ms: 2500 });
      playError();
      setFocus();
      return;
    }
    try {
      const res = await fetch("/pack_scan/create_partial_pack", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "call",
          params: { picking_id: pickingId, package_barcode: packageBarcode, move_line_data: completedItems }
        })
      });
      const response = await res.json();
      const result = response.result || response;
      console.log("API Response:", response);
      console.log("Result:", result);
      if (result?.error) {
        toast.error("❌ " + result.error, { ms: 2500 });
        playError();
        setFocus();
        return;
      }
      if (!result?.success) {
        toast.error("❌ API response không hợp lệ: " + JSON.stringify(result), { ms: 2500 });
        playError();
        setFocus();
        return;
      }
      toast.success(`✅ Tạo gói hàng ${result.package_name} thành công! ${completedItems.length} sản phẩm`, { ms: 2000 });
      playSuccess();
      // Reload để hiển thị các move_line đã được gán vào package
      setTimeout(() => { window.location.reload(); }, 1500);
    } catch (err) {
      toast.error("❌ Lỗi kết nối: " + err.message, { ms: 2500 });
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
      toast.warn("❌ Chưa quét đủ:\n- " + missingProducts.join("\n- "), { ms: 3500 });
      return;
    }


    const res = await fetch("/pack_scan/complete_picking", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { picking_id: pickingId } })
    });
    const response = await res.json();
    if (response.error || response.result?.error) {
      const msg = response.error?.message || response.result?.error || "❌ Có lỗi xảy ra!";
      toast.error(msg, { ms: 1800 })

      return;
    }

    // dừng ghi (sẽ tự upload trong onstop)
    await stopRecording();

    toast.success("✅ Phiếu đã hoàn tất! Đang chuyển trang...", { ms: 1200 });
    setTimeout(() => { window.location.href = "/custom_barcode_scan/ui"; }, 600);
  });

  const btnSwitch = document.getElementById('btnDriveSwitch');
  if (btnSwitch) {
    btnSwitch.addEventListener('click', () => {
      // mở tab mới để disconnect + start OAuth
      window.open('/gdrive/oauth2/disconnect', '_blank', 'noopener');
    });
  }

  // Nút Partial Pack - tạo kiện tự động từ sản phẩm hoàn tất
  document.getElementById('btnPartialPack')?.addEventListener('click', function() {
    const autoPackageBarcode = `AUTO-PKG-${Date.now()}`;
    handlePackageBarcode(autoPackageBarcode);
  });

  // Nút In nhãn
  document.getElementById('btnPrintLabel')?.addEventListener('click', async function() {
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
// ======


let uploadId = null;
let chunkIndex = 0;
// let chunkBusy = Promise.resolve();
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
  if (!uploadId) return;  // chưa start thì bỏ qua

  try {
    await fetch('/pack_scan/finish_upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      // keepalive để vẫn gửi khi tab đóng
      keepalive: true,
      body: JSON.stringify({ upload_id: uploadId, picking_id: pickingId })
    });
  } finally {
    uploadId = null;
  }
}

// ====== Recording module ======
// ====== Recording module (đổi toàn bộ block này) ======
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

  // 1) getUserMedia (ưu tiên có audio, fail thì tắt audio)
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

  // 2) Chuẩn bị canvas overlay & vẽ NGAY (tránh màn hình đen)
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

  // set end time & bắt đầu đếm ngược ngay
  endAt = Date.now() + MAX_DURATION_MS;
  updateCountdownLabel();
  clearInterval(countdownTimer);
  countdownTimer = setInterval(updateCountdownLabel, 500);

  function drawOverlay() {
    if (!overlayCtx) return;
    overlayCtx.drawImage(rawVideo, 0, 0, W, H);

    // dải nền + text
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
  drawOverlay(); // ← vẽ ngay để preview có khung hình

  // 3) stream từ canvas + audio để preview & ghi
  const canvasStream = overlayCanvas.captureStream(24);
  const tracks = [canvasStream.getVideoTracks()[0]];
  const a = mediaStream.getAudioTracks()[0];
  if (a) tracks.push(a);
  const mixedStream = new MediaStream(tracks);

  preview.srcObject = mixedStream;
  try { await preview.play(); } catch { }

  // 4) khởi tạo phiên upload
  await startServerUploadSession();

  // 5) MediaRecorder
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
    mediaRecorder.start(5000); // chia chunk 5s
  } catch (err) {
    console.error('[REC] mediaRecorder.start failed:', err);
    statusText.textContent = 'Không thể bắt đầu ghi hình.';
  }
}

function stopRecording() {
  if (mediaRecorder && isRecording) { try { mediaRecorder.stop(); } catch { } }
}


async function uploadRecording() {
  if (!recordedChunks.length) return;
  const blob = new Blob(recordedChunks, { type: recordedChunks[0].type || 'video/webm' });
  const fileName = `PACK_${parseInt(window.location.pathname.split("/").pop())}_${Date.now()}.webm`;

  if (blob.size > 24 * 1024 * 1024) {
    console.warn('[REC] blob ~', (blob.size / 1024 / 1024).toFixed(1), 'MB');
  }

  const formData = new FormData();
  formData.append('file', blob, fileName);
  formData.append('picking_id', String(parseInt(window.location.pathname.split("/").pop())));

  try {
    const resp = await fetch('/pack_scan/upload_video', {
      method: 'POST',
      body: formData,
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });
    const txt = await resp.text().catch(() => '');
    if (!resp.ok) {
      if (resp.status === 413) toast.error('Video quá lớn (413). Hãy quay ngắn hơn/hạ chất lượng.', { ms: 4000 });
      else toast.error(`Tải video lên thất bại (${resp.status}). ${txt || ''}`, { ms: 4000 });
    } else {
      toast.success('Đã tải video lên.', { ms: 1800 });
    }

  } catch (e) {
    console.error('[REC] upload error:', e);
    // alert('Không thể tải video lên. Kiểm tra mạng.');
    toast.error('Không thể tải video lên. Kiểm tra mạng.', { ms: 3500 });

  } finally {
    recordedChunks = [];
  }
}

function attachRetryButton() {
  if (document.getElementById('recRetryBtn')) return;
  const btn = document.createElement('button');
  btn.id = 'recRetryBtn';
  btn.textContent = '🔁 Thử bật camera lại';
  btn.style.marginLeft = '8px';
  btn.addEventListener('click', startRecording);
  const recText = document.getElementById('recText');
  recText?.parentNode?.insertBefore(btn, recText.nextSibling);
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

// ===================== PARTIAL PACK MANAGEMENT =====================
// Hàm tạo modal dialog
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

// In nhãn
document.getElementById('btnPrintLabel')?.addEventListener('click', async function() {
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

// Action buttons cho sibling packs
document.addEventListener('click', async function(e) {
  const unpackBtn = e.target.closest('.btn-unpack');
  const editBtn = e.target.closest('.btn-edit');
  const transferBtn = e.target.closest('.btn-transfer');
  
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
        setTimeout(() => window.location.reload(), 1000);
      } else {
        toast.error(result?.error || 'Unpack thất bại', { ms: 2000 });
      }
    }
  }
  
  if (editBtn) {
    const packId = parseInt(editBtn.dataset.packId);
    // Mở trang edit của pack đó
    window.location.href = `/custom_barcode_scan/pack_view/${packId}`;
  }
  
  if (transferBtn) {
    const sourcePack = parseInt(transferBtn.dataset.packId);
    const targetPack = pickingId;
    
    createModal(
      '↔️ Chuyển sản phẩm',
      'Tính năng chuyển sản phẩm giữa các pack. Chọn sản phẩm để chuyển.',
      [
        {
          label: 'Hủy',
          color: '#999',
          onclick: () => {}
        },
        {
          label: 'Chuyển',
          color: '#ffa500',
          onclick: async () => {
            toast.info('Tính năng này sẽ được hoàn thiện trong phiên bản tiếp theo', { ms: 2000 });
          }
        }
      ]
    );
  }
});