/** @odoo-module **/

import  BarcodeModel  from "@stock_barcode/models/barcode_model"; 
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// =============================================================================
// HELPER: UI & SOUND
// =============================================================================

function playErrorSound(env) {
    try {
        // Cách 1: Dùng Sound Service chuẩn của Odoo 18
        if (env && env.services && env.services.sound) {
            env.services.sound.play('error');
            return;
        }
        // Cách 2: Fallback HTML5 Audio
        const audio = new Audio('/web/static/src/sounds/error.mp3');
        audio.play().catch(() => {});
    } catch (e) {}
}

function showNotification(env, message, type = 'danger') {
    try {
        if (env && env.services && env.services.notification) {
            env.services.notification.add(message, { 
                type: type, 
                sticky: type === 'danger', 
                title: type === 'danger' ? "CẢNH BÁO" : "Thông báo" 
            });
        } else {
            // Fallback nếu không tìm thấy service
            alert(message);
        }
    } catch (e) {
        console.error(e);
        alert(message);
    }
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
// MAIN LOGIC: PATCH BARCODE MODEL (FIX ERROR NOTIFICATION)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("✅ [HLV] Barcode v2.0 - Fix Notification Ready!");
        setTimeout(() => setupObserver(this.orm), 1000);
    },

    async processBarcode(barcode) {
        console.log("🚀 [HLV] ĐANG QUÉT:", barcode);

        if (!barcode || barcode.startsWith("O-CMD")) {
            return super.processBarcode(...arguments);
        }

        // 1. NHẬN DIỆN SẢN PHẨM (SAFE)
        const product = await this._identifyProductSafe(barcode);
        
        if (!product) {
            console.log("ℹ️ [HLV] Không phải sản phẩm -> Cho qua.");
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
                // SỬA LỖI: Dùng showNotification helper thay vì this.notification.add
                showNotification(this.env, msg, 'danger');
                playErrorSound(this.env);
                return;
            }
        }

        // 3. LẤY LOCATION ID CHÍNH XÁC (TỦ 3)
        let sourceLocId = null;
        let whPrefix = null;

        // Ưu tiên: Lấy từ this.location (Header - Vị trí đang scan)
        if (this.location) {
            sourceLocId = this.location.id;
            console.log("📍 [HLV] Lấy từ this.location (Header):", sourceLocId);
        } 
        
        // Fallback: Lấy từ Picking gốc
        if (!sourceLocId && this.record && this.record.location_id) {
             sourceLocId = typeof(this.record.location_id) === 'object' ? this.record.location_id[0] : this.record.location_id;
             console.log("📍 [HLV] Lấy từ Picking (Gốc):", sourceLocId);
        }

        // Lấy Prefix
        if (this.location && this.location.display_name) {
            const m = this.location.display_name.match(/\b(TSN|KBC|KHD)\b/i);
            if (m) whPrefix = m[1].toUpperCase();
        } else if (this.record && this.record.display_name) {
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
                // SỬA LỖI: Dùng showNotification helper
                showNotification(this.env, result.message, 'danger');
                playErrorSound(this.env);
                return; // ⛔ CHẶN
            }
        } catch (e) {
            console.error("[HLV] RPC Error:", e);
        }

        // 5. PASS
        return super.processBarcode(...arguments);
    },

    async _identifyProductSafe(barcode) {
        let product = null;
        if (this.cache && this.cache.products) {
            product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        }
        if (!product && this.currentState && this.currentState.lines) {
             const line = this.currentState.lines.find(l => 
                l.product_id && (l.product_id.barcode === barcode || l.product_id.default_code === barcode)
             );
             if (line) product = line.product_id;
        }
        return product;
    }
});