/**
 * side_panel.js — Side Panel UI + renderNewPackageToPanel
 * Manages the package list panel on the right side.
 * Depends on: openPackageEditModal (package_edit.js)
 */

function renderNewPackageToPanel(pkgId, pkgName, itemsData) {
  let list = document.querySelector('.panel-packages-list');
  const emptyState = document.querySelector('.panel-empty-state');

  const newItemsQty = itemsData.reduce((sum, i) => sum + i.qty, 0);

  // HELPER: Hàm lấy tên chuẩn [Barcode] Tên
  const getProductInfo = (item) => {
    let finalName = item.name || 'Sản phẩm...';

    if (item.barcode && !finalName.startsWith('[')) {
      finalName = `[${item.barcode}] ${finalName}`;
    }

    // Fallback: Nếu không có name/barcode trong item, thử tìm DOM (Legacy)
    if ((!item.name || !item.barcode) && item.move_line_id) {
      const lineEl = document.querySelector(`[data-line-id="${item.move_line_id}"]`);
      if (lineEl) {
        const rawName = lineEl.querySelector('strong')?.innerText.trim() || '';
        const barcode = lineEl.getAttribute('data-barcode') || '';
        if (rawName) {
          finalName = (barcode && !rawName.startsWith('[')) ? `[${barcode}] ${rawName}` : rawName;
        }
      }
    }
    return finalName;
  };

  const existingCard = document.querySelector(`.package-item-card[data-package-id="${pkgId}"]`);

  if (existingCard) {
    // === TRƯỜNG HỢP A: ĐÃ CÓ GÓI -> CẬP NHẬT (MERGE) ===
    const badge = existingCard.querySelector('.badge');
    if (badge) {
      const currentTotal = parseFloat(badge.textContent.trim()) || 0;
      badge.innerHTML = `
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>
          ${currentTotal + newItemsQty}
      `;
    }

    const previewContainer = existingCard.querySelector('.package-items-preview');
    if (previewContainer) {
      const emptyEl = previewContainer.querySelector('.preview-empty');
      if (emptyEl) emptyEl.remove();

      itemsData.forEach(item => {
        if (item.qty <= 0) return;
        const name = getProductInfo(item);

        let foundRow = null;
        for (let row of previewContainer.querySelectorAll('.preview-item')) {
          if (row.querySelector('.preview-item-name').innerText === name) {
            foundRow = row;
            break;
          }
        }

        if (foundRow) {
          const qtyEl = foundRow.querySelector('.preview-item-qty');
          if (qtyEl) {
            const oldQty = parseFloat(qtyEl.innerText.replace('x', '')) || 0;
            qtyEl.innerText = `x${oldQty + item.qty}`;
          }

          foundRow.style.transition = 'background 0.3s';
          foundRow.style.backgroundColor = '#fff3cd';
          setTimeout(() => foundRow.style.backgroundColor = 'transparent', 500);
        } else {
          const newHtml = `
              <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center; animation: fadeIn 0.5s;">
                <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057; font-size: 0.85rem;">${name}</span>
                <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">x${item.qty}</span>
              </div>`;
          previewContainer.insertAdjacentHTML('afterbegin', newHtml);
        }
      });
    }

    existingCard.style.transition = 'background-color 0.5s ease';
    existingCard.style.backgroundColor = '#e7f5ff';
    setTimeout(() => { existingCard.style.backgroundColor = 'white'; }, 800);
    existingCard.parentElement.prepend(existingCard);

  } else {
    // === TRƯỜNG HỢP B: TẠO GÓI MỚI (CREATE) ===
    const aggregatedItems = {};

    itemsData.forEach(item => {
      if (item.qty <= 0) return;
      const name = getProductInfo(item);
      if (aggregatedItems[name]) {
        aggregatedItems[name] += item.qty;
      } else {
        aggregatedItems[name] = item.qty;
      }
    });

    let previewHtml = '';
    for (const [name, qty] of Object.entries(aggregatedItems)) {
      previewHtml += `
          <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center;">
            <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057; font-size: 0.85rem;">${name}</span>
            <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">x${qty}</span>
          </div>
        `;
    }

    if (!list) {
      if (emptyState) emptyState.remove();
      list = document.createElement('ul');
      list.className = 'panel-packages-list';
      list.style.cssText = "list-style: none; padding: 0; margin: 0;";
      const panelBody = document.querySelector('.pack-side-panel .panel-body');
      const title = panelBody.querySelector('.panel-section-title');
      if (title) title.after(list); else panelBody.prepend(list);
    }

    const li = document.createElement('li');
    li.className = 'package-item-card';
    li.dataset.packageId = pkgId;
    li.style.cssText = "background: white; border-radius: 10px; padding: 1rem; margin-bottom: 1rem; box-shadow: 0 4px 12px rgba(0,0,0,0.03); border: 1px solid #f1f3f5; transition: all 0.2s ease; animation: fadeIn 0.5s ease;";

    li.innerHTML = `
        <div class="package-item-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; padding-bottom: 0.75rem; border-bottom: 1px solid #f8f9fa;">
          <strong class="package-item-name" style="font-size: 0.95rem; color: #212529; font-weight: 600;">${pkgName}</strong>
          <span class="badge" style="background: #e7f5ff; color: #1c7ed6; padding: 0.25rem 0.6rem; border-radius: 6px; font-size: 0.75rem; font-weight: 600; display: flex; align-items: center; gap: 0.25rem;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>
            ${newItemsQty}
          </span>
        </div>
        
        <div class="package-items-preview" style="margin-bottom: 1rem; font-size: 0.85rem; color: #495057;">
          ${previewHtml}
        </div>

        <button class="btn-package-edit" data-package-id="${pkgId}" style="width: 100%; padding: 0.6rem; background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; color: #495057; font-weight: 600; font-size: 0.85rem; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 0.5rem; transition: all 0.2s;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
          Chỉnh sửa
        </button>
      `;

    li.querySelector('.btn-package-edit').addEventListener('click', openPackageEditModal);
    list.prepend(li);
  }
}


// ==================== SIDE PANEL UI ====================
function togglePanelVisibility(button) {
  const panel = button.closest('.pack-side-panel');
  if (!panel) return;

  const isCollapsed = panel.classList.toggle('collapsed');
  button.textContent = isCollapsed ? 'Hiện' : 'Ẩn';
}


/**
 * Cập nhật giao diện thẻ gói bên Side Panel sau khi chỉnh sửa
 */
function updateSidePanelUI(pkgData) {
  if (!pkgData || !pkgData.package_id) return;

  const pkgId = pkgData.package_id;
  const card = document.querySelector(`.package-item-card[data-package-id="${pkgId}"]`);

  if (!card) {
    console.warn("Không tìm thấy thẻ gói để cập nhật:", pkgId);
    return;
  }

  const items = pkgData.items || [];
  const totalQty = items.reduce((sum, item) => sum + (parseFloat(item.qty) || parseFloat(item.qty_done) || 0), 0);

  const badge = card.querySelector('.badge');
  if (badge) {
    badge.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>
        ${totalQty}
      `;
  }

  const aggregatedItems = {};
  items.forEach(item => {
    const rawQty = parseFloat(item.qty) || parseFloat(item.qty_done) || 0;
    if (rawQty <= 0) return;

    let displayName = item.product_name;
    if (item.product_barcode && !displayName.startsWith('[')) {
      displayName = `[${item.product_barcode}] ${displayName}`;
    }

    if (aggregatedItems[displayName]) {
      aggregatedItems[displayName] += rawQty;
    } else {
      aggregatedItems[displayName] = rawQty;
    }
  });

  const previewContainer = card.querySelector('.package-items-preview');
  if (previewContainer) {
    let html = '';
    for (const [name, qty] of Object.entries(aggregatedItems)) {
      html += `
          <div class="preview-item" style="display: flex; justify-content: space-between; margin-bottom: 0.35rem; align-items: center;">
            <span class="preview-item-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 75%; color: #495057; font-size: 0.85rem;">${name}</span>
            <span class="preview-item-qty" style="font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">x${qty}</span>
          </div>
       `;
    }

    if (!html) {
      html = '<div class="preview-empty" style="font-style: italic; color: #adb5bd;">Gói rỗng</div>';
    }

    previewContainer.innerHTML = html;

    card.style.transition = 'background-color 0.3s';
    card.style.backgroundColor = '#fff9db';
    setTimeout(() => card.style.backgroundColor = 'white', 600);
  }
}
