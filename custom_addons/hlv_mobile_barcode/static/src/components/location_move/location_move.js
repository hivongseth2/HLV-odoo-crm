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
            qty: 1,
            loading: false,
            inPickingName: "",
        });

        onWillStart(async () => {
            try {
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

    async doMove() {
        if (!this.state.sourceLocationBarcode) {
            this.notification.add("Yêu cầu nhập vị trí lấy hàng", { type: "danger" });
            return;
        }
        
        this.state.loading = true;
        this.state.inPickingName = "";
        try {
            const res = await rpc("/hlv_mobile_barcode/move_location", {
                product_id: this.props.productId,
                source_barcode: this.state.sourceLocationBarcode,
                qty: this.state.qty
            });
            
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add("Tạo lệnh chuyển thành công", { type: "success" });
                if (res.in_picking_name) {
                    this.state.inPickingName = res.in_picking_name;
                } else {
                    this.props.onBack();
                }
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối máy chủ", { type: "danger" });
        }
        this.state.loading = false;
    }
}
