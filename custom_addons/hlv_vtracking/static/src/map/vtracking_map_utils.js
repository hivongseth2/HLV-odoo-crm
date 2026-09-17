/** @odoo-module **/

/* Hàm thuần dùng cho màn bản đồ: vào gì ra nấy, không đụng DOM, không đụng state.
   Tách riêng để sửa cách hiển thị mà không phải mở file component. */

// Màu theo trạng thái. Xám cho mất liên lạc: không phải cảnh báo đỏ, nhưng cũng không
// được trông giống xe đang hoạt động bình thường.
const STATUS_COLORS = {
    run: "#0d9488",
    stop: "#f59e0b",
    park: "#2563eb",
    offline: "#9ca3af",
    badgps: "#a855f7",
};
const STALE_COLOR = "#9ca3af";
const UNKNOWN_COLOR = "#6b7280";

/**
 * Màu ghim của một xe.
 * @param {Object} vehicle bản ghi xe từ get_vtracking_map_data
 * @returns {string} mã màu hex. Xe mất liên lạc luôn ra màu xám dù trạng thái là gì.
 */
export function statusColor(vehicle) {
    if (!vehicle) {
        return UNKNOWN_COLOR;
    }
    if (vehicle.is_stale) {
        return STALE_COLOR;
    }
    return STATUS_COLORS[vehicle.status] || UNKNOWN_COLOR;
}

/**
 * Khoảng cách từ một mốc thời gian tới bây giờ, dạng người đọc được.
 * @param {string} isoValue chuỗi ISO có hậu tố Z, hoặc rỗng
 * @returns {string} ví dụ "3 phút trước". Rỗng/không đọc được trả "chưa có dữ liệu".
 */
export function formatAgo(isoValue) {
    if (!isoValue) {
        return "chưa có dữ liệu";
    }
    const moment = new Date(isoValue);
    if (Number.isNaN(moment.getTime())) {
        return "chưa có dữ liệu";
    }
    const seconds = Math.floor((Date.now() - moment.getTime()) / 1000);
    if (seconds < 60) {
        return "vừa xong";
    }
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) {
        return `${minutes} phút trước`;
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
        return `${hours} giờ ${minutes % 60} phút trước`;
    }
    return `${Math.floor(hours / 24)} ngày trước`;
}

/**
 * Tốc độ kèm đơn vị.
 * @param {number} value km/h
 * @returns {string} ví dụ "42 km/h". Không có số trả "0 km/h".
 */
export function formatSpeed(value) {
    const speed = Number(value);
    return `${Number.isFinite(speed) ? Math.round(speed) : 0} km/h`;
}
