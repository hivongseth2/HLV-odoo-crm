/** @odoo-module **/

/* Bản đồ theo dõi đội xe.

   Leaflet nạp động từ CDN chứ không khai trong asset bundle: bundle backend được gộp và
   phục vụ cho MỌI trang của Odoo, không đáng bắt cả hệ thống tải thư viện bản đồ chỉ vì
   một màn hình. Nạp động cũng cho phép báo rõ khi mạng chặn CDN, thay vì hiện một ô
   trắng không ai hiểu vì sao.

   Màn hình phải dùng được khi KHÔNG vẽ được bản đồ: danh sách xe bên trái vẫn đủ để biết
   xe nào đang chạy, đang đỗ, mất liên lạc. */

import { Component, onWillStart, onWillUnmount, onMounted, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadLeaflet } from "./vtracking_leaflet_loader";
import {
    statusColor,
    formatAgo,
    formatSpeed,
    formatMoney,
    filterBySearch,
    planLineFlags,
} from "./vtracking_map_utils";
import { clearPlaces, drawPlaces } from "./vtracking_map_places";
import { clearRoute, drawRoute, routableStopCount } from "./vtracking_map_route";
import { VtrackingPlanTable } from "./vtracking_plan_table";

// Bản đồ tự tải lại theo chu kỳ này. 30 giây khớp với nhịp cron đồng bộ chậm nhất mà vẫn
// đủ tươi để nhìn xe di chuyển; ngắn hơn chỉ làm tăng tải cho Odoo chứ dữ liệu không mới hơn.
const REFRESH_MS = 30000;

// Khung nhìn mặc định khi chưa có xe nào có toạ độ: Đông Nam Bộ.
const DEFAULT_CENTER = [10.85, 106.9];
const DEFAULT_ZOOM = 9;

export class VtrackingMap extends Component {
    static template = "hlv_vtracking.Map";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.mapRef = useRef("map");
        this.state = useState({
            vehicles: [],
            places: [],
            placeTypes: [],
            hiddenTypeIds: [],
            showVehicles: true,
            selectedId: null,
            selectedPlaceId: null,
            routePlanId: null,
            search: "",
            loading: true,
            mapError: "",
            lastRefresh: null,
        });

        this.leaflet = null;
        this.map = null;
        this.markers = new Map();
        this.placeMarkers = new Map();
        this.routeLayer = null;
        this.timer = null;

        onWillStart(async () => {
            await this.reload();
            try {
                this.leaflet = await loadLeaflet();
            } catch (error) {
                // Không có bản đồ vẫn dùng được danh sách — nói rõ lý do thay vì im lặng.
                this.state.mapError = error.message;
            }
        });

        // Nút trong popup nằm trong HTML thô do Leaflet dựng, Owl không gắn được
        // t-on-click vào đó. Nghe uỷ quyền ở khung bản đồ: popup của Leaflet nằm bên
        // trong khung này, và khung sống lâu hơn từng popup nên không phải gắn lại mỗi
        // lượt làm tươi.
        this.onMapClick = (ev) => this.handlePopupClick(ev);

        onMounted(() => {
            this.buildMap();
            this.mapRef.el?.addEventListener("click", this.onMapClick);
            this.timer = setInterval(() => this.reload(), REFRESH_MS);
        });

        onWillUnmount(() => {
            if (this.timer) {
                clearInterval(this.timer);
            }
            this.mapRef.el?.removeEventListener("click", this.onMapClick);
            if (this.map) {
                this.map.remove();
                this.map = null;
            }
        });
    }

    // ------------------------------------------------------------------
    // Dữ liệu
    // ------------------------------------------------------------------
    async reload() {
        const data = await this.orm.call("fleet.vehicle", "get_vtracking_map_data", []);
        this.config = data;
        this.state.vehicles = data.vehicles;
        this.state.loading = false;
        this.state.lastRefresh = new Date();
        this.drawMarkers();

        // Địa điểm gần như không đổi nên chỉ nhận ở lượt tải ĐẦU: lượt làm tươi 30 giây
        // là để theo dõi xe, vẽ lại hàng trăm ghim đứng yên mỗi lần là phí.
        if (!this.placesLoaded) {
            this.state.places = data.places;
            this.state.placeTypes = data.place_types;
            this.state.hiddenTypeIds = data.place_types
                .filter((t) => !t.visible_by_default)
                .map((t) => t.id);
            this.placesLoaded = true;
            this.drawPlaceLayer();
        }

        // Lộ trình đang hiện phải vẽ lại theo dữ liệu vừa tải: kế hoạch có thể đã đổi
        // thứ tự điểm hoặc thêm bớt phiếu trong lúc màn hình đang mở.
        if (this.state.routePlanId) {
            this.drawRouteLayer();
        }
    }

    drawPlaceLayer() {
        if (!this.map || !this.leaflet) {
            return;
        }
        clearPlaces(this.placeMarkers);
        this.placeMarkers = drawPlaces(
            this.leaflet,
            this.map,
            this.state.places,
            new Set(this.state.hiddenTypeIds)
        );
    }

    togglePlaceType(typeId) {
        const hidden = this.state.hiddenTypeIds;
        const index = hidden.indexOf(typeId);
        if (index === -1) {
            hidden.push(typeId);
        } else {
            hidden.splice(index, 1);
        }
        this.drawPlaceLayer();
    }

    toggleVehicles() {
        this.state.showVehicles = !this.state.showVehicles;
        this.drawMarkers();
    }

    isTypeVisible(typeId) {
        return !this.state.hiddenTypeIds.includes(typeId);
    }

    placeCountOfType(typeId) {
        return this.state.places.filter((p) => p.type_id === typeId).length;
    }

    // ------------------------------------------------------------------
    // Lọc danh sách bên trái
    // ------------------------------------------------------------------
    // Ô tìm kiếm áp cho CẢ xe lẫn địa điểm: người dùng gõ "nhon trach" mà không cần
    // biết trước thứ mình tìm là xe đang ở đó hay cái kho ở đó.
    get visibleVehicles() {
        if (!this.state.showVehicles) {
            return [];
        }
        return filterBySearch(this.state.vehicles, this.state.search, [
            "name",
            "driver_name",
            "device_driver_name",
            "geocoding",
        ]);
    }

    get visiblePlaces() {
        const shown = this.state.places.filter(
            (place) => !this.state.hiddenTypeIds.includes(place.type_id)
        );
        return filterBySearch(shown, this.state.search, [
            "name",
            "partner_name",
            "address",
            "type_name",
        ]);
    }

    get hasResults() {
        return this.visibleVehicles.length > 0 || this.visiblePlaces.length > 0;
    }

    get locatedCount() {
        return this.state.vehicles.filter((v) => v.latitude && v.longitude).length;
    }

    // ------------------------------------------------------------------
    // Bản đồ
    // ------------------------------------------------------------------
    buildMap() {
        if (!this.leaflet || !this.mapRef.el || this.map) {
            return;
        }
        const L = this.leaflet;
        this.map = L.map(this.mapRef.el).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
        L.tileLayer(this.config.tile_url, {
            attribution: this.config.tile_attribution,
            maxZoom: 19,
        }).addTo(this.map);
        this.drawMarkers();
        this.drawPlaceLayer();
        this.drawRouteLayer();
        this.fitToVehicles();
    }

    drawMarkers() {
        if (!this.map) {
            return;
        }
        const L = this.leaflet;
        const seen = new Set();
        const vehicles = this.state.showVehicles ? this.state.vehicles : [];

        for (const vehicle of vehicles) {
            if (!vehicle.latitude || !vehicle.longitude) {
                continue;
            }
            seen.add(vehicle.id);
            const position = [vehicle.latitude, vehicle.longitude];
            let marker = this.markers.get(vehicle.id);
            if (marker) {
                marker.setLatLng(position);
                marker.setStyle({ fillColor: statusColor(vehicle) });
            } else {
                marker = L.circleMarker(position, {
                    radius: 9,
                    weight: 2,
                    color: "#ffffff",
                    fillColor: statusColor(vehicle),
                    fillOpacity: 1,
                });
                marker.on("click", () => this.selectVehicle(vehicle.id, false));
                marker.addTo(this.map);
                this.markers.set(vehicle.id, marker);
            }
            // bindTooltip/bindPopup gọi lại mỗi lượt làm tươi để nội dung đổi theo dữ
            // liệu mới; Leaflet thay nội dung cũ chứ không chồng thêm.
            marker.bindTooltip(vehicle.name);
            // Rộng và cao hơn mặc định vì popup chứa cả danh sách điểm giao; maxHeight
            // để Leaflet tự cho cuộn thay vì đẩy popup tràn khỏi màn hình.
            marker.bindPopup(this.popupHtml(vehicle), { maxWidth: 360, maxHeight: 420 });
        }

        // Xe bị tắt theo dõi giữa chừng phải biến mất khỏi bản đồ, nếu không ghim sẽ đứng
        // mãi ở vị trí cuối cùng và người xem tưởng xe vẫn đang ở đó.
        for (const [id, marker] of this.markers) {
            if (!seen.has(id)) {
                marker.remove();
                this.markers.delete(id);
            }
        }
    }

    popupHtml(vehicle) {
        const rows = [
            ["Trạng thái", vehicle.status_label],
            ["Tốc độ", formatSpeed(vehicle.speed)],
            ["Vị trí", vehicle.geocoding || "—"],
            ["Tài xế", vehicle.driver_name || vehicle.device_driver_name || "—"],
            ["Tin lúc", formatAgo(vehicle.position_at)],
        ];
        if (vehicle.alarm_text) {
            rows.push(["Cảnh báo", vehicle.alarm_text]);
        }
        const body = rows
            .map(([label, value]) => `<div><strong>${label}:</strong> ${this.escape(value)}</div>`)
            .join("");
        return `<div class="o_vt_popup"><div class="o_vt_popup_title">${this.escape(
            vehicle.name
        )}</div>${body}${this.planHtml(vehicle)}</div>`;
    }

    /** Khối kế hoạch/thực tế trong popup xe. Rỗng khi xe không có kế hoạch hôm nay. */
    planHtml(vehicle) {
        const plans = vehicle.plans || [];
        if (!plans.length) {
            return `<div class="o_vt_plan_empty">Hôm nay chưa có kế hoạch giao.</div>`;
        }
        return plans.map((plan) => this.onePlanHtml(plan)).join("");
    }

    onePlanHtml(plan) {
        const stateLabel =
            { draft: "nháp", confirmed: "đã chốt", done: "xong" }[plan.state] || plan.state;
        const warn = plan.missing_coords_count
            ? `<div class="o_vt_plan_warn">${plan.missing_coords_count} điểm chưa có toạ độ — km đang thiếu</div>`
            : "";
        // Phần thực tế luôn hiện, kể cả khi chưa có số: người xem phải thấy được rằng
        // "kế hoạch 12 đơn" chưa nói gì về việc đã giao mấy đơn.
        const actual = plan.has_actual_data
            ? `<div><strong>Đã giao:</strong> ${plan.actual_line_count} phiếu · ${formatMoney(
                  plan.actual_amount_total
              )} · ${plan.actual_distance_km || 0} km thực chạy</div>`
            : `<div class="o_vt_plan_pending">Thực tế: chưa nối module shipper</div>`;
        return `
            <div class="o_vt_plan">
                <div class="o_vt_plan_head">
                    <span>${this.escape(plan.session_label)} · ${this.escape(stateLabel)}</span>
                    <span class="o_vt_plan_btns">
                        <button type="button" class="o_vt_plan_table_btn" data-vt-route-id="${
                            plan.id
                        }">${this.state.routePlanId === plan.id ? "Ẩn lộ trình" : "Lộ trình"}</button>
                        <button type="button" class="o_vt_plan_table_btn" data-vt-plan-id="${
                            plan.id
                        }">Xem bảng</button>
                    </span>
                </div>
                <div><strong>Kế hoạch:</strong> ${plan.line_count} điểm · ${formatMoney(
            plan.amount_total
        )}</div>
                <div><strong>Dự kiến:</strong> ${plan.distance_km || 0} km · ${this.escape(
            plan.duration_display || "—"
        )}</div>
                ${warn}
                ${this.planLinesHtml(plan)}
                ${actual}
            </div>`;
    }

    /** Danh sách chứng từ của một kế hoạch, theo đúng thứ tự ghé. */
    planLinesHtml(plan) {
        const lines = plan.lines || [];
        if (!lines.length) {
            return "";
        }
        const rows = lines
            .map((line, index) => {
                const flags = planLineFlags(line)
                    .filter((flag) => flag.tone === "warn")
                    .map((flag) => `<span class="o_vt_plan_warn">${this.escape(flag.label)}</span>`);
                const tick = line.delivered ? "✓ " : "";
                const money = formatMoney(line.amount);
                return `<li>
                    <span class="o_vt_line_no">${index + 1}.</span>
                    <span class="o_vt_line_main">${tick}${this.escape(
                    line.reference
                )} · ${this.escape(line.partner_name || "—")}</span>
                    <span class="o_vt_line_amount">${money}</span>
                    ${flags.length ? `<div class="o_vt_line_flags">${flags.join(" · ")}</div>` : ""}
                </li>`;
            })
            .join("");
        // Cuộn trong popup thay vì cắt bớt: xe chở 15 điểm thì phải xem được cả 15, mà
        // popup cao quá màn hình thì không đóng lại được.
        return `<ul class="o_vt_plan_lines">${rows}</ul>`;
    }

    /** Bấm nút trong popup: "Xem bảng" mở hộp thoại, "Xem lộ trình" vẽ lên bản đồ. */
    handlePopupClick(ev) {
        const tableButton = ev.target.closest?.("[data-vt-plan-id]");
        if (tableButton) {
            const plan = this.findPlan(Number(tableButton.dataset.vtPlanId));
            if (plan) {
                this.dialog.add(VtrackingPlanTable, {
                    plan: plan.plan,
                    vehicleName: plan.vehicleName,
                });
            }
            return;
        }
        const routeButton = ev.target.closest?.("[data-vt-route-id]");
        if (routeButton) {
            this.toggleRoute(Number(routeButton.dataset.vtRouteId));
        }
    }

    /** Tìm kế hoạch theo id trong mọi xe. Trả về {plan, vehicleName} hoặc null. */
    findPlan(planId) {
        for (const vehicle of this.state.vehicles) {
            const plan = (vehicle.plans || []).find((p) => p.id === planId);
            if (plan) {
                return { plan, vehicleName: vehicle.name };
            }
        }
        return null;
    }

    // ------------------------------------------------------------------
    // Lộ trình dự kiến
    // ------------------------------------------------------------------
    toggleRoute(planId) {
        // Bấm lại đúng kế hoạch đang hiện thì tắt: không có nút "ẩn" riêng, vì nút riêng
        // chỉ nằm trong popup mà popup thì thường đã bị đóng lúc người dùng muốn tắt.
        this.state.routePlanId = this.state.routePlanId === planId ? null : planId;
        this.drawRouteLayer();
    }

    drawRouteLayer() {
        if (!this.map || !this.leaflet) {
            return;
        }
        clearRoute(this.map, this.routeLayer);
        this.routeLayer = null;
        if (!this.state.routePlanId) {
            return;
        }
        const found = this.findPlan(this.state.routePlanId);
        if (!found) {
            // Kế hoạch biến mất sau một lượt làm tươi (bị xoá, đổi ngày) — quên nó đi
            // thay vì giữ một id trỏ vào hư không.
            this.state.routePlanId = null;
            return;
        }
        this.routeLayer = drawRoute(this.leaflet, this.map, found.plan);
    }

    get routeInfo() {
        const found = this.state.routePlanId && this.findPlan(this.state.routePlanId);
        if (!found) {
            return null;
        }
        const plan = found.plan;
        return {
            vehicleName: found.vehicleName,
            sessionLabel: plan.session_label,
            drawn: routableStopCount(plan),
            total: plan.line_count,
            distance: plan.distance_km || 0,
            duration: plan.duration_display || "—",
        };
    }

    hideRoute() {
        this.state.routePlanId = null;
        this.drawRouteLayer();
    }

    escape(value) {
        const div = document.createElement("div");
        div.textContent = value == null ? "" : String(value);
        return div.innerHTML;
    }

    fitToVehicles() {
        if (!this.map) {
            return;
        }
        const points = this.state.vehicles
            .filter((v) => v.latitude && v.longitude)
            .map((v) => [v.latitude, v.longitude]);
        if (points.length) {
            this.map.fitBounds(points, { padding: [40, 40], maxZoom: 15 });
        }
    }

    // ------------------------------------------------------------------
    // Tương tác
    // ------------------------------------------------------------------
    selectVehicle(vehicleId, pan = true) {
        this.state.selectedId = vehicleId;
        this.state.selectedPlaceId = null;
        const vehicle = this.state.vehicles.find((v) => v.id === vehicleId);
        if (!vehicle || !this.map) {
            return;
        }
        const marker = this.markers.get(vehicleId);
        if (pan && vehicle.latitude && vehicle.longitude) {
            this.map.setView([vehicle.latitude, vehicle.longitude], 16);
        }
        marker?.openPopup();
    }

    selectPlace(placeId) {
        this.state.selectedPlaceId = placeId;
        this.state.selectedId = null;
        const place = this.state.places.find((p) => p.id === placeId);
        if (!place || !this.map) {
            return;
        }
        this.map.setView([place.latitude, place.longitude], 16);
        this.placeMarkers.get(placeId)?.openPopup();
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    statusClass(vehicle) {
        if (vehicle.is_stale) {
            return "o_vt_dot o_vt_dot_stale";
        }
        return `o_vt_dot o_vt_dot_${vehicle.status || "none"}`;
    }

    formatAgo(value) {
        return formatAgo(value);
    }

    formatSpeed(value) {
        return formatSpeed(value);
    }
}

registry.category("actions").add("hlv_vtracking_map", VtrackingMap);
