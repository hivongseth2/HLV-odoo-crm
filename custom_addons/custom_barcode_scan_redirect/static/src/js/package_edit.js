/**
 * package_edit.js — Sibling Pack Actions + Package Edit Modal
 * Handles package unpack/edit delegation, and the full package edit modal
 * (open, close, qty update, remove item, add item, save changes).
 * Depends on: toast, createModal (ui_utils.js), window.normalizeCode (scan_pack.js),
 *   window.highlightElement (scan_pack.js), updateUnpackedLabel (server_sync.js),
 *   updateSidePanelUI (side_panel.js), openTransferModalForItem (transfer_modal.js)
 */

// ==================== SIBLING PACK ACTIONS ====================
document.addEventListener('click', async function (e) {
  const unpackBtn = e.target.closest('.btn-unpack');
  const editBtn = e.target.closest('.btn-edit');

  if (unpackBtn) {
    const packId = parseInt(unpackBtn.dataset.packId);
    if (confirm('Bạn chắc chắn muốn unpack kiện này?')) {
      const res = await fetch('/pack_scan/unpack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({
          jsonrpc: '2.0',
          method: 'call',
          params: { picking_id: packId }
        })
      });
      const response = await res.json();
      const result = response.result || response;

      if (result?.success) {
        toast.success(result.message, { ms: 2000 });
        const card = document.querySelector(`.package-item-card[data-package-id="${packId}"]`);
        if (card) {
          card.style.transition = 'all 0.3s ease';
          card.style.opacity = '0';
          card.style.transform = 'translateX(20px)';
          setTimeout(() => card.remove(), 300);
        }
      } else {
        toast.error(result?.error || 'Unpack thất bại', { ms: 2000 });
      }
    }
  }

  if (editBtn) {
    const packId = parseInt(editBtn.dataset.packId);
    window.location.href = `/custom_barcode_scan/pack_view/${packId}`;
  }

});

// ==================== PACKAGE EDIT MODAL ====================
var currentPackageData = null;


async function openPackageEditModal(event) {
  event.stopPropagation();

  const packageId = event.currentTarget.dataset.packageId;
  const pickingId = parseInt(window.location.pathname.split("/").pop());

  try {
    const res = await fetch("/pack_scan/get_package_details", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: { picking_id: pickingId, package_id: parseInt(packageId) }
      })
    });

    const response = await res.json();
    const result = response.result || response;

    if (result?.error) {
      toast.error("❌ " + result.error);
      return;
    }

    currentPackageData = result;
    updateSidePanelUI(currentPackageData);

    // [NEW] SELF-HEALING: Đồng bộ lại data-packed-qty từ Server về Client
    if (result.sync_info && Array.isArray(result.sync_info)) {
      console.log("[UI SYNC] Starting Self-Healing with server data...", result.sync_info);
      result.sync_info.forEach(info => {
        let targetEl = null;

        // 1. Tìm theo Barcode (Robust)
        if (info.product_barcode) {
          const normCode = normalizeCode(info.product_barcode);
          targetEl = [...document.querySelectorAll('#product_list .product-item')]
            .find(el => normalizeCode(el.dataset.barcode) === normCode);
        }

        // 2. Fallback: Tìm theo SKU
        if (!targetEl && info.product_sku) {
          targetEl = document.querySelector(`#product_list .product-item[data-default-code="${info.product_sku}"]`);
        }

        // 3. Update nếu tìm thấy
        if (targetEl) {
          const oldPacked = parseFloat(targetEl.getAttribute('data-packed-qty') || 0);
          const serverPacked = parseFloat(info.packed_qty || 0);

          if (Math.abs(oldPacked - serverPacked) > 0.001) {
            console.warn(`[UI SYNC] Correction for ${info.product_sku || info.product_barcode}: Client(${oldPacked}) -> Server(${serverPacked})`);
            targetEl.setAttribute('data-packed-qty', serverPacked);
            if (typeof updateUnpackedLabel === 'function') {
              updateUnpackedLabel(targetEl);
            }
          }
        }
      });
    }

    if (!Array.isArray(currentPackageData.other_packages)) {
      currentPackageData.other_packages = [];
    }
    const titleEl = document.getElementById('modalPackageName');
    if (titleEl) titleEl.innerText = result.package_name;

    const mergedItems = result.items || [];

    const uniqueProducts = new Set(mergedItems.map(i => i.product_id));
    const badgeEl = document.getElementById('itemCountBadge');
    if (badgeEl) badgeEl.innerText = uniqueProducts.size;


    const itemsList = document.getElementById('packageItemsList');
    if (itemsList) {
      itemsList.innerHTML = '';

      if (mergedItems.length === 0) {
        itemsList.innerHTML = `
          <div class="empty-state">
            <div class="empty-icon">📦</div>
            <h4 class="empty-title">Chưa có sản phẩm nào</h4>
            <p class="empty-desc">Thêm sản phẩm để quản lý gói hàng</p>
          </div>
        `;
      } else {
        mergedItems.forEach(item => {
          const li = document.createElement('div');
          li.className = 'item-card';
          li.setAttribute('data-move-line-id', item.move_line_id);

          let displayName = item.product_name;
          if (item.product_barcode && !displayName.startsWith('[')) {
            displayName = `[${item.product_barcode}] ${displayName}`;
          }

          li.innerHTML = `
            <div class="item-info">
              <div class="item-details">
                <h4 class="item-name">${displayName}</h4>
                <span class="item-sku">${item.product_sku || 'N/A'}</span>
              </div>
            </div>
            <div class="item-qty-control">
              <button class="qty-btn qty-decrease" data-move-line-id="${item.move_line_id}">−</button>
              <div class="qty-display" data-move-line-id="${item.move_line_id}" data-old-qty="${item.qty_done}">${item.qty_done}</div>
              <button class="qty-btn qty-increase" data-move-line-id="${item.move_line_id}">+</button>
            </div>
            <div class="item-actions">
              <button class="action-btn action-transfer" data-move-line-id="${item.move_line_id}" title="Chuyển sản phẩm">Chuyển</button>
            </div>
          `;

          // 1. Decrease
          console.log(`[DEBUG_RENDER] Item: ${item.product_name} | ID: ${item.move_line_id} | Qty: ${item.qty_done}`);

          li.querySelector('.qty-decrease').addEventListener('click', () => {
            const display = li.querySelector('.qty-display');
            let cur = parseFloat(display.innerText) || 0;
            const newQty = Math.max(0, cur - 1);
            display.innerText = String(newQty);
            item.qty_done = newQty;
          });

          // 2. Increase
          li.querySelector('.qty-increase').addEventListener('click', () => {
            const display = li.querySelector('.qty-display');
            const cur = parseFloat(display.innerText) || 0;

            const allProductItems = currentPackageData.all_items || [];
            const availableItems = allProductItems.filter(i => i.product_name === item.product_name);
            let totalAvailable = 0;
            availableItems.forEach(ai => { totalAvailable += ai.qty_available || 0; });

            const currentPackageItems = currentPackageData.items || [];
            let totalInPackages = 0;
            currentPackageItems.forEach(ci => {
              if (ci.product_name === item.product_name) {
                totalInPackages += parseFloat(ci.qty_done) || 0;
              }
            });

            const oldQtyStored = parseFloat(display.dataset.oldQty) || 0;
            const currentTotalForProduct = totalInPackages + (cur - oldQtyStored);

            if (currentTotalForProduct >= totalAvailable) {
              toast.warn(`Đã đạt giới hạn tối đa (${totalAvailable})`);
              return;
            }

            const newQty = cur + 1;
            display.innerText = String(newQty);
            item.qty_done = newQty;
          });

          // 4. Transfer
          li.querySelector('.action-transfer').addEventListener('click', (ev) => {
            ev.stopPropagation();
            const display = li.querySelector('.qty-display');
            const currentQty = parseFloat(display.innerText) || item.qty_done;
            openTransferModalForItem(item.move_line_id, currentQty, item.product_name);
          });

          itemsList.appendChild(li);
        });
      }
    }

    // Populate add item select
    const addItemSelect = document.getElementById('addItemSelect');
    if (addItemSelect) {
      addItemSelect.innerHTML = '<option value="">-- Chọn sản phẩm --</option>';
      if (result.all_items && result.all_items.length > 0) {
        result.all_items.forEach(item => {
          let label = item.product_name;
          const code = item.product_sku || item.product_barcode || '';
          if (code && !label.startsWith('[')) {
            label = `[${code}] ${label}`;
          }
          const option = document.createElement('option');
          option.value = item.move_line_id;
          option.innerText = `${label} (Còn: ${item.qty_available})`;
          addItemSelect.appendChild(option);
        });
      }
    }

    // Show modal
    const modal = document.getElementById('packageEditModal');
    if (modal) {
      modal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
    }

  } catch (err) {
    toast.error("❌ Lỗi kết nối: " + err.message);
  }
}

function closePackageEditModal() {
  const modal = document.getElementById('packageEditModal');
  modal.style.display = 'none';
  document.body.style.overflow = 'auto';
  currentPackageData = null;
}

async function removePackageItem(moveLineId) {
  const pickingId = parseInt(window.location.pathname.split("/").pop());
  const strLineId = String(moveLineId);

  const itemInModal = document.querySelector(`.qty-display[data-move-line-id="${strLineId}"]`);
  const qtyToRemove = itemInModal ? parseFloat(itemInModal.innerText) : 0;

  try {
    const res = await fetch("/pack_scan/remove_package_item", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: {
          picking_id: pickingId,
          package_id: currentPackageData.package_id,
          move_line_id: moveLineId
        }
      })
    });

    const response = await res.json();
    const result = response.result || response;

    if (result?.error) {
      toast.error(result.error);
      return;
    }

    toast.success("Đã xoá sản phẩm khỏi gói!", { ms: 1000 });

    if (qtyToRemove > 0) {
      let mainListEl = document.querySelector(`#product_list .product-item[data-line-id="${strLineId}"]`);

      if (!mainListEl && currentPackageData?.items) {
        const itemDetail = currentPackageData.items.find(i => String(i.move_line_id) === strLineId);
        if (itemDetail) {
          const allItems = document.querySelectorAll('#product_list .product-item');
          for (const el of allItems) {
            const prodNameEl = el.querySelector('strong');
            if (prodNameEl && prodNameEl.innerText.includes(itemDetail.product_name)) {
              mainListEl = el;
              break;
            }
          }
        }
      }

      if (mainListEl) {
        const doneInput = mainListEl.querySelector('.done-input');
        const doneEl = mainListEl.querySelector('.done');
        const currentDone = parseFloat(doneInput ? doneInput.value : (doneEl?.innerText || 0));
        const newDone = currentDone;

        const currentPacked = parseFloat(mainListEl.getAttribute('data-packed-qty') || 0);
        const newPacked = Math.max(0, currentPacked - qtyToRemove);
        mainListEl.setAttribute('data-packed-qty', newPacked);

        const requiredEl = mainListEl.querySelectorAll('span')[1];
        const required = parseFloat(requiredEl?.innerText || 0);
        if (newDone >= required && required > 0) {
          mainListEl.classList.add("completed");
        } else {
          mainListEl.classList.remove("completed");
        }

        highlightElement(mainListEl, "#ffc9c9");
      }
    }
    if (currentPackageData && currentPackageData.package_id) {
      openPackageEditModal({ currentTarget: { dataset: { packageId: currentPackageData.package_id } }, stopPropagation: () => { } });
    }

  } catch (err) {
    toast.error("Lỗi kết nối: " + err.message);
  }
}

async function addItemToPackage() {
  const pickingId = parseInt(window.location.pathname.split("/").pop());
  const moveLineId = parseInt(document.getElementById('addItemSelect').value);
  const qty = parseFloat(document.getElementById('addItemQty').value);

  if (!moveLineId || qty <= 0) {
    toast.warn("Vui lòng chọn sản phẩm và nhập số lượng");
    return;
  }

  try {
    const res = await fetch("/pack_scan/add_item_to_package", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: {
          picking_id: pickingId,
          package_id: currentPackageData.package_id,
          move_line_id: moveLineId,
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

    toast.success(result.message, { ms: 1500 });
    document.getElementById('addItemSelect').value = '';
    document.getElementById('addItemQty').value = '1';
    openPackageEditModal({ currentTarget: { dataset: { packageId: currentPackageData.package_id } }, stopPropagation: () => { } });

  } catch (err) {
    toast.error("Lỗi kết nối: " + err.message);
  }
}
window.addItemToPackage = addItemToPackage;

async function savePackageChanges() {
  const pickingId = parseInt(window.location.pathname.split("/").pop());
  const displayElements = document.querySelectorAll('.qty-display');

  let hasChanges = false;
  const changes = [];

  for (let display of displayElements) {
    const moveLineId = parseInt(display.dataset.moveLineId);
    const newQty = parseFloat(display.innerText);
    const oldQty = parseFloat(display.dataset.oldQty);

    if (!isNaN(newQty) && !isNaN(oldQty) && newQty !== oldQty) {
      hasChanges = true;
      changes.push({ moveLineId, newQty, oldQty });
    }
  }

  if (!hasChanges) {
    toast.info("Không có thay đổi nào");
    closePackageEditModal();
    return;
  }

  for (let change of changes) {
    try {
      const res = await fetch("/pack_scan/update_package_item_qty", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "call",
          params: {
            picking_id: pickingId,
            package_id: currentPackageData.package_id,
            move_line_id: change.moveLineId,
            new_qty: change.newQty
          }
        })
      });

      const response = await res.json();
      const result = response.result || response;

      if (result?.error) {
        toast.error(result.error);
        return;
      }

      const delta = change.newQty - change.oldQty;
      const strLineId = String(change.moveLineId);

      console.log(`[UI SYNC] ID=${strLineId} Delta=${delta}. Looking for DOM...`);

      let mainListEl = document.querySelector(`#product_list .product-item[data-line-id="${strLineId}"]`);
      if (mainListEl) console.log(`[UI SYNC] Found by ID`);

      if (!mainListEl && currentPackageData?.items) {
        const itemDetail = currentPackageData.items.find(i => String(i.move_line_id) === strLineId);
        if (itemDetail) {
          console.log(`[UI SYNC] Fallback search for`, itemDetail);
          if (itemDetail.product_barcode) {
            mainListEl = document.querySelector(`#product_list .product-item[data-barcode="${itemDetail.product_barcode}"]`);
            if (mainListEl) console.log(`[UI SYNC] Found by Barcode`);
          }
          if (!mainListEl && itemDetail.product_sku) {
            mainListEl = document.querySelector(`#product_list .product-item[data-default-code="${itemDetail.product_sku}"]`);
            if (mainListEl) console.log(`[UI SYNC] Found by SKU`);
          }
          if (!mainListEl) {
            const allItems = document.querySelectorAll('#product_list .product-item');
            for (const el of allItems) {
              const nameEl = el.querySelector('strong');
              if (nameEl && nameEl.innerText.includes(itemDetail.product_name)) {
                mainListEl = el;
                console.log(`[UI SYNC] Found by Name`);
                break;
              }
            }
          }
        }
      }

      if (mainListEl) {
        const doneInput = mainListEl.querySelector('.done-input');
        const doneEl = mainListEl.querySelector('.done');
        const currentDone = parseFloat(doneInput ? doneInput.value : (doneEl?.innerText || 0));
        const newDone = delta < 0 ? currentDone : Math.max(0, currentDone + delta);

        if (doneInput) {
          doneInput.value = newDone;
          doneInput.dataset.currentQty = newDone;
        } else if (doneEl) {
          doneEl.innerText = newDone;
        }

        const currentPacked = parseFloat(mainListEl.getAttribute('data-packed-qty') || 0);
        const newPacked = Math.max(0, currentPacked + delta);
        mainListEl.setAttribute('data-packed-qty', newPacked);

        console.log(`[UI SYNC] Update Stats:`, {
          lineId: strLineId, currentDone, delta, newDone,
          currentPacked, newPacked, unpackedQtyCalculation: newDone - newPacked
        });

        const requiredEl = mainListEl.querySelectorAll('span')[1];
        const required = parseFloat(requiredEl?.innerText || 0);
        if (newDone >= required && required > 0) mainListEl.classList.add("completed");
        else mainListEl.classList.remove("completed");

        const unpackedQty = newDone - parseFloat(mainListEl.getAttribute('data-packed-qty') || 0);
        let unpackedEl = mainListEl.querySelector('.unpacked-info');

        if (unpackedQty > 0) {
          if (!unpackedEl) {
            unpackedEl = document.createElement('div');
            unpackedEl.className = 'unpacked-info';
            unpackedEl.style.cssText = "font-size: 0.8rem; color: #d97706; margin-top: 4px; font-style: italic;";
            const infoContainer = mainListEl.querySelector('div') || mainListEl;
            infoContainer.appendChild(unpackedEl);
          }
          unpackedEl.innerText = `⚠️ Chưa đóng gói: ${unpackedQty}`;
        } else if (unpackedEl) {
          unpackedEl.remove();
        }

        highlightElement(mainListEl, "#ffd43b");
      } else {
        console.warn("⚠️ Không tìm thấy dòng sản phẩm bên ngoài để update ID:", change.moveLineId);
      }

      if (currentPackageData?.items) {
        const itemIndex = currentPackageData.items.findIndex(i => String(i.move_line_id) === strLineId);
        if (itemIndex > -1) {
          currentPackageData.items[itemIndex].qty = change.newQty;
          if (change.newQty <= 0) {
            currentPackageData.items.splice(itemIndex, 1);
          }
        }
      }

    } catch (err) {
      toast.error("Lỗi kết nối: " + err.message);
      return;
    }
  }

  toast.success("Đã lưu thay đổi!", { ms: 1500 });
  updateSidePanelUI(currentPackageData);
  closePackageEditModal();
}
