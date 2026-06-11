/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { geocodeStops, getCurrentPosition } from "../../services/google_maps_utils";
import { sortNearestStops, formatDistance, formatDuration, distanceMeters } from "../../services/route_math";
import { RouteMap } from "./route_map";
import { RouteStopList } from "./route_stop_list";

export class DeliveryRouteApp extends Component {
    static template = "hlv_barcode_shipper.DeliveryRouteApp";
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
                this.state.errorMessage = "Chưa có đơn đã nhận có địa chỉ giao hàng.";
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
