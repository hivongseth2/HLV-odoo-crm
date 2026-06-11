/** @odoo-module **/

import { Component, onMounted, onPatched, useRef } from "@odoo/owl";
import { loadGoogleMaps } from "../../services/google_maps_utils";

export class RouteMap extends Component {
    static props = {
        apiKey: { type: String, optional: true },
        origin: { type: Object, optional: true },
        stops: { type: Array, optional: true },
        started: { type: Boolean, optional: true },
        onRouteSummary: { type: Function, optional: true },
        onError: { type: Function, optional: true },
    };

    static template = "hlv_barcode_shipper.RouteMap";

    setup() {
        this.mapRef = useRef("map");
        this.map = null;
        this.directionsService = null;
        this.directionsRenderer = null;
        this.markers = [];
        this.lastSignature = "";

        onMounted(() => this.renderMap());
        onPatched(() => this.renderRouteIfChanged());
    }

    async renderMap() {
        try {
            const maps = await loadGoogleMaps(this.props.apiKey);
            const center = this.props.origin || { lat: 10.8231, lng: 106.6297 };
            this.map = new maps.Map(this.mapRef.el, {
                center,
                zoom: 12,
                disableDefaultUI: true,
                zoomControl: true,
                mapTypeControl: false,
                streetViewControl: false,
                fullscreenControl: false,
            });
            this.directionsService = new maps.DirectionsService();
            this.directionsRenderer = new maps.DirectionsRenderer({
                map: this.map,
                suppressMarkers: true,
                polylineOptions: {
                    strokeColor: "#1f7a1f",
                    strokeWeight: 5,
                    strokeOpacity: 0.92,
                },
            });
            this.renderRouteIfChanged(true);
        } catch (error) {
            this.props.onError?.(error.message);
        }
    }

    signature() {
        const origin = this.props.origin ? `${this.props.origin.lat},${this.props.origin.lng}` : "";
        const stops = (this.props.stops || []).map((stop) => `${stop.id}:${stop.geocode.lat},${stop.geocode.lng}`).join("|");
        return `${origin}|${stops}`;
    }

    clearMarkers() {
        this.markers.forEach((marker) => marker.setMap(null));
        this.markers = [];
    }

    async renderRouteIfChanged(force = false) {
        if (!this.map || !this.directionsService || !this.directionsRenderer) {
            return;
        }
        const signature = this.signature();
        if (!force && signature === this.lastSignature) {
            return;
        }
        this.lastSignature = signature;
        this.clearMarkers();

        const stops = this.props.stops || [];
        if (!this.props.origin || !stops.length) {
            return;
        }

        const maps = window.google.maps;
        const originMarker = new maps.Marker({
            map: this.map,
            position: this.props.origin,
            label: { text: "K", color: "#ffffff", fontWeight: "700" },
            title: "Vị trí hiện tại",
        });
        this.markers.push(originMarker);

        stops.forEach((stop, index) => {
            const marker = new maps.Marker({
                map: this.map,
                position: stop.geocode,
                label: { text: String(index + 1), color: "#ffffff", fontWeight: "700" },
                title: stop.picking_name,
            });
            this.markers.push(marker);
        });

        const destination = stops[stops.length - 1].geocode;
        const waypoints = stops.slice(0, -1).map((stop) => ({
            location: stop.geocode,
            stopover: true,
        }));

        this.directionsService.route({
            origin: this.props.origin,
            destination,
            waypoints,
            optimizeWaypoints: false,
            travelMode: maps.TravelMode.DRIVING,
        }, (response, status) => {
            if (status !== "OK") {
                this.props.onError?.(`Không thể vẽ tuyến: ${status}`);
                return;
            }
            this.directionsRenderer.setDirections(response);
            const legs = response.routes?.[0]?.legs || [];
            const distance = legs.reduce((sum, leg) => sum + (leg.distance?.value || 0), 0);
            const duration = legs.reduce((sum, leg) => sum + (leg.duration?.value || 0), 0);
            this.props.onRouteSummary?.({ distance, duration });
        });
    }
}
