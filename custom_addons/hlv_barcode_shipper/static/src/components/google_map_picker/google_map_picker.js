/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onMounted, useRef } from "@odoo/owl";
import { loadGoogleMaps } from "@hlv_barcode_shipper/services/google_maps_utils";
import { useService } from "@web/core/utils/hooks";

export class GoogleMapPicker extends Component {
    static template = "hlv_barcode_shipper.GoogleMapPicker";
    static props = { ...standardFieldProps };

    setup() {
        this.mapRef = useRef("mapContainer");
        this.searchInputRef = useRef("searchInput");
        this.coordDisplayRef = useRef("coordDisplay");
        this.orm = useService("orm");
        
        onMounted(async () => {
            // First try to get the API key from Barcode Shipper company settings
            const companyData = await this.orm.searchRead("res.company", [], ["hlv_barcode_google_maps_api_key"], { limit: 1 });
            
            // If not found, try to get it from standard Odoo base_geolocalize settings
            if (!apiKey) {
                apiKey = await this.orm.call("ir.config_parameter", "get_param", ["base_geolocalize.google_map_api_key"]);
            }
            
            if (!apiKey) {
                console.error("Missing Google Maps API Key in Company Settings or General Settings");
                return;
            }
            
            let maps;
            try {
                maps = await loadGoogleMaps(apiKey);
            } catch (error) {
                console.error("Lỗi khi tải Google Maps (Có thể do Trình chặn quảng cáo / Adblock):", error);
                alert("Không thể tải bản đồ. Vui lòng tắt trình chặn quảng cáo (Adblock) hoặc kiểm tra kết nối mạng!");
                return;
            }
            
            // Get coordinates from the record
            let lat = this.props.record.data.latitude || 21.028511; // Default Hanoi
            let lng = this.props.record.data.longitude || 105.804817;
            
            // Fix modal display issue by using timeout
            setTimeout(() => {
                this.map = new maps.Map(this.mapRef.el, {
                    center: { lat, lng },
                    zoom: 15,
                    disableDefaultUI: false,
                    mapId: "DEMO_MAP_ID",
                });
                
                this.marker = new maps.Marker({
                    position: { lat, lng },
                    map: this.map,
                    draggable: true,
                });
                
                this.marker.addListener("dragend", () => {
                    const pos = this.marker.getPosition();
                    const lLat = typeof pos.lat === "function" ? pos.lat() : pos.lat;
                    const lLng = typeof pos.lng === "function" ? pos.lng() : pos.lng;
                    this.props.record.update({ latitude: lLat, longitude: lLng });
                    this.updateCoordDisplay(lLat, lLng);
                });
                
                this.map.addListener("click", (e) => {
                    const pos = e.latLng;
                    this.marker.setPosition(pos);
                    const lLat = typeof pos.lat === "function" ? pos.lat() : pos.lat;
                    const lLng = typeof pos.lng === "function" ? pos.lng() : pos.lng;
                    this.props.record.update({ latitude: lLat, longitude: lLng });
                    this.updateCoordDisplay(lLat, lLng);
                });

                // Tích hợp Places Autocomplete
                if (maps.places && maps.places.Autocomplete) {
                    const autocomplete = new maps.places.Autocomplete(this.searchInputRef.el, {
                        fields: ["geometry", "name", "formatted_address"],
                    });
                    
                    autocomplete.addListener("place_changed", () => {
                        const place = autocomplete.getPlace();
                        if (!place.geometry || !place.geometry.location) {
                            return; // Fallback to searchAddress when user presses Enter
                        }
                        
                        const pos = place.geometry.location;
                        this.map.setCenter(pos);
                        this.map.setZoom(18);
                        this.marker.setPosition(pos);
                        
                        const lLat = typeof pos.lat === "function" ? pos.lat() : pos.lat;
                        const lLng = typeof pos.lng === "function" ? pos.lng() : pos.lng;
                        this.props.record.update({ latitude: lLat, longitude: lLng });
                        this.updateCoordDisplay(lLat, lLng);
                    });
                }
                
                // Initialize display
                this.updateCoordDisplay(lat, lng);
            }, 100);
        });
    }

    onKeydownSearch(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.searchAddress();
        }
    }

    searchAddress() {
        const address = this.searchInputRef.el.value;
        if (!address) return;
        
        const geocoder = new window.google.maps.Geocoder();
        geocoder.geocode({ address: address }, (results, status) => {
            if (status === "OK" && results && results.length > 0) {
                const pos = results[0].geometry.location;
                this.map.setCenter(pos);
                this.map.setZoom(18);
                this.marker.setPosition(pos);
                
                const lLat = typeof pos.lat === "function" ? pos.lat() : pos.lat;
                const lLng = typeof pos.lng === "function" ? pos.lng() : pos.lng;
                this.props.record.update({ latitude: lLat, longitude: lLng });
                this.updateCoordDisplay(lLat, lLng);
            } else {
                alert("Không tìm thấy vị trí cho địa chỉ này trên bản đồ!");
            }
        });
    }

    updateCoordDisplay(lat, lng) {
        if (this.coordDisplayRef.el) {
            this.coordDisplayRef.el.innerText = `${lat.toFixed(7)}, ${lng.toFixed(7)}`;
        }
    }

    copyCoords() {
        if (this.coordDisplayRef.el) {
            const text = this.coordDisplayRef.el.innerText;
            navigator.clipboard.writeText(text).then(() => {
                alert("Đã copy tọa độ: " + text + "\n(Bây giờ bạn có thể dán vào Google Maps)");
            }).catch(err => {
                console.error("Lỗi copy clipboard: ", err);
            });
        }
    }
}

registry.category("fields").add("google_map_picker", {
    component: GoogleMapPicker,
    supportedTypes: ["char", "text"],
});
