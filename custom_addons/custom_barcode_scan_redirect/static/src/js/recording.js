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
          new Blob([JSON.stringify({ upload_id: uploadId, picking_id: _pickingId, feed_issue: feedIssue })],
                   { type: 'application/json' }))
      : fetch('/pack_scan/finish_upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          keepalive: true,
          body: JSON.stringify({ upload_id: uploadId, picking_id: _pickingId, feed_issue: feedIssue }),
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
      body: JSON.stringify({ upload_id: uploadId, picking_id: _pickingId, feed_issue: feedIssue })
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
var overlayCanvas = null, overlayCtx = null, drawTimer = null;
var hiddenAt = 0;                 // moc thoi gian tab bi chuyen sang nen

// Canvas phải được vẽ đều tay thì captureStream mới có khung hình mới. Dùng
// requestAnimationFrame thì Chrome DỪNG HẲN khi tab chạy nền, video ghi ra
// đóng băng dù camera vẫn tốt. setInterval bị Chrome giảm tần suất xuống tối
// thiểu 1 lần/giây ở tab nền, chậm nhưng không bao giờ đứng hẳn.
const DRAW_INTERVAL_MS = Math.round(1000 / 24);
const HIDDEN_IGNORE_SEC = 3;      // chuyen tab thoang qua thi bo qua

function updateCountdownLabel() {
  const el = document.getElementById('recCountdown');
  if (!el || !endAt) return;
  const left = Math.max(0, endAt - Date.now());
  const mm = String(Math.floor(left / 60000)).padStart(2, '0');
  const ss = String(Math.floor((left % 60000) / 1000)).padStart(2, '0');
  el.textContent = `${mm}:${ss}`;
}

// ==================== CAMERA FEED HEALTH ====================
// OBS báo "camera sẵn sàng" với trình duyệt kể cả khi nó đang bơm ra màn hình
// chờ hoặc khung đen vì nguồn VLC chết. getUserMedia() thành công, MediaRecorder
// ghi đủ, Drive nhận file — chỉ nội dung là vô dụng. Chỉ nhìn pixel mới biết.
const PROBE_SIZE = 48;            // đủ pixel để thấy nhiễu cảm biến, đủ nhỏ để gần như miễn phí
const GATE_SAMPLES = 5;
const GATE_INTERVAL_MS = 600;     // 5 mẫu x 600ms ~ 2.4 giây kiểm tra trước khi cho quét
const WATCH_INTERVAL_MS = 2000;
const WATCH_WINDOW = 4;           // 4 mẫu x 2s = phải đứng im liên tục 6s mới báo.
// Cửa sổ ngắn không làm tăng báo nhầm: camera thật không bao giờ cho hai khung
// hình giống hệt nhau dù cảnh đứng yên, nên 6s hay 30s cũng phân biệt được như
// nhau — dài thêm chỉ tổ chậm.

var probeCanvas = null, probeCtx = null;
var watchTimer = null, watchSamples = [];
var feedDead = false;             // trang thai HIEN TAI cua luong camera
var feedIssue = null;             // co DINH {reason, atSec, recovered} de ghi vao chatter

/**
 * Lấy chữ ký khung hình hiện tại của luồng camera.
 * Dò thẳng từ video gốc chứ KHÔNG dò từ overlayCanvas: overlay có vẽ đồng hồ
 * nhảy từng giây nên khung hình lúc nào cũng "đổi", che mất việc camera đã chết.
 */
function _probeSignature(sourceVideo) {
  if (!probeCanvas) {
    probeCanvas = document.createElement('canvas');
    probeCanvas.width = PROBE_SIZE;
    probeCanvas.height = PROBE_SIZE;
    probeCtx = probeCanvas.getContext('2d', { willReadFrequently: true });
    // Tắt nội suy: thu nhỏ kiểu làm mượt sẽ bình quân hoá mất nhiễu cảm biến,
    // mà nhiễu chính là thứ phân biệt camera thật với ảnh tĩnh của OBS.
    probeCtx.imageSmoothingEnabled = false;
  }
  try {
    probeCtx.drawImage(sourceVideo, 0, 0, PROBE_SIZE, PROBE_SIZE);
    return CameraHealth.frameSignature(probeCtx.getImageData(0, 0, PROBE_SIZE, PROBE_SIZE));
  } catch (e) {
    console.warn('[REC] probe failed:', e);
    return null;
  }
}

async function _collectSignatures(sourceVideo, count, intervalMs) {
  const out = [];
  for (let i = 0; i < count; i++) {
    if (i) await new Promise(r => setTimeout(r, intervalMs));
    const sig = _probeSignature(sourceVideo);
    if (sig && sig.length) out.push(sig);
  }
  return out;
}

/** Cờ server truyền xuống: chặn hẳn hay chỉ cảnh báo khi camera hỏng. */
function _gateIsBlocking() {
  return (typeof packCamGateBlocking !== 'undefined') ? !!packCamGateBlocking : true;
}

function _setPackingLocked(locked) {
  // Máy quét barcode gõ vào ô nào đang focus, nên phải vô hiệu hoá mọi ô nhập
  // được — khoá mỗi ô quét thì nhân viên vẫn gõ tay vào cột số lượng.
  const input = document.getElementById('pack_barcode_input');
  if (input) input.disabled = locked;
  ['complete_pack_btn', 'btnPartialPack'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = locked;
  });
  document.querySelectorAll('#product_list .done-input')
    .forEach(el => { el.disabled = locked; });
}

/** Chặn màn hình đóng gói lại cho tới khi người dùng sửa OBS và bấm Thử lại. */
function _blockPacking(reason, statusText) {
  if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }

  statusText.textContent = CameraHealth.describe(reason);
  statusText.classList.add('rec-alert');
  _setPackingLocked(true);

  const old = document.getElementById('camBlockOverlay');
  if (old) old.remove();

  const ov = document.createElement('div');
  ov.id = 'camBlockOverlay';
  ov.className = 'cam-block-overlay';
  ov.innerHTML = `
    <div class="cam-block-box">
      <div class="cam-block-title">⛔ Camera chưa sẵn sàng</div>
      <div class="cam-block-msg">${CameraHealth.describe(reason)}</div>
      <div class="cam-block-hint">
        Mở OBS, bật nguồn VLC và bật Virtual Camera, rồi bấm Thử lại.<br/>
        Chưa có hình thì chưa đóng gói được — video là bằng chứng khi khách khiếu nại.
      </div>
      <button type="button" id="camBlockRetry" class="cam-block-btn">Thử lại</button>
    </div>`;
  document.body.appendChild(ov);
  document.getElementById('camBlockRetry').addEventListener('click', async () => {
    ov.remove();
    _setPackingLocked(false);
    statusText.classList.remove('rec-alert');
    await startRecording();
  });
}

function _startFeedWatchdog(sourceVideo, statusText) {
  clearInterval(watchTimer);
  watchSamples = [];
  watchTimer = setInterval(() => {
    const sig = _probeSignature(sourceVideo);
    if (!sig || !sig.length) return;
    watchSamples.push(sig);
    if (watchSamples.length > WATCH_WINDOW) watchSamples.shift();
    if (watchSamples.length < WATCH_WINDOW) return;

    const verdict = CameraHealth.assessFeed(watchSamples);

    if (!verdict.alive) {
      if (feedDead) return;  // đang mất tín hiệu, đã báo rồi thì thôi
      feedDead = true;

      // Cờ dính: video đã có một đoạn hỏng thì mãi mãi là sự thật về file đó,
      // dù sau này tín hiệu có về. Chỉ ghi lần mất ĐẦU TIÊN.
      if (!feedIssue) {
        const startedAt = endAt - MAX_DURATION_MS;
        feedIssue = {
          reason: verdict.reason,
          atSec: Math.max(0, Math.round((Date.now() - startedAt) / 1000)),
        };
      }
      console.warn('[REC] camera feed died mid-recording:', feedIssue, verdict);

      // Cố ý KHÔNG dừng phiên: dừng giữa chừng là mất luôn đoạn đã quay được. Giữ
      // phần đầu cộng một ghi chú nói rõ mất tín hiệu từ phút nào thì có ích hơn.
      statusText.textContent = '⚠ MẤT TÍN HIỆU CAMERA — vẫn đang ghi';
      statusText.classList.add('rec-alert');
      toast.error('⚠ ' + CameraHealth.describe(verdict.reason) + ' Kiểm tra OBS ngay.', { ms: 8000 });
      return;
    }

    if (!feedDead) return;  // vẫn bình thường, không có gì phải cập nhật

    // Tín hiệu về lại: banner phải theo trạng thái hiện tại, không để đỏ mãi.
    // Nhưng feedIssue thì giữ nguyên — đoạn hỏng vẫn nằm trong file đã quay.
    feedDead = false;
    if (feedIssue) feedIssue.recovered = true;
    console.info('[REC] camera feed recovered');
    statusText.textContent = 'Đang ghi hình... (đã có đoạn mất tín hiệu)';
    statusText.classList.remove('rec-alert');
    toast.success('Camera đã có tín hiệu trở lại.', { ms: 4000 });
  }, WATCH_INTERVAL_MS);
}

/**
 * Tab chạy nền vẫn vẽ được nhờ setInterval, nhưng Chrome bóp xuống ~1 khung/giây
 * nên đoạn đó gần như đứng hình. Không sửa được bằng code — chỉ có thể nói cho
 * người đóng gói biết và ghi lại vào chatter để sau này không tưởng nhầm là
 * video tốt.
 */
function _onVisibilityChange() {
  if (!isRecording) return;

  if (document.hidden) {
    hiddenAt = Date.now();
    return;
  }
  if (!hiddenAt) return;

  const awaySec = Math.round((Date.now() - hiddenAt) / 1000);
  hiddenAt = 0;
  if (awaySec < HIDDEN_IGNORE_SEC) return;

  const statusText = document.getElementById('recText');
  if (!feedIssue) {
    const startedAt = endAt - MAX_DURATION_MS;
    feedIssue = {
      reason: 'hidden',
      atSec: Math.max(0, Math.round((Date.now() - startedAt) / 1000) - awaySec),
    };
  }
  console.warn('[REC] tab hidden while recording for %ds', awaySec);

  // Khi agent ghi hình phía server đang chạy, bằng chứng không còn phụ thuộc tab
  // này: ffmpeg quay độc lập trên máy, rời tab không mất gì. Chỉ bản quay bằng
  // trình duyệt bị đứng hình. Đọc cờ bằng typeof để file này vẫn chạy được khi
  // chưa cài hlv_pack_recorder.
  const agentRecording = typeof window.hlvAgentRecording !== 'undefined'
    && !!window.hlvAgentRecording;

  if (statusText) {
    statusText.textContent = `Đang ghi hình... (đã rời tab ${awaySec}s, đoạn đó đứng hình)`;
    statusText.classList.remove('rec-alert');
  }
  if (agentRecording) {
    toast.info(`Bản quay bằng trình duyệt bị đứng hình ${awaySec} giây do rời tab. `
      + 'Camera ghi phía server vẫn quay đủ, phiếu này vẫn có bằng chứng.', { ms: 6000 });
    return;
  }
  toast.warn(`⚠ Vừa rời màn hình đóng gói ${awaySec} giây — đoạn video đó gần như đứng hình. `
    + 'Đừng chuyển tab trong lúc đang quay.', { ms: 8000 });
}

document.addEventListener('visibilitychange', _onVisibilityChange);

function _stopFeedWatchdog() {
  clearInterval(watchTimer);
  watchTimer = null;
  watchSamples = [];
}

async function startRecording() {
  const statusDot = document.getElementById('recStatus');
  const statusText = document.getElementById('recText');
  const preview = document.getElementById('recPreview');
  if (!statusText || !preview) return;

  feedIssue = null;
  feedDead = false;
  hiddenAt = 0;
  statusText.classList.remove('rec-alert');

  // Tắt qua tham số pack_scan.browser_recording khi agent phía server lo việc
  // quay. Bắt buộc phải tắt nếu hai bên dùng chung một webcam USB.
  if (typeof packBrowserRecording !== 'undefined' && !packBrowserRecording) {
    statusText.textContent = 'Camera do agent phía server ghi (đã tắt quay bằng trình duyệt).';
    console.info('[REC] browser recording disabled by config');
    return;
  }

  // Xin 1080p. 'ideal' không bao giờ làm getUserMedia thất bại — thiết bị chỉ có
  // 720p thì trả về 720p. Trước đây xin ideal 1280 nên kể cả khi OBS xuất 1080p,
  // trình duyệt vẫn thu nhỏ xuống 720p TRƯỚC khi nén, mất chi tiết ngay đầu vào.
  const constraints = {
    video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 24, max: 24 } },
    audio: { echoCancellation: true, noiseSuppression: true }
  };
  try {
    try { mediaStream = await navigator.mediaDevices.getUserMedia(constraints); }
    catch { mediaStream = await navigator.mediaDevices.getUserMedia({ video: constraints.video, audio: false }); }
  } catch (e) {
    // Không mở được thiết bị nào: OBS chưa bật Virtual Camera, hoặc camera đang
    // bị ứng dụng khác chiếm, hoặc trang không chạy trên HTTPS. Trước đây chỗ
    // này chỉ ghi một dòng chữ xám rồi thoát — nhân viên vẫn quét tiếp và đóng
    // gói xong mà không có video nào.
    console.error('[REC] getUserMedia failed:', e);
    if (_gateIsBlocking()) {
      _blockPacking('nocam', statusText);
    } else {
      statusText.textContent = CameraHealth.describe('nocam');
      statusText.classList.add('rec-alert');
      toast.error('⚠ ' + CameraHealth.describe('nocam')
        + ' Phiếu này sẽ không có video.', { ms: 8000 });
    }
    return;  // không có luồng thì không quay được gì
  }

  const vTrack = mediaStream.getVideoTracks()[0];
  const s = vTrack.getSettings ? vTrack.getSettings() : {};
  const W = s.width || 1280, H = s.height || 720;
  console.info('[REC] source %dx%d @%sfps', W, H, s.frameRate || '?');
  // Capabilities cho biết THIẾT BỊ xuất ra tối đa bao nhiêu. Nếu max ở đây cũng
  // chỉ 1280x720 thì trần nằm ngoài trình duyệt — ở Output Resolution của OBS
  // hoặc ở luồng VLC đang kéo substream — sửa phía này không ăn thua.
  try {
    const cap = vTrack.getCapabilities ? vTrack.getCapabilities() : {};
    console.info('[REC] device max %sx%s',
      (cap.width && cap.width.max) || '?', (cap.height && cap.height.max) || '?');
  } catch (e) {
    console.info('[REC] device capabilities không đọc được');
  }

  overlayCanvas = document.createElement('canvas');
  overlayCanvas.width = W; overlayCanvas.height = H;
  overlayCtx = overlayCanvas.getContext('2d');

  const rawVideo = document.createElement('video');
  rawVideo.srcObject = new MediaStream([vTrack]);
  rawVideo.muted = true;
  rawVideo.playsInline = true;
  rawVideo.autoplay = true;
  try { await rawVideo.play(); } catch { }

  statusText.textContent = 'Đang kiểm tra tín hiệu camera...';
  const gate = CameraHealth.assessFeed(
    await _collectSignatures(rawVideo, GATE_SAMPLES, GATE_INTERVAL_MS)
  );
  if (!gate.alive) {
    console.warn('[REC] camera feed dead at gate:', gate);
    if (_gateIsBlocking()) {
      _blockPacking(gate.reason, statusText);
      return;  // khong quay, khong mo phien upload
    }
    // Chế độ chỉ cảnh báo: vẫn quay, nhưng đánh dấu để chatter ghi rõ video hỏng.
    feedIssue = { reason: gate.reason, atSec: 0 };
    toast.error('⚠ ' + CameraHealth.describe(gate.reason)
      + ' Video này sẽ không dùng làm bằng chứng được.', { ms: 8000 });
  }

  endAt = Date.now() + MAX_DURATION_MS;
  updateCountdownLabel();
  clearInterval(countdownTimer);
  countdownTimer = setInterval(updateCountdownLabel, 500);

  function drawOverlay() {
    if (!overlayCtx) return;
    overlayCtx.drawImage(rawVideo, 0, 0, W, H);
    overlayCtx.fillStyle = 'rgba(0,0,0,0.5)';
    overlayCtx.fillRect(0, H - 52, W, 52);

    overlayCtx.fillStyle = '#fff';
    overlayCtx.font = 'bold 24px Segoe UI, Arial';
    overlayCtx.fillText(`Time: ${new Date().toLocaleString()} `, 16, H - 16);
  }
  clearInterval(drawTimer);
  drawOverlay();
  drawTimer = setInterval(drawOverlay, DRAW_INTERVAL_MS);

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
  // 1.2 Mbps cho 720p24 là quá thấp với cảnh kho đầy chi tiết và chuyển động —
  // đó là lý do chính khiến video mờ hơn hẳn luồng gốc. Nâng độ phân giải mà
  // không nâng bitrate thì còn mờ hơn, nên mặc định bám theo khung hình thật sự
  // nhận được. Đặt pack_scan.video_bitrate > 0 để ép một giá trị cố định.
  const autoBitrate = H >= 1080 ? 4_000_000 : 2_500_000;
  const bitrate = (typeof packVideoBitrate !== 'undefined' && packVideoBitrate > 0)
    ? packVideoBitrate : autoBitrate;
  const mrOpts = mimeType ? { mimeType, videoBitsPerSecond: bitrate, audioBitsPerSecond: 64_000 } : {};
  console.info('[REC] codec=%s bitrate=%d', mimeType || 'default', bitrate);

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
    _startFeedWatchdog(rawVideo, statusText);
  };
  mediaRecorder.onstop = async () => {
    isRecording = false;
    try { clearTimeout(stopTimer); } catch { }
    try { clearInterval(countdownTimer); } catch { }
    countdownTimer = null;
    _stopFeedWatchdog();

    statusText.textContent = 'Đang hoàn tất upload...';
    try { await chunkBusy; } catch { }
    await finishServerUploadSession();

    statusText.textContent = 'Đã gửi video lên server để xử lý.';
    statusDot && statusDot.classList.remove('on');

    clearInterval(drawTimer);
    drawTimer = null; overlayCtx = null; overlayCanvas = null;

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
