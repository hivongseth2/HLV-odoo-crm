/**
 * pack_recorder_hook.js — nối màn hình đóng gói với agent ghi hình tại kho.
 *
 * Chạy SONG SONG với luồng quay bằng trình duyệt trong custom_barcode_scan_redirect.
 * Cố ý không gỡ luồng cũ trong giai đoạn thử: hai bên cùng quay một phiếu thì so
 * được chất lượng, và nếu agent chưa chạy thì vẫn còn video của trình duyệt.
 *
 * Mọi lỗi ở đây đều nuốt: agent chết, chưa khai bàn, mạng lỗi — không cái nào
 * được phép chặn nhân viên đóng gói.
 */
(() => {
  const STATION_STORAGE_KEY = 'hlvPackStationKey';
  const HEARTBEAT_MS = 10000;
  let heartbeatTimer = null;

  function stationKey() {
    try {
      return localStorage.getItem(STATION_STORAGE_KEY) || '';
    } catch {
      return '';  // chế độ riêng tư / chặn site data
    }
  }

  async function callJson(path, params) {
    const resp = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params }),
    });
    const data = await resp.json();
    return data.result || data;
  }

  function currentPickingId() {
    return (typeof pickingId !== 'undefined' && pickingId > 0)
      ? pickingId
      : parseInt(window.location.pathname.split('/').filter(Boolean).pop()) || 0;
  }

  async function startAgentRecording() {
    const key = stationKey();
    if (!key) {
      console.info('[PACK_REC] máy này chưa gán bàn đóng gói — mở /pack_recorder/set_station một lần');
      return;
    }
    try {
      const r = await callJson('/pack_recorder/start', {
        picking_id: currentPickingId(), station_key: key,
      });
      if (r && r.ok && (r.cameras || []).length) {
        // Cờ cho recording.js biết bằng chứng không còn phụ thuộc tab này nữa,
        // để nó đừng doạ mất video khi nhân viên chuyển tab.
        window.hlvAgentRecording = true;
        console.info('[PACK_REC] agent đang quay tại %s: %s', r.station, (r.cameras || []).join(', '));
      } else {
        window.hlvAgentRecording = false;
        console.warn('[PACK_REC] không quay được:', r && r.error, '| tình trạng agent:', r && r.agent_status);
      }
    } catch (e) {
      window.hlvAgentRecording = false;
      console.warn('[PACK_REC] gọi start hỏng:', e);
    }
  }

  async function stopAgentRecording() {
    if (!stationKey()) return;
    try {
      await callJson('/pack_recorder/stop', { picking_id: currentPickingId() });
      window.hlvAgentRecording = false;
      console.info('[PACK_REC] đã báo agent dừng');
    } catch (e) {
      console.warn('[PACK_REC] gọi stop hỏng:', e);
    }
  }

  // Nút Hoàn tất đã có handler riêng chuyển trang; bám vào giai đoạn capture để
  // lệnh dừng đi trước khi trang kịp rời đi.
  document.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('pack_barcode_input')) return;  // không phải màn hình đóng gói

    startAgentRecording();

    document.getElementById('complete_pack_btn')
      ?.addEventListener('click', stopAgentRecording, { capture: true });

    // CỐ Ý không dừng ở beforeunload: F5 cũng kích hoạt sự kiện đó, mà F5 giữa
    // chừng thì phải quay TIẾP chứ không phải cắt video của một phiếu thành hai
    // file. Thay vào đó trang báo còn sống đều đặn; im lặng quá lâu thì server
    // tự đóng sổ. Đóng tab, bấm Back, máy treo — cùng một cơ chế lo hết.
    heartbeatTimer = setInterval(() => {
      if (!stationKey()) return;
      callJson('/pack_recorder/heartbeat', { picking_id: currentPickingId() })
        .catch(() => { });  // mạng chớp một nhịp không sao, ngưỡng để rộng rồi
    }, HEARTBEAT_MS);

    window.addEventListener('pagehide', () => clearInterval(heartbeatTimer));
  });
})();
