/**
 * transfer_modal.js — Transfer Item Between Packages Modal
 * Handles the UI for transferring items from one package to another.
 * Depends on: toast, createModal (ui_utils.js), currentPackageData (package_edit.js),
 *   openPackageEditModal (package_edit.js)
 */

function openTransferModalForItem(moveLineId, currentQty, productName) {
  console.log(`[DEBUG_TRANSFER_OPEN] Opening for ID: ${moveLineId} | Product: ${productName} | Qty: ${currentQty}`);

  const packs = [];
  const currentPackId = currentPackageData.package_id;

  document.querySelectorAll('.package-item-card').forEach(card => {
    const pId = parseInt(card.dataset.packageId);

    if (pId && pId !== currentPackId) {
      const pName = card.querySelector('.package-item-name')?.innerText.trim() || `Pack ${pId}`;
      packs.push({
        package_id: pId,
        package_name: pName
      });
    }
  });

  if (!packs.length) {
    toast.warn('Không có gói nào khác để chuyển sang.');
    return;
  }

  const content = document.createElement('div');
  content.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px;">
      <div style="padding:10px;background:#f0f9ff;border-radius:6px;border-left:3px solid #0ea5e9;">
        <strong>Sản phẩm:</strong> ${productName}
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <label style="font-weight:600;color:#374151;">Chọn gói đích:</label>
        <select id="transferTargetSelect" style="width:100%;padding:8px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;">
          <option value="">-- Chọn gói đích --</option>
          ${packs.map(p => `<option value="${p.package_id}">${p.package_name}</option>`).join('')}
        </select>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <label style="font-weight:600;color:#374151;">Số lượng chuyển (tối đa ${currentQty}):</label>
        <input id="transferQtyInput" type="number" min="1" max="${currentQty}" value="${Math.min(1, currentQty)}"
          style="padding:8px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;" />
      </div>
    </div>
  `;

  createModal('↔️ Chuyển sản phẩm', content, [
    { label: 'Hủy', color: '#6b7280', onclick: () => { } },
    {
      label: 'Chuyển', color: '#0ea5e9', onclick: async () => {
        const targetPackSelect = document.getElementById('transferTargetSelect');
        const targetPackId = targetPackSelect.value;
        const qty = parseFloat(document.getElementById('transferQtyInput').value);

        if (!targetPackId) { toast.warn('Vui lòng chọn gói đích'); return; }
        if (!qty || qty <= 0) { toast.warn('Vui lòng nhập số lượng hợp lệ'); return; }
        if (qty > currentQty) { toast.warn(`Số lượng không được vượt quá ${currentQty}`); return; }

        console.log(`[DEBUG_TRANSFER_EXEC] Executing Transfer: LineID=${moveLineId} -> Pack=${targetPackId} | Qty=${qty}`);

        try {
          const pickingId = parseInt(window.location.pathname.split("/").pop());

          const res = await fetch('/pack_scan/transfer_item_between_packs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify({
              jsonrpc: '2.0',
              method: 'call',
              params: {
                picking_id: pickingId,
                source_package_id: currentPackageData.package_id,
                target_package_id: parseInt(targetPackId),
                move_line_id: parseInt(moveLineId),
                qty: qty
              }
            })
          });

          const response = await res.json();
          const result = response.result || response;

          if (result?.error) {
            toast.error(result.error);
            return;
          }

          toast.success('Đã chuyển sản phẩm!', { ms: 1000 });

          // ============================================================
          // [FIX UI] CẬP NHẬT GIAO DIỆN GÓI ĐÍCH (TARGET PACKAGE)
          // ============================================================
          const targetCard = document.querySelector(`.package-item-card[data-package-id="${targetPackId}"]`);

          if (targetCard) {
            const badge = targetCard.querySelector('.badge');
            if (badge) {
              const currentTotal = parseFloat(badge.textContent.trim()) || 0;
              badge.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>
                ${currentTotal + qty}
              `;
            }

            const previewContainer = targetCard.querySelector('.package-items-preview');
            if (previewContainer) {
              const emptyEl = previewContainer.querySelector('.preview-empty');
              if (emptyEl) emptyEl.remove();

              let finalName = productName;
              const lineEl = document.querySelector(`#product_list .product-item[data-line-id="${moveLineId}"]`);
              if (lineEl) {
                const barcode = lineEl.getAttribute('data-barcode') || '';
                const rawName = lineEl.querySelector('strong')?.innerText.trim() || productName;

                console.log(lineEl)

                if (barcode && !rawName.startsWith('[')) {
                  finalName = `[${barcode}] ${rawName}`;
                } else {
                  finalName = rawName;
                }
              }

              let foundItem = null;
              const existingItems = previewContainer.querySelectorAll('.preview-item');

              for (let item of existingItems) {
                const nameEl = item.querySelector('.preview-item-name');
                const currentName = nameEl.innerText;

                if (currentName.includes(productName) || finalName.includes(currentName)) {
                  foundItem = item;
                  break;
                }
              }

              if (foundItem) {
                const qtyEl = foundItem.querySelector('.preview-item-qty');
                if (qtyEl) {
                  const currentQtyVal = parseFloat(qtyEl.innerText.toLowerCase().replace('x', '')) || 0;
                  const newTotalQty = currentQtyVal + qty;
                  qtyEl.innerText = `x${newTotalQty}`;
                }

                const nameEl = foundItem.querySelector('.preview-item-name');
                if (nameEl) nameEl.innerText = finalName;

                foundItem.style.transition = 'background 0.3s';
                foundItem.style.backgroundColor = '#fff3cd';
                setTimeout(() => foundItem.style.backgroundColor = 'transparent', 500);

              } else {
                const newItemHtml = `
                    <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center; animation: fadeIn 0.5s;">
                      <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057; font-size: 0.85rem;">${finalName}</span>
                      <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">x${qty}</span>
                    </div>
                   `;
                previewContainer.insertAdjacentHTML('afterbegin', newItemHtml);
              }
            }

            targetCard.style.transition = 'background-color 0.5s';
            targetCard.style.backgroundColor = '#e7f5ff';
            setTimeout(() => targetCard.style.backgroundColor = 'white', 1000);
          }

          openPackageEditModal({
            currentTarget: { dataset: { packageId: currentPackageData.package_id } },
            stopPropagation: () => { }
          });

        } catch (err) {
          toast.error('Lỗi kết nối: ' + err.message);
        }
      }
    }
  ]);
}
