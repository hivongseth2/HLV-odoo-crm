/** @odoo-module **/

import  BarcodeModel  from "@stock_barcode/models/barcode_model"; 
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// =============================================================================
// PHẦN 1: HIỂN THỊ TỒN KHO (UI) - GIỮ NGUYÊN
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
// PHẦN 2: PATCH BARCODE MODEL - FIX LỖI CRASH & LOCID
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("✅ [HLV] Barcode v1.8 - Fix Crash Ready!");
        setTimeout(() => setupObserver(this.orm), 1000);
    },

    async processBarcode(barcode) {
        console.log("🚀 [HLV] ĐANG QUÉT:", barcode);

        if (!barcode || barcode.startsWith("O-CMD")) {
            return super.processBarcode(...arguments);
        }

        // 1. NHẬN DIỆN SẢN PHẨM (ĐÃ FIX LỖI CRASH)
        const product = await this._identifyProductSafe(barcode);
        
        // Nếu không phải sản phẩm (có thể là mã Vị trí/Tủ), bỏ qua để Odoo tự xử lý
        if (!product) {
            console.log("ℹ️ [HLV] Không phải sản phẩm -> Bỏ qua check stock.");
            return super.processBarcode(...arguments);
        }

        // 2. CHECK CLIENT: ĐỦ SỐ LƯỢNG CHƯA?
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

        // 3. LẤY SOURCE LOCATION ID (TỦ 3)
        let sourceLocId = null;
        let whPrefix = null;

        // A. Lấy từ trạng thái hiện tại (nếu vừa quét vị trí xong)
        if (this.currentState && this.currentState.location_id) {
             sourceLocId = typeof(this.currentState.location_id) === 'object' ? this.currentState.location_id[0] : this.currentState.location_id;
        }

        // B. Lấy từ Picking Record gốc (Fallback)
        if (!sourceLocId && this.record && this.record.location_id) {
             sourceLocId = typeof(this.record.location_id) === 'object' ? this.record.location_id[0] : this.record.location_id;
        }
        
        // C. Lấy từ dòng đầu tiên (Fallback cuối cùng)
        if (!sourceLocId && lines.length > 0 && lines[0].location_id) {
             sourceLocId = typeof(lines[0].location_id) === 'object' ? lines[0].location_id[0] : lines[0].location_id;
        }

        // D. Lấy Prefix (KBC/TSN)
        if (this.record && this.record.display_name) {
            const m = this.record.display_name.match(/\b(TSN|KBC|KHD)\b/i);
            if (m) whPrefix = m[1].toUpperCase();
        }

        console.log(`🔎 [HLV] Check Stock Server: Barcode=${barcode}, Prefix=${whPrefix}, LocID=${sourceLocId}`);

        // 4. GỌI SERVER CHECK
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

        // 5. PASS
        return super.processBarcode(...arguments);
    },

    // --- HÀM MỚI: TÌM SẢN PHẨM AN TOÀN (FIX LỖI OBJECT.VALUES UNDEFINED) ---
    async _identifyProductSafe(barcode) {
        let product = null;

        // Cách 1: Tìm trong Cache Products (có kiểm tra tồn tại)
        if (this.cache && this.cache.products) {
            product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        }

        // Cách 2: Tìm trong dòng hiện tại (Lines) - Phòng trường hợp Cache chưa load
        if (!product && this.currentState && this.currentState.lines) {
             const line = this.currentState.lines.find(l => 
                l.product_id && (l.product_id.barcode === barcode || l.product_id.default_code === barcode)
             );
             if (line) product = line.product_id;
        }
        
        return product;
    }
});