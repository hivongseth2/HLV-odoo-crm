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
        this.orm = useService("orm");
        
        onMounted(async () => {
            // First try to get the API key from Barcode Shipper company settings
            const companyData = await this.orm.searchRead("res.company", [], ["hlv_barcode_google_maps_api_key"], { limit: 1 });
            let apiKey = companyData && companyData.length ? companyData[0].hlv_barcode_google_maps_api_key : null;
            
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
                });
                
                this.marker = new maps.Marker({
                    position: { lat, lng },
                    map: this.map,
                    draggable: true,
                });
                
                this.marker.addListener("dragend", () => {
                    const pos = this.marker.getPosition();
                    this.props.record.update({
                        latitude: pos.lat(),
                        longitude: pos.lng()
                    });
                });
                
                this.map.addListener("click", (e) => {
                    const pos = e.latLng;
                    this.marker.setPosition(pos);
                    this.props.record.update({
                        latitude: pos.lat(),
                        longitude: pos.lng()
                    });
                });
            }, 100);
        });
    }
}

registry.category("fields").add("google_map_picker", {
    component: GoogleMapPicker,
    supportedTypes: ["char", "text"],
});
