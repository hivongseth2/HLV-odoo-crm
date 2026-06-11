/** @odoo-module **/

import { Component, onWillStart, useState, xml } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { geocodeStops, getCurrentPosition } from "../../services/google_maps_utils";
import { sortNearestStops, formatDistance, formatDuration, distanceMeters } from "../../services/route_math";
import { RouteMap } from "./route_map";
import { RouteStopList } from "./route_stop_list";

export class DeliveryRouteApp extends Component {
    static template = xml`<main class="hlv-delivery-route" t-att-class="{ 'is-started': state.started }">
            <t t-if="state.isLoading">
                <div class="hlv-route-loading">
                    <i class="fa fa-spinner fa-spin"></i>
                    <span>Đang tải tuyến giao hàng...</span>
                </div>
            </t>
            <t t-else="">
                <t t-if="state.errorMessage">
                    <div class="hlv-route-empty">
                        <i class="fa fa-route"></i>
                        <strong><t t-esc="state.errorMessage"/></strong>
                        <a class="btn btn-primary" t-att-href="state.scannerUrl">Mở giao hàng</a>
                    </div>
                </t>
                <t t-else="">
                    <section class="hlv-route-map-wrap">
                        <RouteMap apiKey="state.apiKey"
                                  origin="state.origin"
                                  stops="state.routeStops"
                                  started="state.started"
                                  onRouteSummary="onRouteSummary.bind(this)"
                                  onError="onMapError.bind(this)"></RouteMap>
                    </section>

                    <div class="hlv-route-topbar">
                        <button class="hlv-route-icon-btn" t-on-click="goBack" title="Quay lại">
                            <i class="fa fa-arrow-left"></i>
                        </button>
                        <div class="hlv-route-summary"><t t-esc="routeSummaryText"/></div>
                        <button class="hlv-route-icon-btn" t-on-click="bootstrapRoute.bind(this)" title="Tải lại">
                            <i class="fa fa-sync-alt"></i>
                        </button>
                    </div>

                    <t t-if="state.warningMessage">
                        <div class="hlv-route-warning"><t t-esc="state.warningMessage"/></div>
                    </t>

                    <RouteStopList stops="state.routeStops"
                                   started="state.started"
                                   nextDistance="nextDistance"
                                   onReorder="onReorder.bind(this)"></RouteStopList>

                    <button t-if="!state.started"
                            class="hlv-route-start-btn"
                            t-on-click="startDelivery">
                        <i class="fa fa-location-arrow"></i> Bắt đầu giao hàng
                    </button>

                    <button t-if="state.started"
                            class="hlv-route-fab"
                            t-att-style="'transform: translateX(' + state.fabDragX + 'px)'"
                            t-on-click="openScanner"
                            t-on-touchstart="onFabTouchStart"
                            t-on-touchmove="onFabTouchMove"
                            t-on-touchend="onFabTouchEnd"
                            title="Giao hàng">
                        <i class="fa fa-truck"></i>
                        <span>Giao hàng</span>
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
            isLoading: true,
            isRouting: false,
            started: false,
            errorMessage: "",
            warningMessage: "",
            origin: null,
            rawStops: [],
            routeStops: [],
            geocodeErrors: [],
            routeSummary: { distance: 0, duration: 0 },
            fabDragX: 0,
            fabDragging: false,
        });

        onWillStart(async () => {
            await this.bootstrapRoute();
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
            this.state.origin = {
                lat: position.coords.latitude,
                lng: position.coords.longitude,
            };
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

    onReorder(stops) {
        this.state.routeStops = stops;
    }

    onRouteSummary(summary) {
        this.state.routeSummary = summary;
    }

    onMapError(message) {
        this.state.warningMessage = message;
    }

    startDelivery() {
        this.state.started = true;
    }

    goBack() {
        window.history.back();
    }

    openScanner() {
        window.location.href = this.state.scannerUrl;
    }

    onFabTouchStart(ev) {
        const touch = ev.touches?.[0];
        this.fabStartX = touch ? touch.clientX : 0;
        this.state.fabDragging = true;
        this.state.fabDragX = 0;
    }

    onFabTouchMove(ev) {
        const touch = ev.touches?.[0];
        if (!touch || !this.state.fabDragging) {
            return;
        }
        this.state.fabDragX = Math.max(-90, Math.min(90, touch.clientX - this.fabStartX));
    }

    onFabTouchEnd() {
        if (Math.abs(this.state.fabDragX) > 48) {
            this.openScanner();
            return;
        }
        this.state.fabDragging = false;
        this.state.fabDragX = 0;
    }

    get nextDistance() {
        if (!this.state.origin || !this.state.routeStops.length) {
            return 0;
        }
        return distanceMeters(this.state.origin, this.state.routeStops[0].geocode);
    }

    get routeSummaryText() {
        const count = this.state.routeStops.length;
        const distance = formatDistance(this.state.routeSummary.distance);
        const duration = formatDuration(this.state.routeSummary.duration);
        return `${count} điểm giao · ${distance} · ${duration}`;
    }
}
