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
        console.log("🚀 [HLV] FINAL: LOCATION CHECK + QTY LIMIT (STRICT)");
        
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
        // ⛔ BƯỚC 1: CHECK SỐ LƯỢNG (CHẶN DƯ & CHẶN NGOÀI KẾ HOẠCH)
        // =================================================================
        if (product && this.currentState.lines) {
            let totalDone = 0;
            let totalDemand = 0;

            // Lặp qua TOÀN BỘ dòng để tìm sản phẩm này
            for (const line of this.currentState.lines) {
                // Xử lý ID an toàn: line.product_id có thể là [id, "Name"] hoặc id
                const linePid = Array.isArray(line.product_id) ? line.product_id[0] : line.product_id;
                
                if (linePid === product.id) {
                    totalDone += parseFloat(line.qty_done || 0);
                    totalDemand += parseFloat(line.product_uom_qty || 0);
                }
            }

            // console.log(`🔍 [HLV] Check Limit: ${product.display_name} | Done: ${totalDone} | Demand: ${totalDemand}`);

            // LOGIC CHẶN CỨNG:
            // 1. Nếu Demand > 0 mà Done >= Demand => Đã đủ => CHẶN
            // 2. Nếu Demand == 0 => Hàng không có trong phiếu => CHẶN LUÔN
            
            const isFull = (totalDemand > 0 && totalDone >= totalDemand);
            const isUnplanned = (totalDemand === 0);

            if (isFull || isUnplanned) {
                safePlaySound(this.env, 'error');
                
                let msg = "";
                if (isUnplanned) {
                    msg = `⚠️ SẢN PHẨM KHÔNG CÓ TRONG PHIẾU!\n\nSP: ${product.display_name}\n\nBạn đang quét sản phẩm không được yêu cầu lấy.`;
                } else {
                    msg = `⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n\nSP: ${product.display_name}\nĐã lấy: ${totalDone}/${totalDemand}\n\nKhông được phép lấy dư!`;
                }

                // Dùng alert để chặn đứng process
                alert(msg);
                return; // RETURN NGAY - KHÔNG CHẠY TIẾP
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
                alert(`⛔ SAI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                return; 
            }
        } catch (e) {
            // Lỗi mạng/server -> Cảnh báo nhưng có thể cho qua hoặc chặn tùy bạn
            console.error(e);
        }

        // =================================================================
        // ✅ BƯỚC 3: ODOO XỬ LÝ (TĂNG SỐ LƯỢNG)
        // =================================================================
        // Chỉ chạy xuống đây nếu Bước 1 & 2 đều qua cửa
        await super.processBarcode(...arguments);
    },

    async _identifyProductSafe(barcode) {
        let product = null;
        if (this.cache.products) product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        if (!product && this.currentState.lines) {
             const line = this.currentState.lines.find(l => {
                 const pId = Array.isArray(l.product_id) ? l.product_id[0] : l.product_id;
                 const pBarcode = l.product_id.barcode; // Có thể undefined nếu l.product_id là ID
                 // Fallback tìm tương đối
                 return false; 
             });
             // Logic tìm fallback đơn giản hơn để tránh lỗi
             if (!product) {
                 // Tìm trong cache lines nếu có full data
             }
        }
        return product;
    }
});