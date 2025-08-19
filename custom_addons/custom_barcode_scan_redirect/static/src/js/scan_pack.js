document.addEventListener("DOMContentLoaded", function () {
  const input = document.getElementById("pack_barcode_input");
  const list = document.getElementById("product_list");
  const completeBtn = document.getElementById("complete_pack_btn");
  const pickingId = parseInt(window.location.pathname.split("/").pop());

  const BARCODE_MAP_POINT_ONE = {
    // "KEY_SCAN": "BARCODE_SPHAM"
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
        if (result?.error) { alert(result.error); playError(); setFocus(); return; }
        if (!result?.scanned?.length) { playError(); setFocus(); return; }

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


  // input?.addEventListener("keypress", function (e) {
  //   if (e.key === "Enter") {
  //     const val = input.value.trim();
  //     if (!val) return;
  //     if (typeof originPickName !== 'undefined' && val === originPickName) {
  //       completeBtn?.click();
  //       input.value = "";
  //       return;
  //     }

  //     console.log(val);

  //     updateQty(val);
  //     input.value = "";
  //   }
  // });


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
    } else {
      updateQty(raw, 1);
    }

    input.value = "";
  });

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
      alert("❌ Chưa quét đủ các sản phẩm sau:\n\n- " + missingProducts.join("\n- "));
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
      alert(msg); return;
    }

    // dừng ghi (sẽ tự upload trong onstop)
    await stopRecording();
    // alert(response.message || "✅ Phiếu đã hoàn tất!");
    // chờ 0.5s cho upload bắt đầu rồi hẵng rời trang
    setTimeout(() => { window.location.href = "/custom_barcode_scan/ui"; }, 600);
  });

  const btnSwitch = document.getElementById('btnDriveSwitch');
  if (btnSwitch) {
    btnSwitch.addEventListener('click', () => {
      // mở tab mới để disconnect + start OAuth
      window.open('/gdrive/oauth2/disconnect', '_blank', 'noopener');
    });
  }

  setFocus();
  diag();
  setTimeout(startRecording, 400);
});
// ======


let uploadId = null;
let chunkIndex = 0;
let chunkBusy = Promise.resolve();
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
let mediaStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let isRecording = false;
const MAX_DURATION_MS = 1 * 60 * 1000;
let stopTimer = null;

async function startRecording() {
  const statusDot = document.getElementById('recStatus');
  const statusText = document.getElementById('recText');
  const preview = document.getElementById('recPreview');
  if (!statusText || !preview) return;

  // 1) xin quyền camera
  const constraints = {
    video: { facingMode: { ideal: 'environment' }, width: { ideal: 640, max: 1280 }, height: { ideal: 360, max: 720 }, frameRate: { ideal: 20, max: 24 } },
    audio: { echoCancellation: true, noiseSuppression: true }
  };
  try {
    try { mediaStream = await navigator.mediaDevices.getUserMedia(constraints); }
    catch { mediaStream = await navigator.mediaDevices.getUserMedia({ video: constraints.video, audio: false }); }
  } catch (e) { statusText.textContent = 'Không thể mở camera.'; return; }
  preview.srcObject = mediaStream; try { await preview.play(); } catch { }

  // 2) khởi tạo phiên upload trên server
  await startServerUploadSession();

  // 3) chọn mime hợp lệ cho MediaRecorder
  let mimeType = '';
  if (MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')) mimeType = 'video/webm;codecs=vp9,opus';
  else if (MediaRecorder.isTypeSupported('video/webm;codecs=vp8,opus')) mimeType = 'video/webm;codecs=vp8,opus';
  else if (MediaRecorder.isTypeSupported('video/webm')) mimeType = 'video/webm';
  const mrOpts = mimeType ? { mimeType, videoBitsPerSecond: 900_000, audioBitsPerSecond: 64_000 } : {};

  // 4) bắt đầu ghi + đẩy CHUNK MỖI 5–10 GIÂY
  mediaRecorder = new MediaRecorder(mediaStream, mrOpts);
  recordedChunks = [];
  mediaRecorder.ondataavailable = (e) => {
    if (!e.data || !e.data.size) return;
    chunkBusy = chunkBusy.then(() => sendChunk(e.data)).catch(() => { });
  };
  mediaRecorder.onstart = () => {
    isRecording = true;
    statusText.textContent = 'Đang ghi hình...';
    statusDot && statusDot.classList.add('on');
    stopTimer = setTimeout(() => stopRecording(true), MAX_DURATION_MS);
  };
  mediaRecorder.onstop = async () => {
    isRecording = false;
    clearTimeout(stopTimer);
    statusText.textContent = 'Đang hoàn tất upload...';
    // đợi các chunk cuối gửi xong, rồi báo server kết thúc phiên
    try { await chunkBusy; } catch { }
    await finishServerUploadSession();
    statusText.textContent = 'Đã gửi video lên server để xử lý.';
    statusDot && statusDot.classList.remove('on');
    if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
  };

  // timeslice = 5000ms (5s) → chunk nhỏ, giảm rủi ro mất dữ liệu
  mediaRecorder.start(5000);
}

async function stopRecording() {
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
      console.error('[REC] upload fail:', resp.status, txt);
      if (resp.status === 413) alert('Video quá lớn (413). Hãy quay ngắn hơn/hạ chất lượng.');
      else alert(`Tải video lên thất bại (${resp.status}). ${txt || ''}`);
    } else {
      console.info('[REC] upload ok');
    }
  } catch (e) {
    console.error('[REC] upload error:', e);
    alert('Không thể tải video lên. Kiểm tra mạng.');
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

let endAt = 0;
function updateCountdownLabel() {
  const el = document.getElementById('recCountdown');
  if (!el || !endAt) return;
  const left = Math.max(0, endAt - Date.now());
  const mm = String(Math.floor(left / 60000)).padStart(2, '0');
  const ss = String(Math.floor((left % 60000) / 1000)).padStart(2, '0');
  el.textContent = `${mm}:${ss}`;
}

// stop khi rời trang
// window.addEventListener('beforeunload', () => { if (isRecording) stopRecording(); });
// window.addEventListener('visibilitychange', () => {
//   if (document.visibilityState === 'hidden') { try { mediaRecorder && mediaRecorder.stop(); } catch { } }
// });
window.addEventListener('beforeunload', () => { try { mediaRecorder && mediaRecorder.stop(); } catch { } });