/** @odoo-module **/

import { Component, onMounted, onPatched, useRef, xml } from "@odoo/owl";
import { loadGoogleMaps } from "../../services/google_maps_utils";

export class RouteMap extends Component {
    static props = {
        apiKey: { type: String, optional: true },
        origin: { type: Object, optional: true },
        stops: { type: Array, optional: true },
        started: { type: Boolean, optional: true },
        focusStopId: { type: Number, optional: true },
        onRouteSummary: { type: Function, optional: true },
        onError: { type: Function, optional: true },
    };

    static template = xml`<div class="hlv-route-map" t-ref="map"></div>`;

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
        const stops = (this.props.stops || [])
            .map((stop) => `${stop.id}:${stop.geocode.lat},${stop.geocode.lng}`)
            .join("|");
        return `${origin}|${stops}|${this.props.focusStopId || ""}|${this.props.started ? "1" : "0"}`;
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
        const markerIcon = (text, fill) => ({
            url: this.markerSvg(text, fill),
            scaledSize: new maps.Size(36, 42),
            anchor: new maps.Point(18, 42),
            labelOrigin: new maps.Point(18, 15),
        });

        this.markers.push(new maps.Marker({
            map: this.map,
            position: this.props.origin,
            icon: markerIcon("K", "#238636"),
            title: "Current position",
        }));

        stops.forEach((stop, index) => {
            const isFocus = this.props.focusStopId === stop.id;
            this.markers.push(new maps.Marker({
                map: this.map,
                position: stop.geocode,
                icon: markerIcon(String(index + 1), isFocus ? "#39a844" : "#31556a"),
                title: stop.picking_name,
                zIndex: isFocus ? 20 : 10,
            }));
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
                this.props.onError?.(`Cannot draw route: ${status}`);
                return;
            }
            this.directionsRenderer.setDirections(response);
            const legs = response.routes?.[0]?.legs || [];
            const distance = legs.reduce((sum, leg) => sum + (leg.distance?.value || 0), 0);
            const duration = legs.reduce((sum, leg) => sum + (leg.duration?.value || 0), 0);
            this.props.onRouteSummary?.({ distance, duration });
            if (this.props.started && stops[0]?.geocode) {
                this.map.panTo(stops[0].geocode);
                this.map.setZoom(15);
            }
        });
    }

    markerSvg(text, fill) {
        const safeText = String(text).replace(/[<>&"]/g, "");
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="42" viewBox="0 0 36 42">
            <path d="M18 41s14-13.2 14-25A14 14 0 1 0 4 16c0 11.8 14 25 14 25z" fill="${fill}"/>
            <circle cx="18" cy="16" r="10.5" fill="rgba(255,255,255,.18)"/>
            <text x="18" y="20" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" font-weight="700" fill="#fff">${safeText}</text>
        </svg>`;
        return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
    }
}
