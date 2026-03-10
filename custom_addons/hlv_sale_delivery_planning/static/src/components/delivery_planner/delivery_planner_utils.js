/** @odoo-module **/

/**
 * delivery_planner_utils.js
 * Các hàm tiện ích thuần túy (pure functions) cho Delivery Planner Dashboard:
 * - Dịch trạng thái (translate*)
 * - Lấy CSS class màu sắc (get*BadgeClass / get*ColorClass)
 * - Format số và tiền tệ (format*)
 */

// ---------------------------------------------------------------------------
// Translations
// ---------------------------------------------------------------------------

export function translateDeliveryStatus(status) {
    const trans = {
        unknown:         'Chưa cập nhật',
        pending:         'CHƯA GIAO',
        unshipped:       'CHƯA GIAO',
        partial:         'Giao 1 phần',
        pending_partial: 'Chưa & Giao 1 phần',
        full:            'Đã giao đủ',
    };
    return trans[status] || (status ? status.toUpperCase() : '');
}

export function translatePickingState(state) {
    const trans = {
        draft:     'Nháp',
        waiting:   'Chờ phiếu khác',
        confirmed: 'Chờ hàng',
        assigned:  'Sẵn sàng',
        done:      'Hoàn thành',
        cancel:    'Đã hủy',
    };
    return trans[state] || state;
}

export function translatePickingStatus(state) {
    const trans = {
        draft:     'Nháp',
        waiting:   'Chờ QĐ',
        confirmed: 'Chờ hàng',
        assigned:  'Sẵn sàng',
        done:      'Hoàn thành',
        cancel:    'Hủy',
    };
    return trans[state] || (state ? state.toUpperCase() : '');
}

export function translateStockStatus(status) {
    const trans = {
        out_of_stock:  'Không có hàng',
        partial_ready: 'Có hàng 1 phần',
        ready:         'Đủ hàng xuất',
    };
    return trans[status] || (status ? status.toUpperCase() : '');
}

export function translatePackingStatus(status) {
    const trans = {
        waiting_stock: 'Không Có Hàng Đóng',
        unpacked:      'Có Hàng Chưa Đóng Gói',
        partial_packed:'Đã Đóng 1 Phần',        // backward compatibility
        fully_packed:  'Đã Đóng Gói Đủ',
        delivered:     'Đã Giao Đủ',
    };
    return trans[status] || (status ? status.toUpperCase() : '');
}

export function translateSOStatus(status) {
    const trans = {
        draft:  'Báo giá',
        sent:   'Đã gửi',
        sale:   'Đơn hàng',
        done:   'Khóa',
        cancel: 'Đã hủy',
    };
    return trans[status] || (status ? status.toUpperCase() : '');
}

export function translatePOStatus(receiptStatus) {
    const trans = {
        partial: 'Nhận 1 phần',
        pending: 'Chưa nhận',
        full:    'Đã nhận đủ',
        unknown: 'Không rõ',
    };
    return trans[receiptStatus] || 'Mới Tạo / Hủy';
}

// ---------------------------------------------------------------------------
// CSS Badge / Color Classes
// ---------------------------------------------------------------------------

export function getPickingStateBadgeClass(state) {
    const mapping = {
        draft:     'bg-light text-dark',
        waiting:   'bg-warning text-dark',
        confirmed: 'bg-info text-white',
        assigned:  'bg-primary text-white',
        done:      'bg-success text-white',
        cancel:    'bg-danger text-white',
    };
    return mapping[state] || 'bg-secondary text-white';
}

export function getPickingStatusBadgeClass(state) {
    if (state === 'done')     return 'text-bg-success';
    if (state === 'assigned') return 'text-bg-primary';
    if (state === 'cancel')   return 'text-bg-secondary opacity-50';
    return 'text-bg-warning';
}

export function getDeliveryStatusBadgeClass(status) {
    if (status === 'full')    return 'text-bg-success';
    if (status === 'partial') return 'text-bg-warning';
    if (status === 'pending') return 'text-bg-secondary';
    return 'text-bg-light border text-dark';
}

export function getStockStatusBadgeClass(status) {
    if (status === 'ready')         return 'text-bg-primary';
    if (status === 'partial_ready') return 'text-bg-warning';
    if (status === 'out_of_stock')  return 'text-bg-danger';
    return 'text-bg-light border text-dark';
}

export function getPackingStatusBadgeClass(status) {
    if (status === 'fully_packed')  return 'text-bg-success';
    if (status === 'partial_packed')return 'text-bg-info';        // backward compat
    if (status === 'unpacked')      return 'text-bg-warning';     // có hàng → đóng ngay!
    if (status === 'waiting_stock') return 'text-bg-secondary';   // chờ hàng về
    if (status === 'delivered')     return 'text-bg-secondary';
    return 'text-bg-light border text-dark';
}

export function getPOStatusBadgeClass(state, receiptStatus) {
    if (state === 'cancel')                      return 'text-bg-secondary';
    if (receiptStatus === 'full')                return 'text-bg-success';
    if (receiptStatus === 'partial')             return 'text-bg-info';
    if (state === 'purchase' || state === 'done')return 'text-bg-primary';
    return 'text-bg-light border text-dark';
}

export function getSOCardColorClass(so) {
    if (so.real_delivery_status === 'full')    return 'border-success border-2 shadow-sm';
    if (so.stock_status === 'ready')           return 'border-primary border-2 shadow-sm';
    if (so.stock_status === 'partial_ready')   return 'border-warning border-2 shadow-sm';
    return 'border-danger border-2 shadow-sm';
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

export function formatCurrency(value) {
    return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(value);
}

export function formatQty(value) {
    return parseFloat(Number(value).toFixed(2));
}

export function getDatesComparisonClass(soDate, poDate) {
    if (!soDate || !poDate) return '';
    return new Date(poDate) > new Date(soDate) ? 'text-danger fw-bold' : 'text-success';
}
