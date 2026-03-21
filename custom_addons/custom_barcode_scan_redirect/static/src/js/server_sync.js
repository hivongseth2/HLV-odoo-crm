/**
 * server_sync.js — Server Sync Helpers
 * Syncs packed qty from server data and manages unpacked labels.
 * Depends on: window.normalizeCode (scan_pack.js), window.highlightElement (scan_pack.js)
 */

function applyServerSyncInfo(syncInfoList) {
  if (!Array.isArray(syncInfoList)) return;
  console.log("[UI SYNC] Applying Server Sync Info...", syncInfoList);

  syncInfoList.forEach(info => {
    let targetEl = null;

    // [FIX] Prioritize lookup by Line ID if available in sync info
    if (info.line_id) {
      targetEl = document.querySelector(`[data-line-id="${info.line_id}"]`);
    }

    // Only use fuzzy matching if no line_id or line_id not found (and fallback needed? Prefer strict)
    if (!targetEl) {
      const allItems = document.querySelectorAll('#product_list .product-item');
      for (const item of allItems) {
        const itemBar = normalizeCode(item.dataset.barcode || '').toUpperCase();
        const itemSku = normalizeCode(item.dataset.defaultCode || '').toUpperCase();
        const sBarcode = normalizeCode(info.product_barcode || '').toUpperCase();
        const sSku = normalizeCode(info.product_sku || '').toUpperCase();

        // Match by Barcode (Fuzzy: endsWith)
        if (sBarcode && (itemBar === sBarcode || itemBar.endsWith(sBarcode) || sBarcode.endsWith(itemBar))) {
          targetEl = item;
          break;
        }
        // Match by SKU (Fuzzy: endsWith)
        if (!targetEl && sSku && (itemSku === sSku || itemSku.endsWith(sSku) || sSku.endsWith(itemSku))) {
          targetEl = item;
          break;
        }
      }
    }

    // 3. Update nếu tìm thấy
    if (targetEl) {
      const oldPacked = parseFloat(targetEl.getAttribute('data-packed-qty') || 0);
      const serverPacked = parseFloat(info.packed_qty || 0);

      if (Math.abs(oldPacked - serverPacked) > 0.001) {
        console.warn(`[UI SYNC] Correction for ${info.product_sku}: Client(${oldPacked}) -> Server(${serverPacked})`);
        targetEl.setAttribute('data-packed-qty', serverPacked);

        // Hiệu ứng visual báo hiệu update
        highlightElement(targetEl, "#dbe4ff"); // Xanh dương nhạt
      }

      // Luôn update label unpacked để đảm bảo nhất quán
      updateUnpackedLabel(targetEl);
    }
  });
}

function updateUnpackedLabel(el) {
  if (!el) return;
  const packedQty = parseFloat(el.getAttribute('data-packed-qty') || 0);
  const input = el.querySelector(".done-input");
  const currentDone = parseFloat(input ? input.value : (el.querySelector(".done")?.innerText || 0));

  const unpackedQty = currentDone - packedQty;
  let unpackedEl = el.querySelector('.unpacked-info');

  if (unpackedQty > 0.001) {
    if (!unpackedEl) {
      const newInfo = document.createElement('div');
      newInfo.className = 'unpacked-info';
      newInfo.style.cssText = "font-size: 0.8rem; color: #d97706; margin-top: 4px; font-style: italic;";
      const container = el.querySelector('div') || el;
      container.appendChild(newInfo);
      unpackedEl = newInfo;
    }
    unpackedEl.innerText = `⚠️ Chưa đóng gói: ${unpackedQty}`;
  } else {
    if (unpackedEl) unpackedEl.remove();
  }
}
