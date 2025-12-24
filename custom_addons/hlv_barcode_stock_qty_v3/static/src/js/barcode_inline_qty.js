/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model"; 
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";



// -------------------------------------------------------------------------
// PHẦN 1: LOGIC HIỂN THỊ TRÊN DOM (Giữ nguyên logic visual cũ của bạn)
// -------------------------------------------------------------------------
// (Phần này để vẽ chữ "tồn: 10" lên giao diện, chạy độc lập với logic chặn)

const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_default_code_at_warehouse";

async function callKw(orm, model, method, args = [], kwargs = {}) {
    // Trong Odoo 18, ta dùng orm service được truyền vào model
    return await orm.call(model, method, args, kwargs);
}

function insertInline(lineEl, text) {
    const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
    if (!qtyEl) return;
    let badge = qtyEl.parentElement.querySelector(".hlv-inline-stock");
    if (!badge) {
        badge = document.createElement("small");
        badge.className = "hlv-inline-stock";
        badge.style.marginLeft = "8px";
        badge.style.fontSize = "12px";
        badge.style.color = "#0a7";
        qtyEl.parentElement.appendChild(badge);
    }
    badge.textContent = `| ${text}`;
}

function checkAndHighlightOverflow(lineEl) {
    try {
        const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
        if (!qtyEl) return;
        const qtyText = qtyEl.textContent || "";
        const match = qtyText.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);
        if (!match) return;
        const qtyDone = parseFloat(match[1]) || 0;
        const demand = parseFloat(match[2]) || 0;

        if (qtyDone >= demand && demand > 0) {
            qtyEl.style.color = "#d9534f";
            qtyEl.style.fontWeight = "bold";
            // Thêm icon warning
            if (!qtyEl.parentElement.querySelector(".hlv-warning-icon")) {
                const icon = document.createElement("span");
                icon.className = "hlv-warning-icon";
                icon.textContent = " ⚠️";
                icon.style.color = "#d9534f";
                qtyEl.parentElement.appendChild(icon);
            }
        }
    } catch (e) {}
}

// Hàm fetch tồn kho hiển thị (chạy ngầm)
async function annotateLine(lineEl, orm) {
    if (lineEl.__hlv_done__) return;
    lineEl.__hlv_done__ = true;
    
    // Lấy default code từ DOM
    let defaultCode = lineEl.querySelector(".o_product_ref")?.textContent?.trim() || "";
    // Fallback regex nếu dính chữ
    if (!defaultCode || defaultCode.includes("\n")) {
         const m = (lineEl.innerText || "").match(/^[A-Z0-9._-]+/);
         if (m) defaultCode = m[0];
    }
    
    if (!defaultCode) return;

    // Lấy prefix kho
    const breadcrumb = document.querySelector(".o_control_panel")?.innerText || "";
    const prefixMatch = breadcrumb.match(/\b(TSN|KBC|KHD)\b/i);
    const whPrefix = prefixMatch ? prefixMatch[1].toUpperCase() : null;

    try {
        const result = await orm.call("stock.quant", "get_qty_by_default_code_at_warehouse", [defaultCode, whPrefix]);
        const labelPrefix = whPrefix || (result.base_location?.split("/")?.[0]) || "tổng";
        insertInline(lineEl, `tồn (${labelPrefix}): ${result.qty} ${result.uom}`);
        checkAndHighlightOverflow(lineEl);
    } catch(e) {}
}

// Observer để vẽ UI
function setupObserver(orm) {
    if (window.__hlv_observer__) return;
    const obs = new MutationObserver((mutations) => {
        mutations.forEach((m) => {
            m.addedNodes.forEach((node) => {
                if (node instanceof HTMLElement) {
                    if (node.matches(".o_barcode_line")) annotateLine(node, orm);
                    node.querySelectorAll(".o_barcode_line").forEach(el => annotateLine(el, orm));
                }
            });
            // Check update qty
            if (m.type === 'characterData' || m.type === 'childList') {
                const target = m.target.parentElement;
                if (target && target.closest('.o_barcode_line')) {
                    checkAndHighlightOverflow(target.closest('.o_barcode_line'));
                }
            }
        });
    });
    const target = document.querySelector('.o_content'); 
    if (target) {
        obs.observe(document.body, { childList: true, subtree: true, characterData: true });
        window.__hlv_observer__ = obs;
        // Scan initial
        document.querySelectorAll(".o_barcode_line").forEach(el => annotateLine(el, orm));
    }
}


// -------------------------------------------------------------------------
// PHẦN 2: PATCH BARCODE MODEL (QUAN TRỌNG NHẤT)
// -------------------------------------------------------------------------
// Đây là nơi ta chặn việc quét mã nếu hết hàng hoặc đủ số lượng

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        // Kích hoạt observer UI khi model khởi tạo
        // Dùng setTimeout để đợi DOM render
        setTimeout(() => setupObserver(this.orm), 1000);
    },

    /**
     * Override hàm xử lý barcode chính của Odoo
     * @param {string} barcode 
     */
   async processBarcode(barcode) {
        console.log("[HLV] >>> BẮT ĐẦU QUÉT:", barcode);

        // 1. Bỏ qua các lệnh hệ thống
        if (!barcode || barcode.startsWith("O-CMD")) {
            return super.processBarcode(...arguments);
        }

        // 2. CHECK 1: KIỂM TRA SỐ LƯỢNG TRONG PHIẾU (CLIENT SIDE)
        const product = await this._identifyProduct(barcode);
        if (product) {
            // Lấy danh sách dòng trong phiếu hiện tại
            // Odoo 18: this.currentState.lines hoặc this.pages (tuỳ view)
            // Cách an toàn nhất: lấy từ cache lines
            const lines = this.currentState.lines || []; 
            
            // Tìm dòng khớp product
            const line = lines.find(l => l.product_id.id === product.id);
            
            if (line) {
                // Lưu ý: qty_done là số thực tế đã quét, product_uom_qty là demand
                console.log(`[HLV] Check Line: Done=${line.qty_done}, Demand=${line.product_uom_qty}`);
                
                if (line.product_uom_qty > 0 && line.qty_done >= line.product_uom_qty) {
                    this.notification.add(_t("⚠️ Sản phẩm này đã đủ số lượng!"), { type: "danger" });
                    this._beep("error");
                    console.warn("[HLV] BLOCK: Đã đủ số lượng");
                    return; // <--- CHẶN NGAY
                }
            }
        }

        // 3. CHECK 2: KIỂM TRA TỒN KHO THỰC TẾ (SERVER SIDE)
        try {
            // --- TÌM PREFIX KHO (TSN/KBC/KHD) ---
            let whPrefix = null;

            // Cách 1: Lấy từ tên phiếu (Record Name) trong dữ liệu model (Chính xác nhất)
            // Ví dụ record name: "KBC/INT/00185"
            if (this.record && this.record.display_name) {
                const m = this.record.display_name.match(/\b(TSN|KBC|KHD)\b/i);
                if (m) whPrefix = m[1].toUpperCase();
            }
            
            // Cách 2: Fallback quét DOM (Header/Breadcrumb) nếu cách 1 thất bại
            if (!whPrefix) {
                const headerText = document.body.innerText; 
                const m = headerText.match(/\b(TSN|KBC|KHD)\b/i);
                if (m) whPrefix = m[1].toUpperCase();
            }

            console.log("[HLV] Warehouse Prefix tìm được:", whPrefix);

            // GỌI RPC CHECK TỒN KHO
            // Lưu ý: Phải dùng 'await' để code dừng lại chờ server trả lời
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix]);
            
            console.log("[HLV] Kết quả Server:", result);

            if (result && result.allow === false) {
                // ==> SERVER BÁO HẾT HÀNG
                // Hiển thị dialog cảnh báo
                this.notification.add(result.message, { type: "danger", sticky: true, title: "CẢNH BÁO TỒN KHO" });
                
                // Play sound error
                this._beep("error");
                
                console.warn("[HLV] BLOCK: Server báo hết hàng");
                return; // <--- CHẶN NGAY, KHÔNG GỌI SUPER
            }

        } catch (e) {
            console.error("[HLV] Lỗi khi check tồn kho:", e);
            // Nếu lỗi mạng, có thể cho qua hoặc chặn tuỳ bạn. Hiện tại đang cho qua.
        }

        // 4. Nếu qua hết các ải -> Gọi logic gốc Odoo
        console.log("[HLV] OK -> Gọi logic gốc Odoo");
        return super.processBarcode(...arguments);
    },

    // Helper tìm product (giữ nguyên logic Odoo)
    async _identifyProduct(barcode) {
        let product = Object.values(this.cache.products).find(p => p.barcode === barcode);
        if (!product) {
            product = Object.values(this.cache.products).find(p => p.default_code === barcode);
        }
        return product;
    }
});