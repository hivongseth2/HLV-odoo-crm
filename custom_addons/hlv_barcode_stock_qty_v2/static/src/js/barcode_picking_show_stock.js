/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BarcodePickingModel } from "@stock_barcode/models/picking_model";
import { rpc } from "@web/core/network/rpc_service";

/**
 * Patch vào màn hình phiếu (picking) của Barcode App.
 * - Sau khi quét xong 1 barcode, gọi backend lấy tồn kho và hiện notification.
 * - Đồng thời chèn số tồn inline vào dòng sản phẩm tương ứng (DOM).
 */
patch(BarcodePickingModel.prototype, "hlv_barcode_stock_qty_v2", {
    async onBarcodeScanned(barcode) {
        // Gọi logic gốc để Odoo cập nhật dòng/qty như bình thường
        if (this._super) {
            await this._super(...arguments);
        }

        try {
            // Lấy location đích hiện tại (nếu có) để lọc tồn theo khu vực/kho
            const currentLocationId = this.currentState?.locationDestId || this.currentState?.locationId || null;

            const result = await rpc("/web/dataset/call_kw", {
                model: "stock.quant",
                method: "get_qty_by_barcode",
                args: [barcode, currentLocationId],
                kwargs: {},
            });

            const notify = this.env.services?.notification;
            if (result && !result.error) {
                // Hiện thông báo
                notify && notify.add(`${result.product}: còn ${result.qty} ${result.uom}`, {
                    type: "info",
                    title: "Tồn kho hiện tại",
                });

                // Chèn inline vào dòng sản phẩm tương ứng (nếu tìm thấy)
                try {
                    const selector = `.o_barcode_line[data-barcode="${CSS.escape(barcode)}"] .o_barcode_line_title`;
                    const titleEl = document.querySelector(selector);
                    if (titleEl) {
                        let badge = titleEl.querySelector(".hlv-onhand");
                        if (!badge) {
                            badge = document.createElement("span");
                            badge.className = "hlv-onhand ms-2 badge bg-secondary-subtle text-dark small";
                            titleEl.appendChild(badge);
                        }
                        badge.textContent = `Tồn: ${result.qty} ${result.uom}`;
                    }
                } catch (domErr) {
                    // không chặn luồng nếu DOM không khớp
                    console.warn("HLV inline stock DOM update skipped:", domErr);
                }
            } else {
                notify && notify.add(result?.error || "Không tìm thấy sản phẩm", {
                    type: "warning",
                    title: "Thông báo",
                });
            }
        } catch (e) {
            console.error("HLV get stock error:", e);
            const notify = this.env.services?.notification;
            notify && notify.add("Không thể lấy tồn kho sản phẩm.", {
                type: "danger",
                title: "Lỗi hệ thống",
            });
        }
    },
});
