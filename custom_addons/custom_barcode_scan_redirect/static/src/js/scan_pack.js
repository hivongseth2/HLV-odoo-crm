document.addEventListener("DOMContentLoaded", function () {
  const input = document.getElementById("pack_barcode_input");
  const list = document.getElementById("product_list");
  const completeBtn = document.getElementById("complete_pack_btn");
  const pickingId = parseInt(window.location.pathname.split("/").pop());

  function setFocus() {
    setTimeout(() => input.focus(), 100);
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
        if (result?.error) {
          alert(result.error);
          playError();
          setFocus();
          return;
        }

        if (!result?.scanned?.length) {
          playError();
          setFocus();
          return;
        }

        result.scanned.forEach(item => {
          const el = document.querySelector(`[data-line-id="${item.line_id}"]`);
          if (!el) return;

          const doneEl = el.querySelector(".done");
          const requiredEl = el.querySelectorAll("span")[1]; // span sau dấu "/"
          const required = parseFloat(requiredEl?.innerText || 0);

          doneEl.innerText = item.done_qty;

          if (item.done_qty >= required) {
            el.classList.add("completed");
          } else {
            el.classList.remove("completed");
          }
        });

        playSuccess();
        setFocus();
      });
  }

  // input.addEventListener("keypress", function (e) {
  //   if (e.key === "Enter") {
  //     const val = input.value.trim();
  //     if (val) {
  //       updateQty(val);
  //       input.value = "";
  //     }
  //   }
  // });



  input.addEventListener("keypress", function (e) {
    if (e.key === "Enter") {
      const val = input.value.trim();
      if (!val) return;

      if (val === originPickName) {
        completeBtn.click();

        input.value = "";
        return;
      }

      // Nếu không phải mã phiếu → quét sản phẩm như thường
      updateQty(val);
      input.value = "";
    }
  });

  list.querySelectorAll(".btn-plus").forEach(btn =>
    btn.addEventListener("click", () =>
      updateQty(btn.dataset.barcode, 1, btn.dataset.lineId)
    )
  );

  list.querySelectorAll(".btn-minus").forEach(btn =>
    btn.addEventListener("click", () =>
      updateQty(btn.dataset.barcode, -1, btn.dataset.lineId)
    )
  );


  completeBtn.addEventListener("click", function () {
    // if (!confirm("Xác nhận hoàn tất đóng gói phiếu?")) return;

    const items = document.querySelectorAll("#product_list .product-item");
    let isValid = true;
    let missingProducts = [];

    items.forEach(item => {
      const name = item.querySelector("strong").innerText;
      const doneEl = item.querySelector(".done");
      const spanEls = item.querySelectorAll("span");

      const done = parseFloat(doneEl?.innerText || 0);
      const required = parseFloat(spanEls[1]?.innerText || 0);

      if (done < required) {
        isValid = false;
        missingProducts.push(`${name} (${done}/${required})`);
      }
    });

    if (!isValid) {
      alert("❌ Chưa quét đủ các sản phẩm sau:\n\n- " + missingProducts.join("\n- "));
      return;
    }

    fetch("/pack_scan/complete_picking", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest"
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: {
          picking_id: pickingId
        }
      })
    })
      .then(res => res.json())
      .then(response => {
        if (response.error || response.result?.error) {
          const msg = response.error?.message || response.result?.error || "❌ Có lỗi xảy ra!";
          alert(msg);
          return;
        }

        alert(response.message || "✅ Phiếu đã hoàn tất!");
        window.location.href = "/custom_barcode_scan/ui";
      });
  });

  setFocus();
});
// ====== Recording module ======
let mediaStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let isRecording = false;
const MAX_DURATION_MS = 10 * 60 * 1000; // 10 phút (tuỳ chỉnh)
let stopTimer = null;

async function startRecording() {
  const statusDot = document.getElementById('recStatus');
  const statusText = document.getElementById('recText');
  const preview = document.getElementById('recPreview');

  // Nếu thiếu phần tử UI thì bỏ qua để không crash
  if (!statusText || !preview) {
    console.warn('[REC] Missing UI elements (recStatus/recText/recPreview)');
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    statusText.textContent = 'Trình duyệt không hỗ trợ camera.';
    console.error('[REC] mediaDevices/getUserMedia unsupported');
    return;
  }

  try {
    statusText.textContent = 'Đang xin quyền camera...';
    const constraints = {
      video: { facingMode: { ideal: 'environment' } }, // ưu tiên camera sau trên mobile
      audio: true
    };

    // xin cả audio; nếu bị chặn audio thì fallback video-only
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
    } catch (errAudio) {
      console.warn('[REC] audio denied, fallback video-only:', errAudio?.name, errAudio?.message);
      mediaStream = await navigator.mediaDevices.getUserMedia({ video: constraints.video, audio: false });
    }

    preview.srcObject = mediaStream;
    // Một số trình duyệt cần gọi play() sau khi gán srcObject
    try { await preview.play(); } catch (e) { /* ignore */ }

    // chọn mimetype tốt nhất
    let mimeType = '';
    if (MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')) mimeType = 'video/webm;codecs=vp9,opus';
    else if (MediaRecorder.isTypeSupported('video/webm;codecs=vp8,opus')) mimeType = 'video/webm;codecs=vp8,opus';
    else if (MediaRecorder.isTypeSupported('video/webm')) mimeType = 'video/webm';

    mediaRecorder = new MediaRecorder(mediaStream, mimeType ? { mimeType } : undefined);

    recordedChunks = [];
    mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) recordedChunks.push(e.data); };
    mediaRecorder.onstart = () => {
      isRecording = true;
      statusText.textContent = 'Đang ghi hình...';
      statusDot && statusDot.classList.add('on');
      stopTimer = setTimeout(() => stopRecording(true), MAX_DURATION_MS);
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

    mediaRecorder.start(10_000); // chunk mỗi 10s
  } catch (err) {
    const name = err?.name || 'Error';
    const msg = err?.message || String(err);
    console.error('[REC] start error:', name, msg, err);

    // Thông điệp gợi ý nguyên nhân
    let hint = '';
    if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
      hint = 'Truy cập camera bị từ chối. Hãy nhấn “Cho phép” hoặc mở lại quyền camera trong trình duyệt.';
    } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
      hint = 'Không tìm thấy thiết bị camera.';
    } else if (name === 'NotReadableError' || name === 'TrackStartError') {
      hint = 'Camera đang bận hoặc bị hệ thống chặn.';
    } else if (name === 'OverconstrainedError' || name === 'ConstraintNotSatisfiedError') {
      hint = 'Thiết lập camera không phù hợp.';
    } else if (name === 'SecurityError') {
      hint = 'Trang không an toàn hoặc bị chính sách chặn.';
    } else if (name === 'TypeError') {
      hint = 'Thiếu tham số khi gọi getUserMedia.';
    }
    statusText.textContent = 'Không thể mở camera. ' + hint;
  }
}

async function stopRecording(auto = false) {
  if (mediaRecorder && isRecording) {
    try { mediaRecorder.stop(); } catch (e) { /* no-op */ }
  }
}

async function uploadRecording() {
  if (!recordedChunks.length) return;
  const blob = new Blob(recordedChunks, { type: recordedChunks[0].type || 'video/webm' });

  const fileName = `PACK_${pickingId}_${Date.now()}.webm`;
  const formData = new FormData();
  formData.append('file', blob, fileName);
  formData.append('picking_id', String(pickingId));

  try {
    const resp = await fetch('/pack_scan/upload_video', {
      method: 'POST',
      body: formData,
      // Không cần headers Content-Type (FormData tự set)
      // csrf=False trên route server đã cho phép
    });
    if (!resp.ok) {
      const txt = await resp.text();
      console.error('[REC] upload fail:', txt);
      alert('Tải video lên thất bại: ' + txt);
    }
  } catch (e) {
    console.error('[REC] upload error:', e);
    alert('Không thể tải video lên. Vui lòng kiểm tra mạng.');
  } finally {
    recordedChunks = [];
  }
}

// Auto-stop khi rời trang
window.addEventListener('beforeunload', (e) => {
  if (isRecording) {
    // cố gắng stop đồng bộ (trình duyệt có thể không đợi upload xong)
    stopRecording(true);
  }
});

// ====== Gọi khi trang tải xong ======
document.addEventListener('DOMContentLoaded', () => {
  startRecording();
});



document.getElementById('complete_pack_btn').addEventListener('click', async () => {
  try {
    const resp = await fetch('/pack_scan/complete_picking', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ picking_id: pickingId })
    });
    const data = await resp.json();
    if (data.success) {
      // dừng ghi và upload video
      await stopRecording(false);
      alert(data.message || 'Đã hoàn tất!');
      // có thể redirect nếu muốn
      // window.location.href = `/web#id=${pickingId}&model=stock.picking&view_type=form`;
    } else {
      alert(data.error || 'Không thể hoàn tất.');
    }
  } catch (e) {
    console.error(e);
    alert('Lỗi mạng khi hoàn tất phiếu.');
  }
});
