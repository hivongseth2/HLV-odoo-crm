/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// =============================================================================
// PHẦN 1: HELPER HIỂN THỊ TỒN KHO INLINE (TSN: 3 | KBC: 4)
// =============================================================================

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

// Hàm mới: Cộng gộp số lượng theo từ khóa kho (TSN, KBC...)
function formatStockResult(quants) {
    if (!quants || quants.length === 0) return "Hết hàng";
    
    const stockMap = {};

    quants.forEach(q => {
        // q.location_id = [id, "WH/Stock/TSN/Kệ 1"]
        const locName = q.location_id ? q.location_id[1] : ""; 
        // Tìm từ khóa kho trong tên vị trí
        const match = locName.match(/\b(TSN|KBC|KHD)\b/i);
        const key = match ? match[1].toUpperCase() : "KHÁC"; 
        
        if (!stockMap[key]) stockMap[key] = 0;
        stockMap[key] += q.quantity;
    });

    // Tạo chuỗi: "TSN: 3 | KBC: 4"
    return Object.keys(stockMap).map(k => `${k}: ${stockMap[k]}`).join(" | ");
}

async function annotateLine(lineEl, orm) {
    if (lineEl.__hlv_done__) return;
    lineEl.__hlv_done__ = true;
    
    // Lấy Product Code từ giao diện
    let defaultCode = lineEl.querySelector(".o_product_ref")?.textContent?.trim() || "";
    if (!defaultCode || defaultCode.includes("\n")) {
         const m = (lineEl.innerText || "").match(/^[A-Z0-9._-]+/);
         if (m) defaultCode = m[0];
    }
    if (!defaultCode) return;

    try {
        // Dùng hàm search_read chuẩn của Odoo (Không cần sửa Python)
        // Lấy tất cả hàng ở các vị trí nội bộ
        const domain = [
            ['product_id.default_code', '=', defaultCode],
            ['location_id.usage', '=', 'internal'] 
        ];
        
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        // Format và hiển thị
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
            qtyEl.style.color = "#d9534f"; // Đỏ cảnh báo
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
// PHẦN 2: LOGIC BARCODE (CHECK & SAVE)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        setTimeout(() => setupObserver(this.orm), 1000);
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        const product = await this._identifyProductSafe(barcode);
        
        // --- 1. LOGIC CHECK LIMIT (Giữ nguyên của bạn) ---
        if (product) {
            const lines = this.currentState.lines || [];
            const matchedLine = lines.find(l => l.product_id.id === product.id);
            if (matchedLine) {
                const done = parseFloat(matchedLine.qty_done || 0);
                const demand = parseFloat(matchedLine.product_uom_qty || 0);
                if (demand > 0 && done >= demand) {
                    this.env.services.notification.add(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n(${done}/${demand})`, { type: 'danger' });
                    this._playErrorSound();
                    return;
                }
            }
        }

        // --- 2. LOGIC CHECK TỒN KHO (Giữ nguyên của bạn) ---
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
            // Vẫn gọi hàm python check cũ vì bạn bảo nó đang đúng
            const result = await this.orm.call(
                "stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId] 
            );
            if (result && result.allow === false) {
                this.env.services.notification.add(result.message, { type: 'danger' });
                this._playErrorSound();
                return; 
            }
        } catch (e) { console.error("[HLV] Check Error:", e); }

        // --- 3. CẬP NHẬT GIAO DIỆN ---
        await super.processBarcode(...arguments);

        // --- 4. TỰ ĐỘNG LƯU (Quan trọng để fix F5) ---
        try {
            console.log("💾 Auto Saving...");
            await this.save(); 
            // Đã bỏ dòng showNotification("Đã lưu") theo yêu cầu
        } catch (err) {
            console.warn("Save Error:", err);
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
    },

    _playErrorSound() {
        try {
            if (this.env.services.sound) {
                this.env.services.sound.play('error');
            } else {
                const audio = new Audio('/custom_barcode_scan_redirect/static/src/sound/error.mp3');
                audio.play().catch(() => {});
            }
        } catch(e) {}
    }
});