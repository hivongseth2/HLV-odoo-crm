/** @odoo-module **/

/* Vẽ lộ trình DỰ KIẾN của một kế hoạch lên bản đồ.

   Hai kiểu đường, và kiểu vẽ chính là thông tin:

   - NÉT LIỀN: đường đi thật lấy từ Google Routes (plan.road_polyline). Vẽ liền được vì
     vệt đó đúng là đường xe sẽ chạy.
   - NÉT ĐỨT: chưa lấy được đường thật (tính năng tắt, chưa tới lượt cron, hoặc API lỗi) —
     chỉ là đường nối thẳng giữa các điểm theo thứ tự ghé. Nét đứt là có chủ ý: vẽ liền sẽ
     khiến người xem tin rằng xe chạy đúng theo vệt đó.

   Đổi thứ tự ghé sau khi đã lấy đường thật (plan.road_route_stale) thì đường lưu lại là
   của thứ tự CŨ — lúc đó quay về nét đứt, vì thà vẽ thô mà đúng thứ tự hiện tại còn hơn
   vẽ đẹp một lộ trình không còn tồn tại.

   Tách khỏi file vẽ xe và file vẽ địa điểm vì lộ trình có vòng đời riêng: nó chỉ tồn tại
   khi người dùng chọn xem một kế hoạch, và biến mất khi chọn kế hoạch khác. */

// Màu lộ trình: tím đậm, khác hẳn màu xe (xanh/vàng/lam) và màu ghim địa điểm mặc định,
// để đường kẻ không bị nhìn nhầm thành một lớp dữ liệu khác.
const ROUTE_COLOR = "#6d28d9";
const START_COLOR = "#b91c1c";

/**
 * Vẽ lộ trình của một kế hoạch.
 * @param {Object} L thư viện Leaflet
 * @param {Object} map đối tượng bản đồ
 * @param {Object} plan một phần tử trong vehicle.plans
 * @returns {Object|null} L.LayerGroup đã thêm vào bản đồ, hoặc null nếu không đủ điểm vẽ
 */
export function drawRoute(L, map, plan) {
    const stops = (plan.lines || []).filter((line) => line.latitude && line.longitude);
    const points = [];
    const layers = [];

    if (plan.start) {
        points.push([plan.start.latitude, plan.start.longitude]);
        layers.push(
            L.circleMarker([plan.start.latitude, plan.start.longitude], {
                radius: 8,
                weight: 3,
                color: "#ffffff",
                fillColor: START_COLOR,
                fillOpacity: 1,
            }).bindTooltip(`Xuất phát: ${plan.start.name || "kho"}`)
        );
    }

    for (const stop of stops) {
        points.push([stop.latitude, stop.longitude]);
        layers.push(
            L.marker([stop.latitude, stop.longitude], {
                icon: L.divIcon({
                    className: "o_vt_route_pin",
                    html: `<span>${stop.seq_no}</span>`,
                    iconSize: [22, 22],
                    iconAnchor: [11, 11],
                }),
                // Dưới ghim xe: xe là thứ đang chuyển động, phải nằm trên cùng.
                zIndexOffset: -100,
            }).bindTooltip(
                `${stop.seq_no}. ${stop.reference} — ${stop.partner_name || ""}`
            )
        );
    }

    // Một điểm thì không có đoạn nào để nối; vẫn vẽ ghim để biết nó nằm đâu.
    if (points.length >= 2) {
        layers.unshift(routeLine(L, plan, points));
    }
    if (!layers.length) {
        return null;
    }

    const group = L.layerGroup(layers).addTo(map);
    if (points.length) {
        map.fitBounds(points, { padding: [50, 50], maxZoom: 14 });
    }
    return group;
}

/**
 * Đường kẻ của lộ trình: đường đi thật nếu có, không thì đường nối thẳng các điểm.
 * @param {Object} L thư viện Leaflet
 * @param {Object} plan kế hoạch đang vẽ
 * @param {Array<[number, number]>} points toạ độ các điểm theo thứ tự ghé
 * @returns {Object} L.Polyline
 */
function routeLine(L, plan, points) {
    const roadPoints = roadRoutePoints(plan);
    if (roadPoints.length >= 2) {
        return L.polyline(roadPoints, {
            color: ROUTE_COLOR,
            weight: 4,
            opacity: 0.85,
            lineJoin: "round",
        });
    }
    return L.polyline(points, {
        color: ROUTE_COLOR,
        weight: 3,
        opacity: 0.85,
        dashArray: "8 7",
        lineJoin: "round",
    });
}

/**
 * Toạ độ đường đi thật đã giải mã, hoặc mảng rỗng khi không dùng được.
 *
 * Đọc bộ giải mã qua biến toàn cục đúng lúc gọi (giống cách dùng window.L): file codec
 * không phải module Odoo vì trang /giao-hang cũng dùng chung nó.
 */
function roadRoutePoints(plan) {
    if (!plan.road_polyline || plan.road_route_stale) {
        return [];
    }
    const codec = window.VtPolylineCodec;
    if (!codec) {
        return [];
    }
    return codec.decode(plan.road_polyline);
}

/**
 * Gỡ lộ trình khỏi bản đồ.
 * @param {Object} map đối tượng bản đồ
 * @param {Object|null} group kết quả của drawRoute
 */
export function clearRoute(map, group) {
    if (group) {
        map.removeLayer(group);
    }
}

/**
 * Đếm số điểm vẽ được của một kế hoạch.
 * @param {Object} plan một phần tử trong vehicle.plans
 * @returns {number} số điểm có toạ độ
 */
export function routableStopCount(plan) {
    return (plan.lines || []).filter((line) => line.latitude && line.longitude).length;
}
