/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: UI & HIỂN THỊ
// =============================================================================

function safePlaySound(env, type = 'error') {
    try {
        if (env && env.services && env.services.sound) {
            env.services.sound.play(type);
        } else {
            new Audio('/web/static/src/audio/error.mp3').play().catch(() => {});
        }
    } catch (e) {}
}

async function renderInlineStock(lineEl, orm) {
    let defaultCode = lineEl.dataset.barcode;
    if (!defaultCode) {
        const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
        if (codeEl) defaultCode = codeEl.textContent.trim();
    }
    // Tránh vẽ lại nếu đã có
    if (!defaultCode || lineEl.querySelector(".hlv-inline-stock")) return;

    try {
        const domain = [['product_id.default_code', '=', defaultCode], ['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        let textDisplay = "0";
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

        const qtyContainer = lineEl.querySelector('div[name="quantity"]') || lineEl.querySelector('.o_barcode_scanner_qty')?.parentElement;
        if (qtyContainer) {
            let badge = document.createElement("div"); 
            badge.className = "hlv-inline-stock";
            badge.style.cssText = `font-size: 11px; color: #004085; background-color: #cce5ff; padding: 2px 6px; border-radius: 4px; margin-top: 4px; font-weight: bold; width: fit-content; display: block; border: 1px solid #b8daff;`;
            badge.textContent = `📦 ${textDisplay}`;
            qtyContainer.appendChild(badge);
        }
    } catch(e) { console.error("Inline Error:", e); }
}

// =============================================================================
// MAIN LOGIC
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] Barcode Logic: FIX SUM CHECK - NO SAVE");
        
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
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // --- 1. NHẬN DIỆN SẢN PHẨM ---
        const product = await this._identifyProductSafe(barcode);

        // =================================================================
        // ⛔ BƯỚC 1: CHECK SỐ LƯỢNG (TÍNH TỔNG CỘNG DỒN)
        // =================================================================
        if (product && this.currentState.lines) {
            // Lọc ra TẤT CẢ các dòng của sản phẩm này
            // FIX LỖI: So sánh ID an toàn (xử lý cả trường hợp object và số)
            const productLines = this.currentState.lines.filter(l => {
                const lineProductId = (l.product_id && typeof l.product_id === 'object') ? l.product_id.id : l.product_id;
                return lineProductId === product.id;
            });
            
            let totalDone = 0;
            let totalDemand = 0;

            productLines.forEach(l => {
                totalDone += parseFloat(l.qty_done || 0);
                totalDemand += parseFloat(l.product_uom_qty || 0); 
            });

            // DEBUG LOG: Xem nó tính ra bao nhiêu
            // console.log(`🔍 [HLV] Check SUM: ${product.display_name} | TotalDone: ${totalDone} | TotalDemand: ${totalDemand}`);

            // LOGIC CHẶN CỨNG:
            // Chỉ chặn khi Có Yêu Cầu (Demand > 0) VÀ Đã làm xong (Done >= Demand)
            if (totalDemand > 0 && totalDone >= totalDemand) {
                console.error("⛔ BLOCKED: FULL QUANTITY");
                
                safePlaySound(this.env, 'error');
                
                alert(`⚠️ DỪNG LẠI!\n\nSản phẩm: ${product.display_name}\nĐã đủ số lượng: ${totalDone}/${totalDemand}\n\nKhông được phép quét thêm!`);
                
                return; // Return ngay lập tức (Không quét)
            }
        }

        // =================================================================
        // 🌍 BƯỚC 2: CHECK SERVER (VỊ TRÍ)
        // =================================================================
        let sourceLocId = this.location ? this.location.id : (this.record.location_id ? (Array.isArray(this.record.location_id) ? this.record.location_id[0] : this.record.location_id) : null);
        let locName = (this.location?.display_name || this.record?.display_name || "");
        let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

        try {
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId]);
            
            if (result && result.allow === false) {
                safePlaySound(this.env, 'error');
                alert(`⛔ LỖI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                return; 
            }
        } catch (e) {
            alert("Lỗi kiểm tra tồn kho (Server Check): " + e.message);
            return; 
        }

        // =================================================================
        // ✅ BƯỚC 3: ODOO LOGIC (TĂNG SỐ LƯỢNG)
        // =================================================================
        // Chỉ chạy xuống đây nếu Bước 1 & 2 đều qua cửa
        await super.processBarcode(...arguments);

        // ĐÃ BỎ AUTO SAVE THEO YÊU CẦU
    },

    async _identifyProductSafe(barcode) {
        let product = null;
        if (this.cache.products) product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        if (!product && this.currentState.lines) {
             const line = this.currentState.lines.find(l => {
                 const pId = l.product_id && l.product_id.id ? l.product_id.id : l.product_id;
                 // So sánh barcode hoặc code
                 const pBarcode = l.product_id && l.product_id.barcode;
                 const pCode = l.product_id && l.product_id.default_code;
                 return (pBarcode === barcode || pCode === barcode);
             });
             if (line) product = line.product_id;
        }
        return product;
    }
});