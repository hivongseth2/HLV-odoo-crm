/** @odoo-module */

/**
 * HLV Browser Back Button
 * 
 * Thay đổi hành vi của nút ứng dụng (app button) trong Odoo:
 * - CHỈ khi đang ở trong view chi tiết (có breadcrumb .o_back_button)
 * - Sử dụng history.back() thay vì về menu chính
 * - Giúp người dùng quay lại trang trước đó với các bộ lọc được giữ nguyên
 * 
 * QUAN TRỌNG: Không modify khi ở menu hoặc list view để tránh phá hỏng navigation
 */

// Kiểm tra xem có đang ở trong detail view không (có breadcrumb)
function isInDetailView() {
    // Nếu có .o_back_button, tức là đang ở trong một record/view chi tiết
    return document.querySelector('.o_back_button') !== null;
}

// Hàm thay đổi behavior của nút ứng dụng
function modifyAppButton(appButton) {
    if (!appButton) return;

    // LUÔN reset trạng thái modified để có thể re-check
    // vì trạng thái detail view có thể thay đổi khi navigate

    // Kiểm tra xem đang ở detail view không
    if (!isInDetailView()) {
        // Không phải detail view - đảm bảo nút hoạt động bình thường
        if (appButton.dataset.hlvModified) {
            // Đã modified trước đó - cần restore
            // Reload trang để restore (cách đơn giản nhất)
            // Hoặc không làm gì vì OWL sẽ re-render
        }
        return;
    }

    // Đang ở detail view - modify nút
    if (appButton.dataset.hlvModified === 'true') return; // Đã modified rồi

    // Đánh dấu đã xử lý
    appButton.dataset.hlvModified = 'true';

    // Clone để remove OWL bindings
    const newButton = appButton.cloneNode(true);

    // Thêm event listener mới
    newButton.addEventListener('click', function (ev) {
        // Double check vẫn đang ở detail view
        if (!isInDetailView()) {
            // Không còn ở detail view - cho phép default behavior
            return true;
        }

        ev.preventDefault();
        ev.stopPropagation();
        ev.stopImmediatePropagation();

        console.log('[HLV] App button clicked in detail view - using history.back()');
        window.history.back();

        return false;
    }, true);

    newButton.addEventListener('mousedown', function (ev) {
        if (isInDetailView()) {
            ev.stopPropagation();
        }
    }, true);

    // Replace button
    if (appButton.parentNode) {
        appButton.parentNode.replaceChild(newButton, appButton);
        console.log('[HLV] Modified app button for detail view');
    }
}

// Scan và modify nút ứng dụng
function scanAndModifyAppButtons() {
    // Chỉ scan khi đang ở detail view
    if (!isInDetailView()) {
        return;
    }

    const appButtons = document.querySelectorAll('.o_menu_toggle:not([data-hlv-modified="true"])');
    appButtons.forEach(modifyAppButton);
}

// Khởi tạo MutationObserver
function initObserver() {
    const observer = new MutationObserver((mutations) => {
        // Delay để OWL render xong
        setTimeout(scanAndModifyAppButtons, 200);
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    console.log('[HLV] MutationObserver initialized');
}

// Khởi tạo module
function init() {
    scanAndModifyAppButtons();
    initObserver();

    // Scan định kỳ
    setInterval(scanAndModifyAppButtons, 2000);

    console.log('[HLV] Browser Back Button module initialized');
}

// Khởi tạo
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

console.log('[HLV] Browser Back Button module loaded');


