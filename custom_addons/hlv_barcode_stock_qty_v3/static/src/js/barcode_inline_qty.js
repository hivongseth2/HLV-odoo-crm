/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: UI & LOGIC HIỂN THỊ
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
        badge.style.fontWeight = "bold";
        badge.style.color = "#17a2b8"; 
        badge.style.backgroundColor = "#f8f9fa";
        badge.style.padding = "2px 6px";
        badge.style.borderRadius = "4px";
        badge.style.border = "1px solid #dee2e6";
        qtyEl.parentElement.appendChild(badge);
    }
    badge.textContent = `📦 ${text}`;
}

// Hàm format số lượng: TSN: 5, KBC: 3
function formatStockResult(quants) {
    if (!quants || quants.length === 0) return "Hết hàng";
    
    const stockMap = {};

    quants.forEach(q => {
        // Lấy tên kho, ví dụ "WH/Stock/TSN/Kệ 1" -> Lấy "TSN"
        const locName = q.location_id ? q.location_id[1] : ""; 
        const match = locName.match(/\b(TSN|KBC|KHD)\b/i); // Thêm các mã kho của bạn vào đây
        const key = match ? match[1].toUpperCase() : "KHÁC"; 
        
        if (!stockMap[key]) stockMap[key] = 0;
        stockMap[key] += q.quantity;
    });

    // Tạo chuỗi hiển thị: "TSN: 3 | KBC: 4"
    return Object.keys(stockMap).map(k => `${k}: ${stockMap[k]}`).join(" | ");
}

async function annotateLine(lineEl, orm) {
    if (lineEl.__hlv_done__) return;
    lineEl.__hlv_done__ = true;
    
    // 1. Lấy mã sản phẩm
    let defaultCode = lineEl.querySelector(".o_product_ref")?.textContent?.trim() || "";
    if (!defaultCode || defaultCode.includes("\n")) {
         const m = (lineEl.innerText || "").match(/^[A-Z0-9._-]+/);
         if (m) defaultCode = m[0];
    }
    if (!defaultCode) return;

    try {
        // 2. Lấy tồn kho thực tế bằng search_read (Không cần hàm Python riêng)
        const domain = [
            ['product_id.default_code', '=', defaultCode],
            ['location_id.usage', '=', 'internal'] 
        ];
        // Lấy location và quantity
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        // 3. Hiển thị
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
            qtyEl.style.color = "#d9534f"; // Đỏ
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
        
        // --- 1. CHECK SỐ LƯỢNG (LIMIT) ---
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

        // --- 2. CHECK TỒN KHO TẠI VỊ TRÍ (Logic cũ bạn muốn giữ) ---
        // Giữ nguyên logic này nếu Python backend của bạn đã có hàm check_barcode_availability
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
            // Gọi hàm Python cũ của bạn
            const result = await this.orm.call(
                "stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId] 
            );
            if (result && result.allow === false) {
                this.env.services.notification.add(result.message, { type: 'danger' });
                this._playErrorSound();
                return; 
            }
        } catch (e) { 
            // Nếu lỗi RPC (do server chưa update code python), ta log ra thôi chứ ko chặn app
            console.warn("[HLV] Check Availability Skipped:", e); 
        }

        // --- 3. GỌI LOGIC GỐC (Update UI) ---
        await super.processBarcode(...arguments);

        // --- 4. AUTO SAVE IM LẶNG (SILENT SAVE) ---
        // Đây là phần quan trọng để F5 không mất dữ liệu
        try {
            console.log("💾 [HLV] Silent Saving...");
            
            // Mẹo: Tạm thời thay thế hàm notification bằng hàm rỗng
            const originalNotify = this.env.services.notification.add;
            this.env.services.notification.add = () => {}; 

            await this.save(); // Lưu xuống DB

            // Trả lại hàm notification cũ
            this.env.services.notification.add = originalNotify;
            
        } catch (err) {
            console.warn("[HLV] Save failed:", err);
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