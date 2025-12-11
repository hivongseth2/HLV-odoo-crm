/** @odoo-module */

/**
 * HLV Browser Back Button
 * 
 * Thay đổi hành vi của nút back trong Odoo:
 * - Sử dụng history.back() của trình duyệt thay vì navigation mặc định
 * - Đưa người dùng về đúng trang trước đó trong lịch sử duyệt web
 * - Giữ nguyên các bộ lọc và trạng thái tìm kiếm
 */

// Event handler for back button clicks
function handleBackButtonClick(ev) {
    // Tìm back button được click (li.o_back_button a)
    const backButtonLink = ev.target.closest('.o_back_button a, .o_back_button');

    if (!backButtonLink) return;

    // Ngăn chặn hành vi mặc định của Odoo
    ev.preventDefault();
    ev.stopPropagation();
    ev.stopImmediatePropagation();

    console.log('[HLV] Back button clicked - using history.back()');

    // Sử dụng history.back() để quay lại trang trước đó
    window.history.back();

    return false;
}

// Khởi tạo module
function initBrowserBackButton() {
    // Thêm event listener với capture phase (true) để chạy TRƯỚC Odoo handlers
    document.addEventListener('click', handleBackButtonClick, true);

    console.log('[HLV] Browser Back Button module initialized');
}

// Khởi tạo ngay khi module được load
initBrowserBackButton();

console.log('[HLV] Browser Back Button module loaded - Back button now uses browser history');
