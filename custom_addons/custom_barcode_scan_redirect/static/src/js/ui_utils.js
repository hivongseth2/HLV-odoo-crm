/**
 * ui_utils.js — UI Utilities
 * Generic modal creation and package UI optimization.
 * No external dependencies.
 */

function createModal(title, content, buttons = []) {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.style.cssText = `
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center;
    z-index: 10000;
  `;

  const modalContent = document.createElement('div');
  modalContent.style.cssText = `
    background: #fff; border-radius: 12px; padding: 20px; max-width: 600px;
    width: 90%; max-height: 80vh; overflow-y: auto; box-shadow: 0 10px 40px rgba(0,0,0,0.2);
  `;

  const titleEl = document.createElement('h2');
  titleEl.textContent = title;
  titleEl.style.margin = '0 0 16px 0';
  modalContent.appendChild(titleEl);

  if (typeof content === 'string') {
    const contentDiv = document.createElement('div');
    contentDiv.innerHTML = content;
    modalContent.appendChild(contentDiv);
  } else {
    modalContent.appendChild(content);
  }

  const buttonContainer = document.createElement('div');
  buttonContainer.style.cssText = 'display: flex; gap: 10px; margin-top: 20px; justify-content: flex-end;';

  buttons.forEach(btn => {
    const button = document.createElement('button');
    button.textContent = btn.label;
    button.style.cssText = `
      padding: 10px 16px; border: none; border-radius: 8px;
      cursor: pointer; font-size: 14px; font-weight: 600;
      background: ${btn.color || '#3b82f6'}; color: #fff;
    `;
    button.addEventListener('click', () => {
      btn.onclick();
      modal.remove();
    });
    buttonContainer.appendChild(button);
  });

  modalContent.appendChild(buttonContainer);
  modal.appendChild(modalContent);

  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.remove();
  });

  document.body.appendChild(modal);
  return modal;
}

// ============================================================
// HÀM DỌN DẸP UI KHI VỪA F5 (GỘP DÒNG & FORMAT TÊN)

function optimizePackageUI() {
  const packageCards = document.querySelectorAll('.package-item-card');
  const allMainItems = document.querySelectorAll('#product_list .product-item');

  packageCards.forEach(card => {
    const previewContainer = card.querySelector('.package-items-preview');
    if (!previewContainer) return;

    const items = previewContainer.querySelectorAll('.preview-item');
    const aggregated = {};

    items.forEach(item => {
      // Lấy tên gốc và làm sạch
      let originalName = item.querySelector('.preview-item-name').innerText.trim();
      let compareName = originalName.toLowerCase();

      let qtyText = item.querySelector('.preview-item-qty').innerText.toLowerCase().replace('x', '');
      let qty = parseFloat(qtyText) || 0;

      if (qty <= 0) {
        item.remove();
        return;
      }

      // --- LOGIC TÌM MÃ (SỬA ĐỂ ƯU TIÊN DEFAULT CODE) ---
      let finalName = originalName;

      // Nếu tên chưa có [...], đi tìm mã
      if (!originalName.startsWith('[')) {
        for (let mainItem of allMainItems) {
          const mainRawText = mainItem.querySelector('strong')?.innerText || '';
          const mainCompare = mainRawText.toLowerCase().trim();

          // So sánh tương đối
          if (mainCompare.includes(compareName) || compareName.includes(mainCompare)) {

            // 👇 SỬA Ở ĐÂY: Lấy data-default-code trước
            const code = mainItem.getAttribute('data-default-code') || mainItem.getAttribute('data-barcode');

            if (code) {
              finalName = `[${code}] ${originalName}`;
            } else {
              // Fallback: Nếu không có attribute, lấy luôn text gốc bên trái nếu nó có dạng [Mã]
              if (mainRawText.trim().startsWith('[')) {
                finalName = mainRawText.trim();
              }
            }
            break;
          }
        }
      }

      // Gom nhóm
      if (aggregated[finalName]) {
        aggregated[finalName].qty += qty;
        aggregated[finalName].elementsToRemove.push(item);
      } else {
        aggregated[finalName] = {
          qty: qty,
          mainElement: item,
          elementsToRemove: []
        };
      }
    });

    // Render lại DOM
    for (const [name, data] of Object.entries(aggregated)) {
      data.elementsToRemove.forEach(el => el.remove());

      const mainEl = data.mainElement;
      const nameEl = mainEl.querySelector('.preview-item-name');
      const qtyEl = mainEl.querySelector('.preview-item-qty');

      if (nameEl) {
        nameEl.innerText = name;
        nameEl.style.color = "#495057";
        nameEl.style.fontSize = "0.85rem";
      }

      if (qtyEl) {
        qtyEl.innerText = `x${data.qty}`;
        qtyEl.style.cssText = "font-weight: 600; color: #343a40; background: #f1f3f5; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;";
      }

      mainEl.style.display = 'flex';
      mainEl.style.justifyContent = 'space-between';
      mainEl.style.marginBottom = '0.35rem';
      mainEl.style.alignItems = 'center';
    }
  });
}
