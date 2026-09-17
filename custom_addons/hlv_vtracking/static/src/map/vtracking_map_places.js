/** @odoo-module **/

/* Vẽ lớp ĐỊA ĐIỂM (kho, đối tác...) lên bản đồ.

   Tách khỏi file vẽ xe vì hai lớp có vòng đời khác hẳn: xe di chuyển và được tải lại mỗi
   30 giây, địa điểm gần như không đổi nên chỉ tải một lần rồi giữ nguyên. Gộp chung sẽ
   khiến mỗi lượt làm tươi xe kéo theo việc vẽ lại hàng trăm ghim đứng yên. */

import { shortLabel } from "./vtracking_map_utils";

// Bán kính ghim theo cỡ khai ở loại địa điểm. Kho để "Lớn" thì nhìn thấy ngay giữa hàng
// trăm ghim đối tác — đó là lý do cỡ là thuộc tính của LOẠI, không phải của từng điểm.
const SIZE_RADIUS = { small: 5, normal: 7, large: 11 };

/**
 * Vẽ toàn bộ địa điểm lên bản đồ, thay thế lớp đang có.
 * @param {Object} L thư viện Leaflet
 * @param {Object} map đối tượng bản đồ
 * @param {Array} places danh sách địa điểm từ get_vtracking_map_data
 * @param {Set<number>} hiddenTypeIds id các loại người xem đang tắt
 * @returns {Map<number, Object>} marker theo id địa điểm, để lớp gọi còn xoá được
 */
export function drawPlaces(L, map, places, hiddenTypeIds) {
    const markers = new Map();
    for (const place of places) {
        if (!place.latitude || !place.longitude) {
            continue;
        }
        if (hiddenTypeIds.has(place.type_id)) {
            continue;
        }
        const radius = SIZE_RADIUS[place.size] || SIZE_RADIUS.normal;
        const marker = L.circleMarker([place.latitude, place.longitude], {
            radius,
            // Ghim vuông-ish nhờ viền dày và màu đặc: đủ để phân biệt với ghim xe ở xa,
            // mà không phải nạp thêm bộ icon ảnh nào.
            weight: place.size === "large" ? 3 : 2,
            color: "#ffffff",
            fillColor: place.color || "#7c3aed",
            fillOpacity: 0.95,
        });
        marker.bindPopup(placePopup(place));
        if (place.show_label) {
            // Nhãn cố định dùng tên RÚT GỌN; tên đầy đủ vẫn nằm trong popup khi bấm vào.
            marker.bindTooltip(shortLabel(place.name), {
                permanent: true,
                direction: "right",
                offset: [radius, 0],
                className: "o_vt_place_label",
            });
        } else {
            marker.bindTooltip(place.name);
        }
        marker.addTo(map);
        markers.set(place.id, marker);
    }
    return markers;
}

/**
 * Xoá mọi marker địa điểm khỏi bản đồ.
 * @param {Map} markers kết quả của drawPlaces
 */
export function clearPlaces(markers) {
    for (const marker of markers.values()) {
        marker.remove();
    }
    markers.clear();
}

function placePopup(place) {
    const rows = [
        ["Loại", place.type_name],
        ["Đối tác", place.partner_name],
        ["Địa chỉ", place.address],
        ["Điện thoại", place.phone],
    ];
    if (place.geo_state === "pending_review") {
        rows.push(["⚠️", "Toạ độ máy tra, chưa ai duyệt"]);
    }
    const body = rows
        .filter(([, value]) => value)
        .map(([label, value]) => `<div><strong>${label}:</strong> ${escapeHtml(value)}</div>`)
        .join("");
    return `<div class="o_vt_popup"><div class="o_vt_popup_title">${escapeHtml(
        place.name
    )}</div>${body}</div>`;
}

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
}
