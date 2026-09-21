/* Bản đồ xe cho trang /giao-hang.

   Tách khỏi sale_board.js vì đây là việc khác hẳn: bảng chuyến vẽ lại toàn bộ mỗi lần có
   dữ liệu mới, còn bản đồ phải GIỮ nguyên khung nhìn và chỉ dời ghim — người đang phóng to
   xem một khu vực mà bản đồ tự nhảy về vị trí cũ là mất chỗ đang xem.

   Không dùng module ES: trang này là HTML tự dựng, nạp bằng thẻ <script> thường. */

window.VtSaleMap = (function () {
    const STATUS_COLOR = {
        run: "#198754",      // đang chạy
        stop: "#fd7e14",     // dừng máy nổ
        park: "#6c757d",     // đỗ
        offline: "#adb5bd",  // mất tín hiệu
        badgps: "#dc3545",
    };
    const DEFAULT_CENTER = [10.75, 106.92];
    const DEFAULT_ZOOM = 11;

    let map = null;
    let markers = new Map();
    let fitted = false;
    // Lộ trình đang vẽ: đường nối và các số thứ tự ghé. Giữ riêng để xoá gọn khi tắt.
    let routeLayer = null;
    let routePlanId = null;

    function ensureMap(config) {
        if (map) {
            return map;
        }
        map = L.map("vt-map").setView(DEFAULT_CENTER, DEFAULT_ZOOM);
        L.tileLayer(config.tile_url || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution: config.tile_attribution || "© OpenStreetMap contributors",
            maxZoom: 19,
        }).addTo(map);
        return map;
    }

    function icon(vehicle) {
        const color = STATUS_COLOR[vehicle.status] || STATUS_COLOR.offline;
        // Xe mất tín hiệu quá lâu vẽ rỗng ruột: nhìn là biết chấm đó không còn đáng tin.
        const fill = vehicle.is_stale ? "#fff" : color;
        return L.divIcon({
            className: "vt-marker",
            html: `<span class="vt-dot" style="background:${fill};border-color:${color}"></span>
                   <span class="vt-plate-tag">${vehicle.name || ""}</span>`,
            iconSize: [90, 18],
            iconAnchor: [9, 9],
        });
    }

    function popup(vehicle) {
        const rows = [
            ["Trạng thái", vehicle.status_label + (vehicle.is_stale ? " (tin cũ)" : "")],
            ["Tốc độ", `${Math.round(vehicle.speed || 0)} km/h`],
            ["Vị trí", vehicle.geocoding || "—"],
            ["Tài xế", vehicle.driver_name || "—"],
        ];
        const body = rows
            .map(([label, value]) => `<div><b>${label}:</b> ${escapeHtml(String(value))}</div>`)
            .join("");
        return `<div class="vt-popup"><div class="fw-bold mb-1">${escapeHtml(vehicle.name || "")}</div>${body}</div>`;
    }

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    function update(vehicles, config) {
        ensureMap(config || {});
        const seen = new Set();
        const points = [];
        for (const vehicle of vehicles) {
            if (!vehicle.latitude || !vehicle.longitude) {
                continue;
            }
            const position = [vehicle.latitude, vehicle.longitude];
            points.push(position);
            seen.add(vehicle.id);
            let marker = markers.get(vehicle.id);
            if (marker) {
                marker.setLatLng(position);
                marker.setIcon(icon(vehicle));
                marker.setPopupContent(popup(vehicle));
            } else {
                marker = L.marker(position, { icon: icon(vehicle) }).addTo(map);
                marker.bindPopup(popup(vehicle));
                markers.set(vehicle.id, marker);
            }
        }
        for (const [id, marker] of markers) {
            if (!seen.has(id)) {
                marker.remove();
                markers.delete(id);
            }
        }
        // Chỉ căn khung nhìn MỘT lần, lúc mới mở trang.
        if (!fitted && points.length) {
            map.fitBounds(points, { padding: [30, 30], maxZoom: 13 });
            fitted = true;
        }
    }

    /* Vẽ (hoặc tắt) lộ trình của một chuyến: kho -> các điểm theo đúng thứ tự ghé.

       Đường thẳng nối các điểm, KHÔNG phải đường đi thật — cả module tính km theo đường
       chim bay, vẽ đường cong giả ở đây chỉ khiến người xem tin vào thứ không có. */
    function toggleRoute(plan) {
        if (routePlanId === plan.id) {
            clearRoute();
            return false;
        }
        clearRoute();
        const points = [];
        if (plan.start) {
            points.push([plan.start.latitude, plan.start.longitude]);
        }
        const stops = plan.stops.filter((stop) => stop.latitude && stop.longitude);
        stops.forEach((stop) => points.push([stop.latitude, stop.longitude]));
        if (points.length < 2) {
            return false;
        }
        ensureMap({});
        routeLayer = L.layerGroup().addTo(map);
        L.polyline(points, { color: "#0d6efd", weight: 3, opacity: .8, dashArray: "6 4" })
            .addTo(routeLayer);
        if (plan.start) {
            L.circleMarker(points[0], { radius: 6, color: "#0d6efd", fillColor: "#fff", fillOpacity: 1 })
                .bindTooltip("Xuất phát: " + (plan.start.name || ""), { direction: "top" })
                .addTo(routeLayer);
        }
        stops.forEach((stop) => {
            L.marker([stop.latitude, stop.longitude], {
                icon: L.divIcon({
                    className: "vt-route-stop",
                    html: `<span class="vt-route-no ${stop.mine ? "vt-route-mine" : ""}">${stop.sequence}</span>`,
                    iconSize: [22, 22],
                    iconAnchor: [11, 11],
                }),
            })
                .bindTooltip(`${stop.sequence}. ${stop.partner_name || ""}`, { direction: "top" })
                .addTo(routeLayer);
        });
        map.fitBounds(points, { padding: [40, 40] });
        routePlanId = plan.id;
        return true;
    }

    function clearRoute() {
        if (routeLayer) {
            routeLayer.remove();
            routeLayer = null;
        }
        routePlanId = null;
    }

    /* Kéo bản đồ tới một điểm giao khi người dùng bấm "Xem trên bản đồ" ở danh sách. */
    function focus(latitude, longitude, label) {
        ensureMap({});
        map.setView([latitude, longitude], 15);
        L.popup({ closeButton: true })
            .setLatLng([latitude, longitude])
            .setContent(escapeHtml(label || ""))
            .openOn(map);
    }

    function shownRoute() {
        return routePlanId;
    }

    return { update, toggleRoute, clearRoute, shownRoute, focus };
})();
