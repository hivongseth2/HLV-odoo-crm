/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

function insertInlineForBarcode(barcode, text, tries = 0) {
    const line = document.querySelector(`.o_barcode_line[data-barcode="${barcode}"] .o_barcode_scanner_qty`);
    if (line) {
        let badge = line.parentElement.querySelector(".hlv-inline-stock");
        if (!badge) {
            badge = document.createElement("small");
            badge.className = "hlv-inline-stock";
            line.parentElement.appendChild(badge);
        }
        badge.textContent = `| tồn: ${text}`;
        return true;
    }
    if (tries < 5) setTimeout(() => insertInlineForBarcode(barcode, text, tries + 1), 120);
    return false;
}

registry.category("barcode_handlers").add("hlv_show_stock_qty_inline", {
    sequence: 9999,
    async handler(env, barcode) {
        try {
            const orm = env.services.orm || useService("orm");
            const notification = env.services.notification || useService("notification");
            const result = await orm.call("stock.quant", "get_qty_by_barcode", [barcode], {});
            if (result && !result.error) {
                const label = `${result.qty} ${result.uom}`;
                insertInlineForBarcode(barcode, label);
                notification.add(`${result.product}: ${label}`, { title: "Tồn kho", type: "info" });
            } else {
                notification.add(result?.error || "Không tìm thấy sản phẩm", { title: "Thông báo", type: "warning" });
            }
        } catch (e) {
            const notification = env.services.notification || useService("notification");
            console.error("HLV inline stock error:", e);
            notification.add("Không thể lấy tồn kho sản phẩm.", { title: "Lỗi hệ thống", type: "danger" });
        }
        return false;
    },
});
