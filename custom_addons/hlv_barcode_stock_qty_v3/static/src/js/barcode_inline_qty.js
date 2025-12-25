/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: CÁC HÀM HỖ TRỢ
// =============================================================================

function safeNotify(env, message, type = 'warning') {
    try {
        if (env && env.services && env.services.notification) {
            env.services.notification.add(message, { type: type, sticky: type === 'danger' });
        }
    } catch (e) {}
}

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
        console.log("🚀 [HLV] Barcode Security: ACTIVE");
        
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
        // ⛔ BƯỚC 1: CHẶN QUÉT DƯ (HARD BLOCK)
        // =================================================================
        // Logic: Tìm dòng sản phẩm đó -> Check Đã làm (Done) vs Nhu cầu (Demand)
        if (product && this.currentState.lines) {
            const line = this.currentState.lines.find(l => l.product_id.id === product.id);
            
            if (line) {
                const done = parseFloat(line.qty_done || 0);
                const demand = parseFloat(line.product_uom_qty || 0);

                // DEBUG LOG: Để bạn F12 kiểm tra
                console.log(`🔍 Check Limit: ${product.display_name} | Done: ${done} | Demand: ${demand}`);

                // Nếu có yêu cầu (Demand > 0) VÀ Đã làm xong (Done >= Demand)
                if (demand > 0 && done >= demand) {
                    console.error("⛔ BLOCKED: FULL QUANTITY");
                    
                    // 1. Âm thanh lỗi
                    safePlaySound(this.env, 'error');
                    
                    // 2. Alert Cứng (Bắt buộc click OK mới tắt)
                    alert(`⚠️ DỪNG LẠI!\n\nSản phẩm: ${product.display_name}\nĐã đủ số lượng: ${done}/${demand}\n\nKhông được phép quét thêm!`);
                    
                    // 3. Return ngay lập tức (Chặn đứng mọi thứ)
                    return; 
                }
            }
        }

        // =================================================================
        // 🌍 BƯỚC 2: CHECK SERVER (VỊ TRÍ CÓ HÀNG KHÔNG?)
        // =================================================================
        let sourceLocId = this.location ? this.location.id : (this.record.location_id ? (Array.isArray(this.record.location_id) ? this.record.location_id[0] : this.record.location_id) : null);
        let locName = (this.location?.display_name || this.record?.display_name || "");
        let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

        try {
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId]);
            
            // NẾU BỊ CHẶN (Allow = False)
            if (result && result.allow === false) {
                safePlaySound(this.env, 'error');
                
                // Alert Cứng cho lỗi vị trí luôn
                alert(`⛔ LỖI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                
                return; // CHẶN
            }
            if (result && result.message) safeNotify(this.env, result.message, 'warning');

        } catch (e) {
            // Nếu lỗi server check, chặn luôn cho an toàn
            alert("Lỗi kiểm tra tồn kho: " + e.message);
            return; 
        }

        // =================================================================
        // ✅ BƯỚC 3: ODOO XỬ LÝ (TĂNG SỐ LƯỢNG)
        // =================================================================
        // Chỉ chạy xuống đây nếu Bước 1 & 2 đều qua cửa
        await super.processBarcode(...arguments);

        // =================================================================
        // 💾 BƯỚC 4: AUTO SAVE (WRITE DB)
        // =================================================================
        try {
            if (product && this.currentState.lines) {
                const line = this.currentState.lines.find(l => l.product_id.id === product.id);
                if (line) {
                    if (line.id && typeof line.id === 'number') {
                        // Line cũ -> Write (Nhanh)
                        await this.orm.write("stock.move.line", [line.id], { "qty_done": line.qty_done });
                    } else {
                        // Line mới -> Save tổng (Chậm hơn chút)
                        await this.save();
                    }
                }
            }
        } catch (err) {
            console.error("Save Error:", err);
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