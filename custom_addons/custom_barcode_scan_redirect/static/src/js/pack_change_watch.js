/**
 * pack_change_watch.js — Báo người đóng gói khi phiếu PACK đổi trong lúc đang đóng.
 *
 * Odoo 18 đẩy hàng của PICK bổ sung vào chính phiếu PACK đang mở (gộp vào dòng cùng
 * sản phẩm), còn màn hình chỉ đọc số yêu cầu lúc tải trang. Không báo thì người đóng
 * gói thấy 80/80 trong khi máy chủ đòi 100: quét thêm bị chặn, Hoàn tất bị từ chối.
 *
 * Bản chụp số yêu cầu lúc render nằm ở #pack_snapshot. File này gửi lại nó định kỳ,
 * scan_pack.js gửi kèm mỗi lần quét / hoàn tất; máy chủ trả `changes` nếu lệch thì
 * khoá màn hình và bắt tải lại — sửa số tại chỗ không đủ vì có thể có cả dòng mới.
 *
 * Depends on: recording.js (_setPackingLocked), scan_pack.js (window.playPackError)
 */
(function () {
  if (window.packChangeWatch) return;

  // Đủ nhanh để người đóng gói biết trước khi quét hết số cũ, đủ thưa để không đè máy chủ.
  const POLL_MS = 15000;

  let snapshot = null;
  let pickingId = 0;
  let blocked = false;

  function describeChange(c) {
    if (c.old === null || c.old === undefined) return `${c.product}: thêm mới ${c.new}`;
    if (c.new === null || c.new === undefined) return `${c.product}: đã bỏ khỏi phiếu (trước là ${c.old})`;
    return `${c.product}: ${c.old} → ${c.new}`;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function block(changes) {
    if (blocked) return;
    blocked = true;
    if (typeof _setPackingLocked === 'function') _setPackingLocked(true);
    window.playPackError?.();

    const ov = el('div', 'cam-block-overlay');
    ov.id = 'packChangedOverlay';
    const box = el('div', 'cam-block-box');
    box.appendChild(el('div', 'cam-block-title', '⚠️ Phiếu vừa thay đổi'));
    box.appendChild(el('div', 'cam-block-msg', 'Số cần đóng đã khác lúc mở phiếu (thường do vừa lấy thêm hàng về):'));

    const list = el('ul', 'cam-block-hint');
    list.style.textAlign = 'left';
    changes.forEach(c => list.appendChild(el('li', '', describeChange(c))));
    box.appendChild(list);

    box.appendChild(el('div', 'cam-block-hint',
      'Bấm Tải lại để thấy số mới rồi làm tiếp. Hàng đã quét và kiện đã tạo vẫn giữ nguyên.'));
    const btn = el('button', 'cam-block-btn', 'Tải lại phiếu');
    btn.type = 'button';
    btn.addEventListener('click', () => window.location.reload());
    box.appendChild(btn);

    ov.appendChild(box);
    document.body.appendChild(ov);
  }

  /** Khoá màn hình nếu kết quả máy chủ có `changes`. Trả true khi đã khoá. */
  function handle(result) {
    if (!result || !Array.isArray(result.changes) || !result.changes.length) return false;
    block(result.changes);
    return true;
  }

  /** Hỏi máy chủ ngay. Trả true nếu phiếu đã đổi; lỗi mạng trả false (máy chủ vẫn chặn khi Hoàn tất). */
  async function checkNow() {
    if (blocked) return true;
    if (!snapshot) return false;
    try {
      const res = await fetch('/pack_scan/check_changes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { picking_id: pickingId, snapshot } }),
      });
      return handle((await res.json()).result);
    } catch (e) {
      console.warn('[pack_change_watch] check failed', e);
      return false;
    }
  }

  function start() {
    const holder = document.getElementById('pack_snapshot');
    if (!holder) return;
    try {
      snapshot = JSON.parse(holder.dataset.snapshot || 'null');
    } catch (e) {
      snapshot = null;
    }
    pickingId = parseInt(holder.dataset.pickingId) || 0;
    if (!snapshot || !pickingId) return;

    setInterval(() => { if (!document.hidden) checkNow(); }, POLL_MS);
    // Lúc tab ẩn thì không hỏi, nên quay lại tab là phải hỏi ngay.
    document.addEventListener('visibilitychange', () => { if (!document.hidden) checkNow(); });
  }

  window.packChangeWatch = { snapshot: () => snapshot, handle, checkNow };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
