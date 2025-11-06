/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc_service";

const BarcodeMainMenuPatch = {
    dependencies: ["notification"],

    setup() {
        this.notification = useService("notification");
    },

    async onBarcodeScanned(barcode) {
        if (super.onBarcodeScanned) {
            super.onBarcodeScanned(barcode);
        }
        try {
            const result = await rpc("/web/dataset/call_kw", {
                model: "stock.quant",
                method: "get_qty_by_barcode",
                args: [barcode],
                kwargs: {},
            });
            if (result && !result.error) {
                this.notification.add(
                    `${result.product}: còn ${result.qty} ${result.uom}`,
                    { type: "info", title: "Tồn kho" }
                );
            } else {
                this.notification.add(result.error || "Không tìm thấy sản phẩm", {
                    type: "warning",
                    title: "Thông báo",
                });
            }
        } catch (e) {
            console.error("Lỗi khi lấy tồn kho:", e);
            this.notification.add("Không thể lấy tồn kho sản phẩm.", {
                type: "danger",
                title: "Lỗi hệ thống",
            });
        }
    },
};

registry.category("barcode_handlers").add("hlv_show_stock_qty", BarcodeMainMenuPatch);
