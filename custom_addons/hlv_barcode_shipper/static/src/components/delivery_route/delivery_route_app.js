/** @odoo-module **/

import { Component, onWillStart, useState, xml } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
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
                                   onExpand="expandSheet.bind(this)"
                                   onCollapse="collapseSheet.bind(this)"
                                   onReorder="onReorder.bind(this)"
                                   onNavigate="openTurnByTurn.bind(this)"
                                   onNavigateAll="openAllTurnByTurn.bind(this)"></RouteStopList>

                    <button class="hlv-route-swipe hlv-route-swipe-fixed"
                            t-att-class="{ 'is-animating': state.isAnimating, 'is-success': state.isSuccess }"
                            t-att-style="'--swipe-x:' + state.fabDragX + 'px; --swipe-progress:' + (state.fabDragX / (state.fabDragMax || 1))"
                            t-on-pointerdown="onFabPointerDown">
                        <div class="swipe-progress-bg"></div>
                        <span>
                            <i t-if="!state.isSuccess" class="fa fa-angle-double-right"></i>
                            <i t-else="" class="fa fa-check"></i>
                        </span>
                        <b class="swipe-text">Vuốt để giao hàng</b>
                    </button>
                </t>
            </t>
        </main>`;
    static components = { RouteStopList };

    setup() {
        const config = window.HLV_SHIPPER_ROUTE_CONFIG || {};
        this.state = useState({
            scannerUrl: config.scannerUrl || "/barcode/shipper#deliver",
            view: "map",
            isLoading: true,
            historyLoading: false,
            sheetExpanded: false,
            errorMessage: "",
            warningMessage: "",
            rawStops: [],
            routeStops: [],
            deliveredPickings: [],
            fabDragX: 0,
            fabDragMax: 0,
            fabDragging: false,
            isAnimating: false,
            isSuccess: false,
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
            this.state.routeStops = this.state.rawStops;
        } catch (error) {
            this.state.errorMessage = error.message;
        } finally {
            this.state.isLoading = false;
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

    openTurnByTurn(stop = null) {
        const target = stop || this.currentStop;
        if (!target?.address) {
            return;
        }
        const params = new URLSearchParams({
            api: "1",
            destination: target.address,
            travelmode: "driving",
            dir_action: "navigate",
        });
        window.location.href = `https://www.google.com/maps/dir/?${params.toString()}`;
    }

    openAllTurnByTurn() {
        const stops = (this.state.routeStops || []).filter((stop) => stop.address && stop.state !== 'done' && stop.state !== 'cancel');
        if (!stops.length) {
            alert("Không có điểm giao nào cần chỉ đường.");
            return;
        }
        if (stops.length === 1) {
            this.openTurnByTurn(stops[0]);
            return;
        }
        const destination = stops[stops.length - 1].address;
        const waypoints = stops.slice(0, -1).map((stop) => stop.address).join("|");
        const params = new URLSearchParams({
            api: "1",
            destination,
            waypoints,
            travelmode: "driving",
            dir_action: "navigate",
        });
        window.location.href = `https://www.google.com/maps/dir/?${params.toString()}`;
    }

    onFabPointerDown(ev) {
        if (this.state.isSuccess) {
            return;
        }
        // Ngăn chọn chữ và các hành vi vuốt mặc định của trình duyệt
        ev.preventDefault();

        const target = ev.currentTarget;
        this.fabStartX = ev.clientX;
        this.state.fabDragMax = Math.max(0, (target.clientWidth || 0) - 54);
        this.state.fabDragging = true;
        this.state.fabDragX = 0;
        this.state.isAnimating = false;

        // Bắt trọn mọi chuyển động của ngón tay/chuột kể cả khi trượt ra ngoài
        target.setPointerCapture?.(ev.pointerId);

        const onMove = (moveEv) => {
            if (!this.state.fabDragging || this.state.isSuccess) return;
            moveEv.preventDefault();
            const rawX = moveEv.clientX - this.fabStartX;
            this.state.fabDragX = Math.max(0, Math.min(this.state.fabDragMax, rawX));
        };

        const onUp = (upEv) => {
            target.releasePointerCapture?.(upEv.pointerId);
            document.removeEventListener("pointermove", onMove);
            document.removeEventListener("pointerup", onUp);
            document.removeEventListener("pointercancel", onUp);

            this.state.fabDragging = false;
            this.state.isAnimating = true;

            const threshold = this.state.fabDragMax * 0.8;
            if (this.state.fabDragX >= threshold) {
                this.state.fabDragX = this.state.fabDragMax;
                this.state.isSuccess = true;
                setTimeout(() => {
                    this.state.isSuccess = false;
                    this.state.fabDragX = 0;
                    this.openScanner();
                }, 300);
            } else {
                this.state.fabDragX = 0;
            }
        };

        document.addEventListener("pointermove", onMove, { passive: false });
        document.addEventListener("pointerup", onUp);
        document.addEventListener("pointercancel", onUp);
    }

    get currentStopIndex() {
        return 0;
    }

    get currentStop() {
        return this.state.routeStops[this.currentStopIndex] || null;
    }

    get historyAverageText() {
        return this.state.deliveredPickings.length ? "12 phút/đơn" : "--";
    }

    get routeSummaryText() {
        const count = this.state.routeStops.length;
        return `${count} điểm giao`;
    }
}
