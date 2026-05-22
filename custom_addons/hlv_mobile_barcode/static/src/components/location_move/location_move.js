/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class LocationMove extends Component {
    static template = "hlv_mobile_barcode.LocationMove";
    static props = {
        productId: Number,
        onBack: Function,
        openCameraForInput: { type: Function, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        
        this.state = useState({
            productName: "Loading...",
            sourceLocationBarcode: "",
            destLocationBarcode: "",
            qty: 1,
            loading: false,
        });

        onWillStart(async () => {
            try {
                // Fetch product info quickly so user knows what they are moving
                const res = await rpc("/hlv_mobile_barcode/smart_scan", { barcode: `product_${this.props.productId}` });
                // Note: smart_scan expects a barcode, but we only have ID. We can use a different endpoint or just let the backend handle id if we change it.
                // Actually, let's just make a simple RPC call to read product name:
                const product = await rpc("/web/dataset/call_kw/product.product/read", {
                    model: 'product.product',
                    method: 'read',
                    args: [[this.props.productId], ['display_name']],
                    kwargs: {}
                });
                if (product && product.length) {
                    this.state.productName = product[0].display_name;
                } else {
                    this.state.productName = "Unknown Product";
                }
            } catch(e) {
                this.state.productName = "Product #" + this.props.productId;
            }
        });
    }

    scanSource() {
        if (this.props.openCameraForInput) {
            this.props.openCameraForInput((text) => {
                this.state.sourceLocationBarcode = text;
            });
        }
    }

    scanDest() {
        if (this.props.openCameraForInput) {
            this.props.openCameraForInput((text) => {
                this.state.destLocationBarcode = text;
            });
        }
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
