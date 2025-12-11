/** @odoo-module */

/**
 * HLV Browser Back Button
 * 
 * Thay đổi hành vi của nút back (breadcrumb đầu tiên) trong Odoo:
 * - Sử dụng history.back() của trình duyệt thay vì restore action mặc định
 * - Đưa người dùng về đúng trang trước đó trong lịch sử duyệt web
 * - Giữ nguyên các bộ lọc và trạng thái tìm kiếm
 */

// Đợi DOM ready
function initBrowserBackButton() {
    // Event handler for breadcrumb clicks
    function handleBreadcrumbClick(ev) {
        // Tìm breadcrumb link đã được click
        const breadcrumbLink = ev.target.closest('.o_breadcrumb a');

        if (!breadcrumbLink) return;

        // Kiểm tra xem có phải là breadcrumb đầu tiên không
        const breadcrumbContainer = breadcrumbLink.closest('.o_breadcrumb');
        if (!breadcrumbContainer) return;

        const allBreadcrumbs = document.querySelectorAll('.o_breadcrumb .breadcrumb-item, .o_breadcrumb a');

        // Nếu breadcrumb link được click là link đầu tiên (back button)
        const allLinks = Array.from(document.querySelectorAll('.o_breadcrumb a'));
        const clickedIndex = allLinks.indexOf(breadcrumbLink);

        // Chỉ intercept nếu là click vào back button (breadcrumb đầu tiên)
        // và có nhiều hơn 1 breadcrumb
        if (clickedIndex === 0 && allLinks.length >= 1) {
            ev.preventDefault();
            ev.stopPropagation();
            ev.stopImmediatePropagation();

            console.log('[HLV] Back button clicked - using history.back()');
            window.history.back();
            return false;
        }
    }

    // Thêm event listener với capture phase để intercept trước Odoo
    document.addEventListener('click', handleBreadcrumbClick, true);

    console.log('[HLV] Browser Back Button module loaded - Back button now uses browser history');
}

// Khởi tạo ngay khi module được load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBrowserBackButton);
} else {
    initBrowserBackButton();
}
