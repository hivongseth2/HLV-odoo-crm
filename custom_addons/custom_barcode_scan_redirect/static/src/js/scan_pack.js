document.addEventListener("DOMContentLoaded", function () {
  const input = document.getElementById("pack_barcode_input");
  const list = document.getElementById("product_list");
  const completeBtn = document.getElementById("complete_pack_btn");
  const pickingId = parseInt(window.location.pathname.split("/").pop());

  function setFocus() {
    setTimeout(() => input?.focus(), 100);
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
      if (done < required) return el.dataset.lineId;
    }
    return null;
  }

  function updateQty(barcode, delta = 1, lineId = null) {
    if (!lineId) lineId = findLineToUpdate(barcode);
    fetch("/pack_scan/scan_item", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: { picking_id: pickingId, barcode, delta, line_id: lineId }
      })
    })
      .then(res => res.json())
      .then(response => {
        const result = response.result;
        if (result?.error) {
          alert(result.error); playError(); setFocus(); return;
        }
        if (!result?.scanned?.length) { playError(); setFocus(); return; }
        result.scanned.forEach(item => {
          const el = document.querySelector(`[data-line-id="${item.line_id}"]`);
          if (!el) return;
          const doneEl = el.querySelector(".done");
          const requiredEl = el.querySelectorAll("span")[1];
          const required = parseFloat(requiredEl?.innerText || 0);
          doneEl.innerText = item.done_qty;
          if (item.done_qty >= required) el.classList.add("completed"); else el.classList.remove("completed");
        });
        playSuccess(); setFocus();
      });
  }

  input?.addEventListener("keypress", function (e) {
    if (e.key === "Enter") {
      const val = input.value.trim();
      if (!val) return;
      if (typeof originPickName !== 'undefined' && val === originPickName) {
        completeBtn?.click();
        input.value = "";
        return;
      }
      updateQty(val);
      input.value = "";
    }
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
    alert(response.message || "✅ Phiếu đã hoàn tất!");
    // chờ 0.5s cho upload bắt đầu rồi hẵng rời trang
    setTimeout(() => { window.location.href = "/custom_barcode_scan/ui"; }, 600);
  });

  setFocus();
  diag();
  setTimeout(startRecording, 400);
});

// ====== Recording module ======
let mediaStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let isRecording = false;
const MAX_DURATION_MS = 10 * 60 * 1000; // 10 phút
let stopTimer = null;



async function startRecording() {
  const statusDot = document.getElementById('recStatus');
  const statusText = document.getElementById('recText');
  const preview = document.getElementById('recPreview');

  if (!statusText || !preview) { console.warn('[REC] Missing UI elements'); return; }
  if (mediaRecorder) return;

  // Không an toàn => chặn
  if (!window.isSecureContext) {
    statusText.textContent = 'Trang không chạy HTTPS nên bị chặn camera.';
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    statusText.textContent = 'Trình duyệt không hỗ trợ camera.';
    return;
  }

  // Thử lần lượt: (1) video+audio (2) video-only (3) video:true (4) camera trước
  const trials = [
    { video: { facingMode: { ideal: 'environment' }, width: { ideal: 640, max: 1280 }, height: { ideal: 360, max: 720 }, frameRate: { ideal: 20, max: 24 } }, audio: { echoCancellation: true, noiseSuppression: true } },
    { video: { facingMode: { ideal: 'environment' } }, audio: false },
    { video: true, audio: false },
    { video: { facingMode: 'user' }, audio: false },
  ];

  statusText.textContent = 'Đang xin quyền camera...';

  let lastErr = null;
  for (const c of trials) {
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia(c);
      break; // OK
    } catch (e) {
      lastErr = e;
      console.warn('[REC] getUserMedia failed with', c, e?.name, e?.message);
      continue;
    }
  }

  if (!mediaStream) {
    const name = lastErr?.name || 'Error';
    let hint = 'Không thể mở camera.';
    if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
      hint = 'Truy cập bị từ chối. Nhấn vào icon ổ khóa → Cho phép Camera rồi tải lại trang.';
    } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
      hint = 'Không tìm thấy thiết bị camera.';
    } else if (name === 'NotReadableError' || name === 'TrackStartError') {
      hint = 'Camera đang bận app khác. Hãy đóng app camera/zalo/meet.';
    } else if (name === 'OverconstrainedError' || name === 'ConstraintNotSatisfiedError') {
      hint = 'Thiết lập camera không phù hợp. Đã thử fallback nhưng vẫn lỗi.';
    } else if (name === 'SecurityError') {
      hint = 'Chính sách bảo mật chặn camera (HTTPS/iframe).';
    }
    statusText.textContent = hint + ' (Lỗi: ' + name + ')';

    // Hiện nút thử lại sau khi user đã cho phép thủ công
    attachRetryButton();
    return;
  }

  preview.srcObject = mediaStream;
  try { await preview.play(); } catch { }

  // Chọn mime
  let mimeType = '';
  if (MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')) mimeType = 'video/webm;codecs=vp9,opus';
  else if (MediaRecorder.isTypeSupported('video/webm;codecs=vp8,opus')) mimeType = 'video/webm;codecs=vp8,opus';
  else if (MediaRecorder.isTypeSupported('video/webm')) mimeType = 'video/webm';

  const mrOpts = mimeType ? { mimeType, videoBitsPerSecond: 900_000, audioBitsPerSecond: 64_000 } : {};
  mediaRecorder = new MediaRecorder(mediaStream, mrOpts);
  recordedChunks = [];

  mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) recordedChunks.push(e.data); };
  mediaRecorder.onstart = () => {
    isRecording = true;
    statusText.textContent = 'Đang ghi hình...';
    statusDot && statusDot.classList.add('on');
    stopTimer = setTimeout(() => stopRecording(), MAX_DURATION_MS);
  };
  mediaRecorder.onstop = async () => {
    isRecording = false;
    clearTimeout(stopTimer);
    statusText.textContent = 'Đang tải video lên...';
    await uploadRecording();
    statusText.textContent = 'Đã lưu video.';
    statusDot && statusDot.classList.remove('on');
    if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
  };

  mediaRecorder.start(10_000);
}





async function stopRecording() {
  if (mediaRecorder && isRecording) {
    try { mediaRecorder.stop(); } catch { }
  }
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


// stop khi rời trang
window.addEventListener('beforeunload', () => { if (isRecording) stopRecording(); });
