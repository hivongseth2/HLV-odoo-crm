/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BarcodePickingModel } from "@stock_barcode/models/picking_model";
import { rpc } from "@web/core/network/rpc_service";
import { useService } from "@web/core/utils/hooks";

patch(BarcodePickingModel.prototype, "hlv_barcode_stock_qty", {
    async _onBarcodeScanned(barcode) {
        // Gọi hàm gốc để vẫn xử lý logic quét như bình thường
        await super._onBarcodeScanned(...arguments);

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
                    { type: "info", title: "Tồn kho hiện tại" }
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
});

registry.category("barcode_handlers").add("hlv_show_stock_qty", BarcodeMainMenuPatch);
