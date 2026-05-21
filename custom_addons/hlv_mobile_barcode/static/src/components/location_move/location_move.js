/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class LocationMove extends Component {
    static template = "hlv_mobile_barcode.LocationMove";
    static props = {
        productId: Number,
        onBack: Function,
    };

    setup() {
        this.notification = useService("notification");
        
        this.state = useState({
            sourceLocationBarcode: "",
            destLocationBarcode: "",
            qty: 1,
            loading: false,
        });
    }

    async doMove() {
        if (!this.state.sourceLocationBarcode || !this.state.destLocationBarcode) {
            this.notification.add("Source and Destination locations are required", { type: "danger" });
            return;
        }
        
        this.state.loading = true;
        try {
            const res = await rpc("/hlv_mobile_barcode/move_location", {
                product_id: this.props.productId,
                source_barcode: this.state.sourceLocationBarcode,
                dest_barcode: this.state.destLocationBarcode,
                qty: this.state.qty
            });
            
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add("Moved successfully", { type: "success" });
                this.props.onBack();
            }
        } catch (e) {
            this.notification.add("Server error", { type: "danger" });
        }
        this.state.loading = false;
    }
}
