/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// Chèn "| tồn: X Cái" ngay sau phần qty của dòng chứa data-barcode
function insertInlineForBarcode(barcode, text, tries = 0) {
    const qtyEl = document.querySelector(`.o_barcode_line[data-barcode="${barcode}"] .o_barcode_scanner_qty`);
    if (qtyEl) {
        let badge = qtyEl.parentElement.querySelector(".hlv-inline-stock");
        if (!badge) {
            badge = document.createElement("small");
            badge.className = "hlv-inline-stock";
            badge.style.marginLeft = "8px";
            badge.style.fontSize = "12px";
            badge.style.color = "#0a7";
            qtyEl.parentElement.appendChild(badge);
        }
        badge.textContent = `| tồn: ${text}`;
        return true;
    }
    if (tries < 5) setTimeout(() => insertInlineForBarcode(barcode, text, tries + 1), 120);
    return false;
}

// Handler chạy được ở cả menu barcode và màn hình phiếu
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
            (env.services.notification || useService("notification"))
                .add("Không thể lấy tồn kho sản phẩm.", { title: "Lỗi hệ thống", type: "danger" });
        }
        return false; // không chặn các handler khác của Odoo
    },
});
