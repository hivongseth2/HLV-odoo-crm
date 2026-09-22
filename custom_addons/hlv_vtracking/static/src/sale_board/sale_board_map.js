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
    // Ghim kho: vẽ một lần rồi giữ nguyên. Tách khỏi lớp xe vì xe được vẽ lại mỗi nhịp
    // cập nhật vị trí (30 giây), còn kho thì không đổi — gộp chung là vẽ lại kho vô ích.
    let placeLayer = null;

    /* Dựng bản đồ. Gọi khi khung bản đồ ĐÃ hiện trên trang: Leaflet đo kích thước khung
       lúc khởi tạo, dựng trên khung đang ẩn thì bản đồ ra méo (chỉ vẽ một dải nhỏ góc trên)
       cho tới khi có ai gọi invalidateSize(). Vì vậy trang chỉ gọi open() sau khi đã bỏ lớp
       ẩn, và open() tự gọi invalidateSize() cho lần mở lại. */
    function open(config) {
        if (map) {
            map.invalidateSize();
            return map;
        }
        map = L.map("vt-map").setView(DEFAULT_CENTER, DEFAULT_ZOOM);
        L.tileLayer(config.tile_url || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution: config.tile_attribution || "© OpenStreetMap contributors",
            maxZoom: 19,
        }).addTo(map);
        return map;
    }

    function isOpen() {
        return Boolean(map);
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

    /* Vẽ lại vị trí xe. KHÔNG tự dựng bản đồ: nhịp này chạy mỗi 30 giây kể cả khi người
       dùng chưa chọn chuyến nào, dựng bản đồ ở đây là tải tile cho một khung đang ẩn. Trang
       gọi lại hàm này ngay sau khi mở bản đồ để bù nhịp đã bỏ. */
    function update(vehicles) {
        if (!map) {
            return;
        }
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

    /* Vẽ các KHO lên bản đồ. Gọi một lần mỗi lần tải lại cả trang, không gọi trong nhịp
       cập nhật vị trí xe.

       Kho là mốc quy chiếu của mọi chuyến nên luôn hiện, kể cả khi chưa mở chuyến nào:
       không có nó thì một chấm xe giữa bản đồ không cho biết xe đang đi ra hay đang về. */
    function showPlaces(places) {
        if (!map) {
            return;
        }
        if (placeLayer) {
            placeLayer.remove();
            placeLayer = null;
        }
        const items = (places || []).filter((place) => place.latitude && place.longitude);
        if (!items.length) {
            return;
        }
        placeLayer = L.layerGroup().addTo(map);
        for (const place of items) {
            L.circleMarker([place.latitude, place.longitude], {
                radius: 9,
                weight: 3,
                color: "#ffffff",
                fillColor: place.color || "#b91c1c",
                fillOpacity: 1,
            })
                // Nhãn hiện thường trực: số kho ít nên không làm rối, mà phải đọc được tên
                // kho ngay chứ không bắt bấm vào từng ghim.
                .bindTooltip(place.name || "Kho", { permanent: true, direction: "right" })
                .addTo(placeLayer);
        }
    }

    /* Vẽ (hoặc tắt) lộ trình của một chuyến: kho -> các điểm theo đúng thứ tự ghé.

       Nét LIỀN khi chuyến đã lấy được đường đi thật từ Google Routes (plan.road_polyline);
       nét ĐỨT khi chưa có, vì lúc đó chỉ là đường nối thẳng các điểm — vẽ liền một vệt
       không phải đường xe chạy chỉ khiến người xem tin vào thứ không có. Thứ tự ghé đã đổi
       sau khi lấy đường (road_route_stale) cũng quay về nét đứt: đường lưu lại là của thứ
       tự cũ. */
    /* Luôn vẽ, không bật/tắt: việc "bấm lại để đóng" do trang quyết định (đóng cả cột chi
       tiết lẫn bản đồ), không phải việc của lớp vẽ.

       ``fit`` = có căn lại khung nhìn về toàn tuyến hay không. Lượt làm tươi định kỳ gọi
       với fit=false: vẽ lại đường cho khớp dữ liệu mới nhưng KHÔNG kéo bản đồ về chỗ khác —
       người đang phóng to xem một điểm mà cứ 2 phút bị giật về toàn tuyến là không xem được. */
    function showRoute(plan, fit) {
        if (!map) {
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
        routeLayer = L.layerGroup().addTo(map);
        const roadPoints = roadRoutePoints(plan);
        if (roadPoints.length >= 2) {
            L.polyline(roadPoints, { color: "#0d6efd", weight: 4, opacity: .85 })
                .addTo(routeLayer);
        } else {
            L.polyline(points, { color: "#0d6efd", weight: 3, opacity: .8, dashArray: "6 4" })
                .addTo(routeLayer);
        }
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
        if (fit !== false) {
            map.fitBounds(points, { padding: [40, 40] });
        }
        return true;
    }

    /* Toạ độ đường đi thật đã giải mã, hoặc mảng rỗng khi không dùng được. Bộ giải mã dùng
       CHUNG với bản đồ backend (vtracking_polyline_codec.js) — một bản duy nhất. */
    function roadRoutePoints(plan) {
        if (!plan.road_polyline || plan.road_route_stale || !window.VtPolylineCodec) {
            return [];
        }
        return window.VtPolylineCodec.decode(plan.road_polyline);
    }

    function clearRoute() {
        if (routeLayer) {
            routeLayer.remove();
            routeLayer = null;
        }
    }

    /* Kéo bản đồ tới một điểm giao khi người dùng bấm "Xem trên bản đồ" ở danh sách. */
    function focus(latitude, longitude, label) {
        if (!map) {
            return;
        }
        map.setView([latitude, longitude], 15);
        L.popup({ closeButton: true })
            .setLatLng([latitude, longitude])
            .setContent(escapeHtml(label || ""))
            .openOn(map);
    }

    return { open, isOpen, update, showPlaces, showRoute, clearRoute, focus };
})();
