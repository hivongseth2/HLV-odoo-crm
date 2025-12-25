/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model"; 
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: UI & AN TOÀN (SAFE MODE)
// =============================================================================

// Hàm phát âm thanh an toàn (không cần env)
function playErrorSound(env) {
    try {
        if (env && env.services && env.services.sound) {
            env.services.sound.play('error');
            return;
        }
        // Fallback: Dùng HTML5 Audio nếu không có env
        const audio = new Audio('/custom_barcode_scan_redirect/static/src/sound/error.mp3');
        audio.play().catch(() => {});
    } catch (e) {}
}

// Hàm thông báo an toàn (Kiểm tra kỹ env trước khi gọi)
function showNotification(env, message, type = 'danger') {
    try {
        if (env && env.services && env.services.notification) {
            env.services.notification.add(message, { 
                type: type, 
                sticky: type === 'danger', 
                title: type === 'danger' ? "CẢNH BÁO" : "Thông báo" 
            });
        } else {
            // Nếu không có env (lỗi undefined), dùng console log hoặc alert nhẹ
            console.warn("[HLV Notification]", message);
        }
    } catch (e) { console.error(e); }
}

function insertInline(lineEl, text) {
    const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
    if (!qtyEl) return;
    
    let badge = qtyEl.parentElement.querySelector(".hlv-inline-stock");
    if (!badge) {
        badge = document.createElement("span");
        badge.className = "hlv-inline-stock";
        badge.style.marginLeft = "10px";
        badge.style.fontSize = "13px";
        badge.style.color = "#17a2b8"; 
        badge.style.fontWeight = "bold";
        qtyEl.parentElement.appendChild(badge);
    }
    badge.textContent = `📦 ${text}`;
}

function formatStockResult(quants) {
    if (!quants || quants.length === 0) return "Hết hàng";
    const stockMap = {};
    quants.forEach(q => {
        const locName = q.location_id ? q.location_id[1] : ""; 
        const match = locName.match(/\b(TSN|KBC|KHD)\b/i);
        const key = match ? match[1].toUpperCase() : "KHÁC"; 
        if (!stockMap[key]) stockMap[key] = 0;
        stockMap[key] += q.quantity;
    });
    return Object.keys(stockMap).map(k => `${k}: ${stockMap[k]}`).join(" | ");
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

    try {
        const domain = [['product_id.default_code', '=', defaultCode],['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        const textDisplay = formatStockResult(quants);
        insertInline(lineEl, textDisplay);
        checkAndHighlightOverflow(lineEl);
    } catch(e) { console.error(e); }
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
                icon.textContent = " ✅";
                qtyEl.parentElement.appendChild(icon);
            }
        }
    } catch (e) {}
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
// MAIN LOGIC
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        setTimeout(() => setupObserver(this.orm), 1000);
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        const product = await this._identifyProductSafe(barcode);
        
        // --- 1. CHECK SỐ LƯỢNG (Dùng hàm safe showNotification) ---
        if (product) {
            const lines = this.currentState.lines || [];
            const matchedLine = lines.find(l => l.product_id.id === product.id);
            if (matchedLine) {
                const done = parseFloat(matchedLine.qty_done || 0);
                const demand = parseFloat(matchedLine.product_uom_qty || 0);
                if (demand > 0 && done >= demand) {
                    showNotification(this.env, `⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n(${done}/${demand})`, 'danger');
                    playErrorSound(this.env);
                    return; 
                }
            }
        }

        // --- 2. CHECK VỊ TRÍ (Giữ logic cũ) ---
        let sourceLocId = null;
        let whPrefix = null;
        if (this.location) sourceLocId = this.location.id;
        if (!sourceLocId && this.record && this.record.location_id) sourceLocId = typeof(this.record.location_id) === 'object' ? this.record.location_id[0] : this.record.location_id;
        
        if (this.location && this.location.display_name) {
            const m = this.location.display_name.match(/\b(TSN|KBC|KHD)\b/i);
            if (m) whPrefix = m[1].toUpperCase();
        } else if (this.record && this.record.display_name) {
             const m = this.record.display_name.match(/\b(TSN|KBC|KHD)\b/i);
             if (m) whPrefix = m[1].toUpperCase();
        }

        try {
            const result = await this.orm.call(
                "stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId] 
            );
            if (result && result.allow === false) {
                // SỬA LỖI Ở ĐÂY: Dùng showNotification thay vì gọi trực tiếp this.env
                showNotification(this.env, result.message, 'danger');
                playErrorSound(this.env);
                return; 
            }
        } catch (e) { 
            console.warn("[HLV] Check Availability Skipped:", e); 
        }

        // --- 3. GỌI LOGIC GỐC ---
        await super.processBarcode(...arguments);

        // --- 4. AUTO SAVE (SAFE MODE) ---
        try {
            console.log("💾 Auto Saving...");
            // Mẹo: Tạm thời mute notification nếu env tồn tại
            let originalNotify = null;
            if (this.env && this.env.services && this.env.services.notification) {
                originalNotify = this.env.services.notification.add;
                this.env.services.notification.add = () => {}; 
            }

            await this.save(); 

            // Trả lại hàm notification cũ
            if (originalNotify && this.env && this.env.services && this.env.services.notification) {
                this.env.services.notification.add = originalNotify;
            }
        } catch (err) {
            console.warn("[HLV] Save warning:", err);
        }
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