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
      if (r && r.ok) {
        console.info('[PACK_REC] agent đang quay tại %s: %s', r.station, (r.cameras || []).join(', '));
      } else {
        console.warn('[PACK_REC] không bật được agent:', r && r.error);
      }
    } catch (e) {
      console.warn('[PACK_REC] gọi start hỏng:', e);
    }
  }

  async function stopAgentRecording() {
    if (!stationKey()) return;
    try {
      await callJson('/pack_recorder/stop', { picking_id: currentPickingId() });
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

    // Đóng tab / bấm Back giữa chừng: sendBeacon vẫn đi được khi trang đang unload.
    window.addEventListener('beforeunload', () => {
      if (!stationKey()) return;
      const payload = JSON.stringify({
        jsonrpc: '2.0', method: 'call', params: { picking_id: currentPickingId() },
      });
      try {
        navigator.sendBeacon('/pack_recorder/stop',
          new Blob([payload], { type: 'application/json' }));
      } catch { }
    });
  });
})();
