/** @odoo-module **/

import { Component, onWillStart, useState, xml } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { geocodeStops, getCurrentPosition } from "../../services/google_maps_utils";
import { sortNearestStops, formatDistance, formatDuration, distanceMeters } from "../../services/route_math";
import { RouteMap } from "./route_map";
import { RouteStopList } from "./route_stop_list";

export class DeliveryRouteApp extends Component {
    static template = xml`<main class="hlv-delivery-route"
                                t-att-class="{ 'is-history': state.view === 'history' }">
            <t t-if="state.isLoading">
                <div class="hlv-route-loading">
                    <span class="hlv-loading-dot"></span>
                    <span>Đang tải tuyến giao hàng...</span>
                </div>
            </t>
            <t t-else="">
                <t t-if="state.view === 'history'">
                    <section class="hlv-history-view">
                        <header class="hlv-history-header">
                            <div>
                                <h1>Lịch sử giao hàng</h1>
                                <p>Thống kê hiệu suất và đơn hàng đã hoàn thành</p>
                            </div>
                        </header>

                        <div class="hlv-history-stats">
                            <article>
                                <span>⏱ THỜI GIAN TRUNG BÌNH</span>
                                <strong><t t-esc="historyAverageText"/></strong>
                            </article>
                            <article>
                                <span>✓ ĐÃ GIAO HÔM NAY</span>
                                <strong><t t-esc="state.deliveredPickings.length"/> đơn</strong>
                            </article>
                        </div>

                        <h2>Đơn hàng thành công</h2>
                        <div class="hlv-history-list">
                            <t t-if="state.historyLoading">
                                <div class="hlv-history-empty">Đang tải lịch sử...</div>
                            </t>
                            <t t-elif="!state.deliveredPickings.length">
                                <div class="hlv-history-empty">Chưa có đơn giao thành công hôm nay.</div>
                            </t>
                            <t t-else="">
                                <t t-foreach="state.deliveredPickings" t-as="item" t-key="item.id">
                                    <article class="hlv-history-card">
                                        <div class="hlv-history-card-top">
                                            <div>
                                                <span>MÃ ĐƠN HÀNG</span>
                                                <strong><t t-esc="item.origin || item.name"/></strong>
                                            </div>
                                            <em>✓ Thành công</em>
                                        </div>
                                        <div class="hlv-history-address">
                                            <span><i class="fa fa-map-marker"></i></span>
                                            <b><t t-esc="item.address || item.partner_name || 'Không có địa chỉ'"/></b>
                                        </div>
                                        <div class="hlv-history-card-foot">
                                            <span><i class="fa fa-clock-o me-1"></i><t t-esc="item.date_done || '--:--'"/></span>
                                            <span>›</span>
                                        </div>
                                    </article>
                                </t>
                            </t>
                        </div>

                        <button class="hlv-history-back" t-on-click="closeHistory">
                            <span>▱</span> Quay lại bản đồ
                        </button>
                    </section>
                </t>
                <t t-elif="state.errorMessage">
                    <div class="hlv-route-empty">
                        <span class="hlv-empty-icon"><i class="fa fa-map-marker"></i></span>
                        <strong><t t-esc="state.errorMessage"/></strong>
                        <a class="btn btn-primary" t-att-href="state.scannerUrl">Mở giao hàng</a>
                    </div>
                </t>
                <t t-else="">
                    <section class="hlv-route-map-wrap">
                        <RouteMap apiKey="state.apiKey"
                                  origin="state.origin"
                                  stops="state.routeStops"
                                  started="false"
                                  focusStopId="currentStop ? currentStop.id : 0"
                                  onRouteSummary="onRouteSummary.bind(this)"
                                  onError="onMapError.bind(this)"></RouteMap>
                    </section>

                    <div class="hlv-route-topbar">
                        <button class="hlv-route-icon-btn" t-on-click="goBack" title="Quay lại">
                            <i class="fa fa-chevron-left"></i>
                        </button>
                        <div class="hlv-route-summary"><t t-esc="routeSummaryText"/></div>
                        <button class="hlv-route-icon-btn hlv-history-open-btn" t-on-click="openHistory" title="Lịch sử">Lịch sử</button>
                    </div>

                    <t t-if="state.warningMessage">
                        <div class="hlv-route-warning"><t t-esc="state.warningMessage"/></div>
                    </t>

                    <RouteStopList stops="state.routeStops"
                                   expanded="state.sheetExpanded"
                                   started="false"
                                   nextDistance="nextDistance"
                                   onExpand="expandSheet.bind(this)"
                                   onCollapse="collapseSheet.bind(this)"
                                   onReorder="onReorder.bind(this)"
                                   onNavigate="openTurnByTurn.bind(this)"></RouteStopList>

                    <button class="hlv-route-swipe hlv-route-swipe-fixed"
                            t-att-style="'--swipe-x:' + state.fabDragX + 'px'"
                            t-on-touchstart="onFabTouchStart"
                            t-on-touchmove="onFabTouchMove"
                            t-on-touchend="onFabTouchEnd"
                            t-on-pointerdown="onFabPointerDown">
                        <span><i class="fa fa-angle-right"></i></span>
                        <b>Vuốt để giao hàng</b>
                    </button>
                </t>
            </t>
        </main>`;
    static components = { RouteMap, RouteStopList };

    setup() {
        const config = window.HLV_SHIPPER_ROUTE_CONFIG || {};
        this.state = useState({
            apiKey: config.googleMapsApiKey || "",
            scannerUrl: config.scannerUrl || "/barcode/shipper#deliver",
            view: "map",
            isLoading: true,
            isRouting: false,
            historyLoading: false,
            sheetExpanded: false,
            errorMessage: "",
            warningMessage: "",
            origin: null,
            rawStops: [],
            routeStops: [],
            deliveredPickings: [],
            geocodeErrors: [],
            routeSummary: { distance: 0, duration: 0 },
            fabDragX: 0,
            fabDragMax: 0,
            fabDragging: false,
        });

        onWillStart(async () => {
            await this.bootstrapRoute();
            await this.loadDeliveryHistory();
        });
    }

    async bootstrapRoute() {
        this.state.isLoading = true;
        this.state.errorMessage = "";
        try {
            const res = await rpc("/api/barcode/delivery_route_stops", {});
            if (!res.success) {
                throw new Error(res.error || "Không thể tải điểm giao");
            }
            this.state.apiKey = this.state.apiKey || res.google_maps_api_key || "";
            this.state.rawStops = res.stops || [];
            if (res.missing_address?.length) {
                this.state.warningMessage = `${res.missing_address.length} phiếu chưa có địa chỉ giao hàng`;
            }
            if (!this.state.rawStops.length) {
                const receivedCount = res.received_count || 0;
                this.state.errorMessage = receivedCount
                    ? `Có ${receivedCount} đơn đã nhận nhưng chưa tìm được địa chỉ giao hàng.`
                    : "Chưa có đơn đã nhận để lập tuyến giao hàng.";
                return;
            }
            await this.buildInitialRoute();
        } catch (error) {
            this.state.errorMessage = error.message;
        } finally {
            this.state.isLoading = false;
        }
    }

    async buildInitialRoute() {
        this.state.isRouting = true;
        try {
            const position = await getCurrentPosition();
            this.updateRouteOrigin(position, { force: true });
            const geocoded = await geocodeStops(this.state.rawStops, {
                apiKey: this.state.apiKey,
                country: "VN",
            });
            this.state.geocodeErrors = geocoded.errors;
            this.state.routeStops = sortNearestStops(this.state.origin, geocoded.stops);
            if (!this.state.routeStops.length) {
                throw new Error("Không geocode được địa chỉ giao hàng nào.");
            }
        } finally {
            this.state.isRouting = false;
        }
    }

    async loadDeliveryHistory() {
        this.state.historyLoading = true;
        try {
            const today = new Date();
            const yyyy = today.getFullYear();
            const mm = String(today.getMonth() + 1).padStart(2, "0");
            const dd = String(today.getDate()).padStart(2, "0");
            const res = await rpc("/api/barcode/get_delivered", {
                date_filter: `${yyyy}-${mm}-${dd}`,
            });
            this.state.deliveredPickings = res.success ? (res.pickings || []) : [];
        } catch (error) {
            this.state.deliveredPickings = [];
        } finally {
            this.state.historyLoading = false;
        }
    }

    onReorder(stops) {
        this.state.routeStops = stops;
    }

    onRouteSummary(summary) {
        this.state.routeSummary = summary;
    }

    onMapError(message) {
        this.state.warningMessage = message;
    }

    expandSheet() {
        this.state.sheetExpanded = true;
    }

    collapseSheet() {
        this.state.sheetExpanded = false;
    }

    openHistory() {
        this.state.view = "history";
        this.loadDeliveryHistory();
    }

    closeHistory() {
        this.state.view = "map";
    }

    goBack() {
        window.history.back();
    }

    openScanner() {
        window.location.href = this.state.scannerUrl;
    }

    updateRouteOrigin(position) {
        const nextOrigin = {
            lat: position.coords.latitude,
            lng: position.coords.longitude,
        };
        this.state.origin = nextOrigin;
    }

    openTurnByTurn(stop = null) {
        const target = stop || this.currentStop;
        if (!target?.geocode) {
            return;
        }
        const params = new URLSearchParams({
            api: "1",
            destination: `${target.geocode.lat},${target.geocode.lng}`,
            travelmode: "driving",
            dir_action: "navigate",
        });
        if (this.state.origin) {
            params.set("origin", `${this.state.origin.lat},${this.state.origin.lng}`);
        }
        window.open(`https://www.google.com/maps/dir/?${params.toString()}`, "_blank", "noopener");
    }

    onFabTouchStart(ev) {
        const touch = ev.touches?.[0];
        this.fabStartX = touch ? touch.clientX : 0;
        this.state.fabDragMax = Math.max(0, (ev.currentTarget?.clientWidth || 0) - 54);
        this.state.fabDragging = true;
        this.state.fabDragX = 0;
    }

    onFabTouchMove(ev) {
        const touch = ev.touches?.[0];
        if (!touch || !this.state.fabDragging) {
            return;
        }
        this.state.fabDragX = Math.max(0, Math.min(this.state.fabDragMax, touch.clientX - this.fabStartX));
    }

    onFabTouchEnd() {
        if (this.state.fabDragMax && this.state.fabDragX > this.state.fabDragMax * 0.88) {
            this.openScanner();
            return;
        }
        this.state.fabDragging = false;
        this.state.fabDragX = 0;
    }

    onFabPointerDown(ev) {
        if (ev.pointerType === "touch") {
            return;
        }
        const target = ev.currentTarget;
        this.fabStartX = ev.clientX;
        this.state.fabDragMax = Math.max(0, target.clientWidth - 54);
        this.state.fabDragging = true;
        target.setPointerCapture?.(ev.pointerId);
        const onMove = (moveEv) => {
            this.state.fabDragX = Math.max(0, Math.min(this.state.fabDragMax, moveEv.clientX - this.fabStartX));
        };
        const onUp = () => {
            this.onFabTouchEnd();
            document.removeEventListener("pointermove", onMove);
            document.removeEventListener("pointerup", onUp);
            document.removeEventListener("pointercancel", onUp);
        };
        document.addEventListener("pointermove", onMove);
        document.addEventListener("pointerup", onUp);
        document.addEventListener("pointercancel", onUp);
    }

    get currentStopIndex() {
        return 0;
    }

    get currentStop() {
        return this.state.routeStops[this.currentStopIndex] || null;
    }

    get nextDistance() {
        if (!this.state.origin || !this.currentStop) {
            return 0;
        }
        return distanceMeters(this.state.origin, this.currentStop.geocode);
    }

    get nextDurationText() {
        const meters = this.nextDistance;
        if (!meters) {
            return "--";
        }
        return formatDuration((meters / 1000 / 30) * 3600);
    }

    get historyAverageText() {
        return this.state.deliveredPickings.length ? "12 phút/đơn" : "--";
    }

    get routeSummaryText() {
        const count = this.state.routeStops.length;
        const distance = formatDistance(this.state.routeSummary.distance);
        const duration = formatDuration(this.state.routeSummary.duration);
        return `${count} điểm giao · ${distance} · ${duration}`;
    }

    formatDistance(value) {
        return formatDistance(value);
    }
}
