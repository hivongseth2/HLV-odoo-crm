/** @odoo-module */

/**
 * HLV Browser Back Button
 * 
 * Thay đổi hành vi của nút back trong Odoo:
 * - Sử dụng history.back() của trình duyệt thay vì navigation mặc định
 * - Giữ nguyên các bộ lọc và trạng thái tìm kiếm
 * 
 * Approach: Sử dụng MutationObserver để thay đổi behavior của back button
 * vì OWL framework xử lý events ở cấp component, không phải DOM events.
 */

// Hàm thay đổi behavior của back button
function modifyBackButton(backButton) {
    if (!backButton || backButton.dataset.hlvModified) return;

    // Đánh dấu đã xử lý để không xử lý lại
    backButton.dataset.hlvModified = 'true';

    // Clone element để remove OWL event handlers
    const link = backButton.querySelector('a') || backButton;
    if (!link) return;

    // Thêm onclick handler với highest priority
    link.onclick = function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        ev.stopImmediatePropagation();

        console.log('[HLV] Back button clicked - using history.back()');
        window.history.back();

        return false;
    };

    // Cũng capture mousedown để ngăn OWL xử lý
    link.onmousedown = function (ev) {
        ev.stopPropagation();
    };

    console.log('[HLV] Modified back button:', link);
}

// Scan và modify tất cả back buttons hiện có
function scanAndModifyBackButtons() {
    const backButtons = document.querySelectorAll('.o_back_button');
    backButtons.forEach(modifyBackButton);
}

// Khởi tạo MutationObserver để theo dõi DOM changes
function initObserver() {
    const observer = new MutationObserver((mutations) => {
        let shouldScan = false;

        for (const mutation of mutations) {
            if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        // Check if it's a back button or contains one
                        if (node.classList?.contains('o_back_button') ||
                            node.querySelector?.('.o_back_button')) {
                            shouldScan = true;
                            break;
                        }
                        // Also check for breadcrumb container
                        if (node.classList?.contains('o_breadcrumb') ||
                            node.querySelector?.('.o_breadcrumb')) {
                            shouldScan = true;
                            break;
                        }
                    }
                }
            }
            if (shouldScan) break;
        }

        if (shouldScan) {
            // Delay một chút để OWL render xong
            setTimeout(scanAndModifyBackButtons, 100);
        }
    });

    // Observe toàn bộ document
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    console.log('[HLV] MutationObserver initialized');
}

// Khởi tạo module
function init() {
    // Scan ngay lập tức
    scanAndModifyBackButtons();

    // Thiết lập observer cho dynamic content
    initObserver();

    // Scan lại sau mỗi 2 giây (backup)
    setInterval(scanAndModifyBackButtons, 2000);

    console.log('[HLV] Browser Back Button module initialized');
}

// Khởi tạo khi document ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

console.log('[HLV] Browser Back Button module loaded');
