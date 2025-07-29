/** @odoo-module **/

import { PickingBarcodeHandler } from "@stock_barcode/js/picking_barcode_handler";
import { registry } from "@web/core/registry";

export class CustomPickingBarcodeHandler extends PickingBarcodeHandler {
    setup() {
        super.setup();
        this.currentLocationId = null;
    }

    async _handleLocationBarcode(barcode) {
        const res = await super._handleLocationBarcode(barcode);
        const line = this.props.record.data.move_line_ids.find(l => l.location_id?.[1] === barcode);
        if (line) {
            this.currentLocationId = line.location_id[0];
        }
        return res;
    }

    async _handleProductBarcode(barcode) {
        const productLine = this.props.record.data.move_line_ids.find(l => l.product_barcode === barcode);

        if (!productLine) {
            return super._handleProductBarcode(barcode);
        }

        if (this.currentLocationId && productLine.location_id[0] !== this.currentLocationId) {
            this.notification.add("⚠️ Sản phẩm này không nằm ở kệ đang quét!", { type: "danger" });
            return true;
        }

        return super._handleProductBarcode(barcode);
    }
}

registry.category("barcode_handlers").add("stock_picking_custom", CustomPickingBarcodeHandler);
