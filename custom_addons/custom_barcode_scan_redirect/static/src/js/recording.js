/**
 * recording.js — Upload Session Management + Recording Module
 * Handles chunked video upload and MediaRecorder camera recording.
 * Depends on: toast (toast.js)
 */

// ==================== UPLOAD SESSION MANAGEMENT (CHUNKED) ====================
var uploadId = null;
var chunkIndex = 0;
var finishing = false;
var _stopResolve = null;  // resolve callback cho stopRecording() Promise

// Bảo vệ khi user đóng tab / bấm Back trong lúc đang quay:
// gọi finishServerUploadSession() với keepalive=true để browser gửi request
// ngay cả khi trang đang bị unload.
window.addEventListener('beforeunload', () => {
  if (uploadId && !finishing) {
    const _pickingId = (typeof pickingId !== 'undefined' && pickingId > 0)
      ? pickingId
      : parseInt(window.location.pathname.split('/').filter(Boolean).pop()) || 0;
    // fetch với keepalive=true – browser giữ request sống dù trang unload
    navigator.sendBeacon
      ? navigator.sendBeacon('/pack_scan/finish_upload',
          new Blob([JSON.stringify({ upload_id: uploadId, picking_id: _pickingId })],
                   { type: 'application/json' }))
      : fetch('/pack_scan/finish_upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          keepalive: true,
          body: JSON.stringify({ upload_id: uploadId, picking_id: _pickingId }),
        });
  }
});

async function startServerUploadSession() {
  // Use global pickingId injected by pack_scan_template.xml (server-rendered, always correct).
  // Do NOT re-parse the URL — trailing slashes or redirects make that unreliable.
  const _pickingId = (typeof pickingId !== 'undefined' && pickingId > 0)
    ? pickingId
    : parseInt(window.location.pathname.split('/').filter(Boolean).pop()) || 0;
  const resp = await fetch('/pack_scan/start_upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    body: JSON.stringify({ picking_id: _pickingId, ext: 'webm', mimetype: 'video/webm' })
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

  // Use global pickingId from template, same as startServerUploadSession.
  const _pickingId = (typeof pickingId !== 'undefined' && pickingId > 0)
    ? pickingId
    : parseInt(window.location.pathname.split('/').filter(Boolean).pop()) || 0;
  try {
    await fetch('/pack_scan/finish_upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      keepalive: true,
      body: JSON.stringify({ upload_id: uploadId, picking_id: _pickingId })
    });
  } finally {
    uploadId = null;
  }
}

// ==================== RECORDING MODULE (MediaRecorder + upload) ====================
var mediaStream = null;
var mediaRecorder = null;
var isRecording = false;
var chunkBusy = Promise.resolve();

const MAX_DURATION_MS = 25 * 60 * 1000;
var stopTimer = null, countdownTimer = null, endAt = 0;
var overlayCanvas = null, overlayCtx = null, drawRAF = 0;

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

    // Báo hiệu cho stopRecording() Promise rằng onstop đã hoàn tất
    if (_stopResolve) { _stopResolve(); _stopResolve = null; }
  };

  try {
    mediaRecorder.start(5000);
  } catch (err) {
    console.error('[REC] mediaRecorder.start failed:', err);
    statusText.textContent = 'Không thể bắt đầu ghi hình.';
  }
}

function stopRecording() {
  // Trả về Promise – resolve khi onstop hoàn tất (bao gồm finishServerUploadSession).
  // Cho phép caller dùng `await stopRecording()` và đảm bảo video đã được gửi
  // trước khi chuyển trang.
  if (!mediaRecorder || !isRecording) return Promise.resolve();
  return new Promise((resolve) => {
    _stopResolve = resolve;
    try { mediaRecorder.stop(); } catch { resolve(); _stopResolve = null; }
    // Timeout tối đa 90s (tăng từ 30s) – video lớn + mạng chậm cần thêm thời gian
    setTimeout(() => { if (_stopResolve) { _stopResolve(); _stopResolve = null; } }, 90000);
  });
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
