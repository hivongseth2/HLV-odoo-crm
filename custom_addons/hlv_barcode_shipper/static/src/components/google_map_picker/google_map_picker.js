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
            const configs = await this.orm.call("ir.config_parameter", "get_param", ["hlv_barcode_shipper.google_maps_api_key"]);
            if (!configs) {
                console.error("Missing Google Maps API Key in Settings");
                return;
            }
            const maps = await loadGoogleMaps(configs);
            
            // Get coordinates from the record
            let lat = this.props.record.data.latitude || 21.028511; // Default Hanoi
            let lng = this.props.record.data.longitude || 105.804817;
            
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
        });
    }
}

registry.category("fields").add("google_map_picker", {
    component: GoogleMapPicker,
});
