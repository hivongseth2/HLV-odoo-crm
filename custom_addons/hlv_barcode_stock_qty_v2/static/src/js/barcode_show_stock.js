/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// Đăng ký một barcode handler chung (được gọi trong cả menu & màn hình phiếu)
registry.category("barcode_handlers").add("hlv_show_stock_qty", {
    sequence: 9999,
    async handler(env, barcode) {
        try {
            const orm = env.services.orm || useService("orm");
            const notification = env.services.notification || useService("notification");
            const result = await orm.call("stock.quant", "get_qty_by_barcode", [barcode], {});
            if (result && !result.error) {
                (notification).add(`${result.product}: còn ${result.qty} ${result.uom}`, {
                    title: "Tồn kho",
                    type: "info",
                });
            } else {
                (notification).add(result?.error || "Không tìm thấy sản phẩm", {
                    title: "Thông báo",
                    type: "warning",
                });
            }
        } catch (e) {
            const notification = env.services.notification || useService("notification");
            console.error("HLV show stock qty error:", e);
            (notification).add("Không thể lấy tồn kho sản phẩm.", {
                title: "Lỗi hệ thống",
                type: "danger",
            });
        }
        // Không chặn các handler khác
        return false;
    },
});
