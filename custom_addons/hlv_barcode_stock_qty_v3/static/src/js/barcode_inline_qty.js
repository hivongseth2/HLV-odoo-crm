/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model"; 
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

console.log("🔥🔥🔥 HLV: FILE JS ĐÃ ĐƯỢC LOAD THÀNH CÔNG !!! 🔥🔥🔥");

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
    
    // Hook vào lúc khởi tạo để chắc chắn patch đã ăn
    setup() {
        super.setup(...arguments);
        console.log("✅ [HLV] BarcodeModel đã được khởi tạo!");
    },

    async processBarcode(barcode) {
        console.log("🚀 [HLV] >>> ĐANG QUÉT MÃ:", barcode);

        // 1. Logic gốc: Bỏ qua lệnh hệ thống
        if (!barcode || barcode.startsWith("O-CMD")) {
            return super.processBarcode(...arguments);
        }

        // 2. CHECK CLIENT: ĐỦ SỐ LƯỢNG CHƯA?
        try {
            const product = await this._identifyProduct(barcode);
            if (product) {
                // Odoo 18: Lấy lines từ state
                const lines = this.currentState.lines || [];
                const line = lines.find(l => l.product_id.id === product.id);

                if (line) {
                    // qty_done: đã làm, product_uom_qty: nhu cầu
                    // Lưu ý: convert sang float để so sánh
                    const done = parseFloat(line.qty_done || 0);
                    const demand = parseFloat(line.product_uom_qty || 0);

                    console.log(`[HLV] Check: Done=${done} / Demand=${demand}`);

                    if (demand > 0 && done >= demand) {
                        const msg = `⚠️ Dư hàng! Đã quét đủ ${done}/${demand} ${line.product_uom_id.name || ''}`;
                        this.notification.add(msg, { type: "danger", sticky: false });
                        this._beep("error");
                        console.warn("[HLV] BLOCK: Đã đủ số lượng");
                        return; // ⛔ STOP NGAY
                    }
                }
            }
        } catch (err) {
            console.error("[HLV] Lỗi check client:", err);
        }

        // 3. CHECK SERVER: TỒN KHO CÒN KHÔNG?
        try {
            // Lấy tên phiếu để tìm prefix kho (VD: "WH/PICK/001")
            const recordName = this.record ? this.record.display_name : "";
            let whPrefix = null;
            if (recordName) {
                const m = recordName.match(/\b(TSN|KBC|KHD)\b/i);
                if (m) whPrefix = m[1].toUpperCase();
            }

            console.log("[HLV] Check Server với prefix:", whPrefix);

            // Gọi RPC
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix]);
            
            if (result && result.allow === false) {
                this.notification.add(result.message, { type: "danger", sticky: true, title: "HẾT HÀNG" });
                this._beep("error");
                console.warn("[HLV] BLOCK: Server báo hết hàng");
                
                // ⚠️ QUAN TRỌNG: Return luôn để không chạy logic gốc
                return; 
            }

        } catch (e) {
            console.error("[HLV] Lỗi check server:", e);
        }

        // 4. Nếu không bị chặn, gọi logic gốc
        console.log("✅ [HLV] OK -> Pass cho Odoo xử lý");
        return super.processBarcode(...arguments);
    },

    async _identifyProduct(barcode) {
        // Fallback hàm tìm product nếu cần
        let product = Object.values(this.cache.products).find(p => p.barcode === barcode);
        if (!product) {
            product = Object.values(this.cache.products).find(p => p.default_code === barcode);
        }
        return product;
    }
});