/** @odoo-module **/

import  BarcodeModel  from "@stock_barcode/models/barcode_model"; 
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// =============================================================================
// PHẦN 1: HIỂN THỊ TỒN KHO (GIỮ NGUYÊN)
// =============================================================================
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

        if (demand > 0 && qtyDone >= demand) {
            qtyEl.style.color = "#d9534f";
            qtyEl.style.fontWeight = "bold";
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

async function annotateLine(lineEl, orm) {
    if (lineEl.__hlv_done__) return;
    lineEl.__hlv_done__ = true;
    
    let defaultCode = lineEl.querySelector(".o_product_ref")?.textContent?.trim() || "";
    if (!defaultCode || defaultCode.includes("\n")) {
         const m = (lineEl.innerText || "").match(/^[A-Z0-9._-]+/);
         if (m) defaultCode = m[0];
    }
    if (!defaultCode) return;

    const breadcrumb = document.body.innerText;
    const m = breadcrumb.match(/\b(TSN|KBC|KHD)\b/i);
    const whPrefix = m ? m[1].toUpperCase() : null;

    try {
        const result = await orm.call("stock.quant", "get_qty_by_default_code_at_warehouse", [defaultCode, whPrefix]);
        const labelPrefix = whPrefix || (result.base_location?.split("/")?.[0]) || "tổng";
        insertInline(lineEl, `tồn (${labelPrefix}): ${result.qty} ${result.uom}`);
        checkAndHighlightOverflow(lineEl);
    } catch(e) {}
}

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
            if (m.type === 'characterData' || m.type === 'childList') {
                const target = m.target.parentElement;
                if (target && target.closest('.o_barcode_line')) {
                    checkAndHighlightOverflow(target.closest('.o_barcode_line'));
                }
            }
        });
    });
    if (document.body) {
        obs.observe(document.body, { childList: true, subtree: true, characterData: true });
        window.__hlv_observer__ = obs;
        document.querySelectorAll(".o_barcode_line").forEach(el => annotateLine(el, orm));
    }
}

// =============================================================================
// PHẦN 2: PATCH BARCODE MODEL - CHẶN QUÉT (ĐÃ FIX LOCID)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("✅ [HLV] Barcode Interceptor v1.7 Ready!");
        setTimeout(() => setupObserver(this.orm), 1000);
    },

    async processBarcode(barcode) {
        console.log("🚀 [HLV] ĐANG QUÉT:", barcode);

        // 1. Nếu là lệnh hệ thống, cho qua
        if (!barcode || barcode.startsWith("O-CMD")) {
            return super.processBarcode(...arguments);
        }

        // 2. QUAN TRỌNG: Kiểm tra xem barcode này có phải SẢN PHẨM không?
        // Nếu là barcode Vị Trí (KBC-TU3), ta phải CHO QUA để Odoo đổi vị trí nguồn.
        const product = await this._identifyProduct(barcode);
        
        if (!product) {
            console.log("ℹ️ [HLV] Không phải sản phẩm (có thể là Vị trí/Lệnh/Package). Bỏ qua check stock.");
            return super.processBarcode(...arguments);
        }

        // 3. CHECK CLIENT: ĐỦ SỐ LƯỢNG CHƯA?
        const lines = this.currentState.lines || [];
        const matchedLine = lines.find(l => l.product_id.id === product.id);

        if (matchedLine) {
            const done = parseFloat(matchedLine.qty_done || 0);
            const demand = parseFloat(matchedLine.product_uom_qty || 0);
            if (demand > 0 && done >= demand) {
                const msg = `⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n(${done}/${demand})`;
                this.notification.add(msg, { type: "danger", sticky: false });
                this._beep("error");
                return;
            }
        }

        // 4. LẤY SOURCE LOCATION ID (FIXED LOGIC)
        let sourceLocId = null;
        let whPrefix = null;

        // Ưu tiên A: Lấy từ trạng thái hiện tại (nếu vừa quét vị trí xong)
        if (this.currentState && this.currentState.location_id) {
             sourceLocId = typeof(this.currentState.location_id) === 'object' ? this.currentState.location_id[0] : this.currentState.location_id;
             console.log("📍 [HLV] Lấy LocID từ currentState:", sourceLocId);
        }

        // Ưu tiên B: Lấy từ Picking Record gốc
        if (!sourceLocId && this.record && this.record.location_id) {
             sourceLocId = typeof(this.record.location_id) === 'object' ? this.record.location_id[0] : this.record.location_id;
             console.log("📍 [HLV] Lấy LocID từ record.location_id:", sourceLocId);
        }

        // Ưu tiên C: Lấy từ dòng đầu tiên (Picking thường chung 1 nguồn)
        if (!sourceLocId && lines.length > 0 && lines[0].location_id) {
             sourceLocId = typeof(lines[0].location_id) === 'object' ? lines[0].location_id[0] : lines[0].location_id;
             console.log("📍 [HLV] Lấy LocID từ dòng đầu tiên:", sourceLocId);
        }

        // Tìm Prefix (KBC/TSN) để hiển thị lỗi cho đẹp (không dùng để check logic chính nữa)
        if (this.record && this.record.display_name) {
            const m = this.record.display_name.match(/\b(TSN|KBC|KHD)\b/i);
            if (m) whPrefix = m[1].toUpperCase();
        }

        console.log(`🔎 [HLV] Check Stock Server: Barcode=${barcode}, Prefix=${whPrefix}, LocID=${sourceLocId}`);

        // 5. GỌI SERVER
        try {
            const result = await this.orm.call(
                "stock.quant", 
                "check_barcode_availability", 
                [barcode, whPrefix, sourceLocId] 
            );
            
            if (result && result.allow === false) {
                this.notification.add(result.message, { type: "danger", sticky: true, title: "LỖI KHO" });
                this._beep("error");
                return; // ⛔ CHẶN
            }
        } catch (e) {
            console.error("[HLV] RPC Error:", e);
        }

        // 6. PASS
        return super.processBarcode(...arguments);
    },

    async _identifyProduct(barcode) {
        let product = Object.values(this.cache.products).find(p => p.barcode === barcode);
        if (!product) {
            product = Object.values(this.cache.products).find(p => p.default_code === barcode);
        }
        // Nếu không tìm thấy trong cache, thử tìm trong lines (phòng hờ)
        if (!product && this.currentState.lines) {
             const line = this.currentState.lines.find(l => l.product_id.default_code === barcode);
             if (line) product = line.product_id;
        }
        return product;
    }
});