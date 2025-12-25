/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: INLINE STOCK & UI
// =============================================================================

async function renderInlineStock(lineEl, orm) {
    // 1. Tìm Product Code
    const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
    if (!codeEl) return;
    
    // Check xem đã vẽ chưa
    if (lineEl.querySelector(".hlv-inline-stock")) return;

    const defaultCode = codeEl.textContent.trim();
    if (!defaultCode) return;

    try {
        // Lấy tồn kho
        const domain = [['product_id.default_code', '=', defaultCode], ['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        // Format text
        let textDisplay = "Hết hàng";
        if (quants && quants.length > 0) {
            const stockMap = {};
            quants.forEach(q => {
                const locName = q.location_id ? q.location_id[1] : ""; 
                const match = locName.match(/\b(TSN|KBC|KHD)\b/i);
                const key = match ? match[1].toUpperCase() : "KHÁC"; 
                if (!stockMap[key]) stockMap[key] = 0;
                stockMap[key] += q.quantity;
            });
            textDisplay = Object.keys(stockMap).map(k => `${k}: ${stockMap[k]}`).join(" | ");
        }

        // Vẽ UI
        const qtyDiv = lineEl.querySelector('.o_barcode_scanner_qty');
        if (qtyDiv) {
            let badge = document.createElement("div"); 
            badge.className = "hlv-inline-stock";
            badge.style.cssText = "font-size: 11px; color: #004085; background-color: #cce5ff; padding: 2px 5px; border-radius: 4px; margin-top: 5px; font-weight: bold; width: fit-content; display: block; border: 1px solid #b8daff;";
            badge.textContent = `📦 ${textDisplay}`;
            
            if (qtyDiv.parentElement) qtyDiv.parentElement.appendChild(badge);
        }
        
        // Check đỏ
        const parts = (qtyDiv.innerText || "").split("/");
        if (parts.length >= 2) {
             const done = parseFloat(parts[0]);
             const demand = parseFloat(parts[1]);
             if (demand > 0 && done >= demand) {
                 qtyDiv.style.color = "#d9534f";
                 qtyDiv.style.fontWeight = "bold";
             }
        }
    } catch(e) { 
        console.error("Inline Error:", e);
    }
}

// =============================================================================
// MAIN LOGIC
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] Barcode Model Patched Successfully");
        
        // Observer để vẽ Inline Stock
        const observer = new MutationObserver(() => {
            document.querySelectorAll(".o_barcode_line").forEach(line => renderInlineStock(line, this.orm));
        });
        const wait = setInterval(() => {
            if (document.body) {
                observer.observe(document.body, { childList: true, subtree: true });
                clearInterval(wait);
            }
        }, 500);
    },

    async processBarcode(barcode) {
        console.log("⚡ [HLV] Processing Barcode:", barcode);

        // 0. Bỏ qua lệnh hệ thống
        if (!barcode || barcode.startsWith("O-CMD")) {
            return super.processBarcode(...arguments);
        }

        // 1. Chuẩn bị dữ liệu check
        let sourceLocId = this.location ? this.location.id : (this.record.location_id ? (Array.isArray(this.record.location_id) ? this.record.location_id[0] : this.record.location_id) : null);
        let locName = (this.location?.display_name || this.record?.display_name || "");
        let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

        console.log("🔍 [HLV] Checking Availability parameters:", { barcode, whPrefix, sourceLocId });

        // =================================================================
        // BƯỚC CHECK: CHẶN TUYỆT ĐỐI
        // =================================================================
        try {
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId]);
            
            console.log("📩 [HLV] Server Response:", result);

            // NẾU KHÔNG CHO PHÉP (ALLOW = FALSE)
            if (result && result.allow === false) {
                console.error("⛔ [HLV] BLOCKED BY SERVER");
                
                // Dùng ALERT của trình duyệt để chắc chắn bạn thấy (không bị Odoo che)
                alert(result.message || "⛔ Dừng lại! Không có hàng ở vị trí này.");
                
                if (this.env.services.sound) this.env.services.sound.play('error');
                
                // RETURN NGAY LẬP TỨC - KHÔNG BAO GIỜ CHẠY SUPER
                return; 
            }
            
            // Nếu có warning
            if (result && result.message) {
                 if (this.env.services.notification) {
                    this.env.services.notification.add(result.message, { type: 'warning' });
                 }
            }

        } catch (e) {
            console.error("❌ [HLV] CRITICAL ERROR during Check:", e);
            // Quan trọng: Nếu code check bị lỗi (ví dụ lỗi mạng, lỗi code python), 
            // BẠN MUỐN CHẶN HAY CHO QUA?
            // Hiện tại tôi để ALERT lỗi lên để bạn biết là code check đang fail.
            alert("Lỗi hệ thống khi kiểm tra tồn kho: " + e.message);
            return; // Chặn luôn nếu lỗi code để debug
        }

        // =================================================================
        // NẾU CODE CHẠY ĐẾN ĐÂY NGHĨA LÀ ĐÃ QUA ĐƯỢC CỔNG BẢO VỆ
        // =================================================================
        console.log("✅ [HLV] Check Passed. Executing Odoo Logic...");
        await super.processBarcode(...arguments);

        // =================================================================
        // AUTO SAVE (WRITE)
        // =================================================================
        try {
            const product = await this._identifyProductSafe(barcode);
            if (product && this.currentState.lines) {
                const line = this.currentState.lines.find(l => l.product_id.id === product.id);
                if (line) {
                    if (line.id && typeof line.id === 'number') {
                        console.log("💾 [HLV] Writing to DB Line ID:", line.id);
                        await this.orm.write("stock.move.line", [line.id], { "qty_done": line.qty_done });
                    } else {
                        console.log("💾 [HLV] New Line -> Calling Full Save");
                        await this.save();
                    }
                }
            }
        } catch (err) {
            console.error("❌ [HLV] Save Error:", err);
        }
    },

    async _identifyProductSafe(barcode) {
        let product = null;
        if (this.cache.products) product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        if (!product && this.currentState.lines) {
             const line = this.currentState.lines.find(l => l.product_id && (l.product_id.barcode === barcode || l.product_id.default_code === barcode));
             if (line) product = line.product_id;
        }
        return product;
    }
});