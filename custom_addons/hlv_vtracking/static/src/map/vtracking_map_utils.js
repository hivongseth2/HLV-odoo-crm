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

/**
 * Rút gọn tên để in làm nhãn cố định trên bản đồ.
 *
 * Tên đối tác trong Odoo thường là pháp nhân đầy đủ ("CÔNG TY TNHH VI NA HOÀNG LONG VŨ -
 * TÂN SƠN NHÌ"), in nguyên vào nhãn thì một địa điểm che mất cả một góc bản đồ. Ưu tiên
 * cắt ở dấu gạch ngang phân nhánh — phần sau dấu gạch thường mới là thứ phân biệt hai
 * cơ sở, nên giữ nó và bỏ phần pháp nhân lặp lại ở mọi điểm.
 *
 * @param {string} value tên đầy đủ
 * @param {number} maxLength số ký tự tối đa (mặc định 24)
 * @returns {string} tên đã rút gọn. null/undefined trả "".
 */
export function shortLabel(value, maxLength = 24) {
    const text = String(value == null ? "" : value).trim();
    if (text.length <= maxLength) {
        return text;
    }
    const dashIndex = text.lastIndexOf(" - ");
    if (dashIndex > 0) {
        const tail = text.slice(dashIndex + 3).trim();
        if (tail && tail.length <= maxLength) {
            return tail;
        }
    }
    return text.slice(0, maxLength - 1).trimEnd() + "…";
}

/**
 * Chuẩn hoá chuỗi để so khớp khi tìm: thường hoá và BỎ DẤU tiếng Việt.
 *
 * Bỏ dấu là bắt buộc chứ không phải tiện nghi: tên địa điểm trong Odoo có dấu
 * ("Nhơn Trạch") còn người tìm thường gõ không dấu ("nhon trach"). Không bỏ dấu thì ô
 * tìm kiếm gần như vô dụng với dữ liệu tiếng Việt.
 *
 * @param {string} value chuỗi bất kỳ
 * @returns {string} chuỗi thường, không dấu. null/undefined trả "".
 */
export function searchKey(value) {
    return String(value == null ? "" : value)
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .replace(/đ/g, "d")
        .replace(/Đ/g, "D")
        .toLowerCase();
}

/**
 * Lọc danh sách theo chuỗi tìm kiếm, so trên các trường chỉ định.
 * @param {Array<Object>} items danh sách cần lọc
 * @param {string} needle chuỗi người dùng gõ; rỗng thì trả nguyên danh sách
 * @param {Array<string>} fields tên các trường đem ra so
 * @returns {Array<Object>} phần tử khớp, giữ nguyên thứ tự ban đầu
 */
export function filterBySearch(items, needle, fields) {
    const key = searchKey(needle).trim();
    if (!key) {
        return items;
    }
    return items.filter((item) =>
        fields.some((field) => searchKey(item[field]).includes(key))
    );
}
