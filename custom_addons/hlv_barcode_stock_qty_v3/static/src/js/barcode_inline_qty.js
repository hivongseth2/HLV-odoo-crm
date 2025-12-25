/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: CÔNG CỤ HỖ TRỢ (AN TOÀN TUYỆT ĐỐI)
// =============================================================================

// Hàm lấy ID an toàn (Xử lý trường hợp ID là mảng [id, name] hoặc số nguyên)
function extractId(field) {
    if (!field) return null;
    if (Array.isArray(field)) return field[0];
    if (typeof field === 'object') return field.id;
    return field;
}

// Hàm phát âm thanh (Không dùng env để tránh crash)
function playSystemSound() {
    try {
        new Audio('/web/static/src/audio/error.mp3').play().catch(() => {});
    } catch (e) {}
}

// Hàm vẽ Inline Stock
async function renderInlineStock(lineEl, orm) {
    let defaultCode = lineEl.dataset.barcode;
    if (!defaultCode) {
        const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
        if (codeEl) defaultCode = codeEl.textContent.trim();
    }
    // Tránh vẽ lại
    if (!defaultCode || lineEl.querySelector(".hlv-inline-stock")) return;

    try {
        // console.log("[HLV] Getting stock for:", defaultCode);
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
    } catch(e) { 
        // Silent fail for inline
    }
}

// =============================================================================
// MAIN LOGIC
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] DEBUG MODE ACTIVATED: LOG ALL");
        
        const observer = new MutationObserver(() => {
            document.querySelectorAll(".o_barcode_line").forEach(line => renderInlineStock(line, this.orm));
        });
        const wait = setInterval(() => {
            if (document.body) {
                observer.observe(document.body, { childList: true, subtree: true });
                clearInterval(wait);
            }
        }, 1000);
    },

    async processBarcode(barcode) {
        console.log("\n========================================");
        console.log("⚡ [HLV] PROCESSING BARCODE:", barcode);

        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // --- 1. NHẬN DIỆN SẢN PHẨM ---
        const product = await this._identifyProductSafe(barcode);
        
        if (!product) {
            console.log("⚠️ [HLV] Product not found for barcode:", barcode);
            // Để super xử lý (có thể là lệnh hoặc barcode lạ)
            return super.processBarcode(...arguments);
        }

        console.log("📦 [HLV] Identified Product:", product.display_name, "(ID:", product.id, ")");

        // =================================================================
        // ⛔ BƯỚC 1: TÍNH TỔNG SỐ LƯỢNG (XỬ LÝ ĐA VỊ TRÍ)
        // =================================================================
        if (this.currentState.lines) {
            let totalDone = 0;
            let totalDemand = 0;
            let lineCount = 0;

            // Lặp qua TOÀN BỘ dòng để tìm sản phẩm này
            for (const line of this.currentState.lines) {
                const linePid = extractId(line.product_id);
                
                // So sánh ID
                if (linePid === product.id) {
                    lineCount++;
                    // Cộng dồn qty_done và product_uom_qty (nhu cầu)
                    totalDone += parseFloat(line.qty_done || 0);
                    // Lưu ý: Odoo có thể dùng 'product_uom_qty' hoặc 'reserved_uom_qty'. Thường Barcode dùng product_uom_qty là Demand.
                    totalDemand += parseFloat(line.product_uom_qty || 0);
                }
            }

            console.log(`📊 [HLV] STATS: Found ${lineCount} lines.`);
            console.log(`📊 [HLV] STATS: Total Done: ${totalDone} | Total Demand: ${totalDemand}`);

            // LOGIC CHẶN:
            // 1. Unplanned: Không có nhu cầu (Demand = 0)
            if (totalDemand === 0) {
                console.error("⛔ [HLV] BLOCK: UNPLANNED (Demand is 0)");
                playSystemSound();
                alert(`⚠️ CHẶN NGOÀI KẾ HOẠCH!\n\nSản phẩm: ${product.display_name}\nKhông có trong phiếu yêu cầu (Demand = 0).`);
                return; // DỪNG
            }

            // 2. Over Limit: Đã làm >= Nhu cầu
            if (totalDone >= totalDemand) {
                console.error("⛔ [HLV] BLOCK: OVER LIMIT");
                playSystemSound();
                alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n\nSản phẩm: ${product.display_name}\nTiến độ: ${totalDone}/${totalDemand}\n\nKhông thể quét thêm (Vui lòng kiểm tra các dòng khác nếu có tách dòng).`);
                return; // DỪNG
            }
        }

        // =================================================================
        // 🌍 BƯỚC 2: CHECK SERVER (VỊ TRÍ)
        // =================================================================
        let sourceLocId = this.location ? this.location.id : (this.record.location_id ? extractId(this.record.location_id) : null);
        let locName = (this.location?.display_name || this.record?.display_name || "");
        let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

        console.log(`🌐 [HLV] Checking Location Availability... Prefix: ${whPrefix}, LocID: ${sourceLocId}`);

        try {
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId]);
            console.log("📩 [HLV] Server Response:", result);

            if (result && result.allow === false) {
                console.error("⛔ [HLV] BLOCK: WRONG LOCATION");
                playSystemSound();
                // Dùng Alert để không bao giờ bị lỗi 'services undefined'
                alert(`⛔ SAI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                return; // DỪNG
            }

        } catch (e) {
            console.error("❌ [HLV] SERVER CHECK ERROR:", e);
            alert("Lỗi kết nối kiểm tra tồn kho! Vui lòng thử lại.");
            return; // Dừng nếu lỗi mạng để an toàn
        }

        // =================================================================
        // ✅ BƯỚC 3: ODOO XỬ LÝ (TĂNG SỐ LƯỢNG)
        // =================================================================
        console.log("✅ [HLV] All Checks Passed -> Incrementing Qty");
        await super.processBarcode(...arguments);
    },

    async _identifyProductSafe(barcode) {
        let product = null;
        if (this.cache.products) {
            product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        }
        // Fallback: Tìm trong lines nếu cache chưa đầy đủ
        if (!product && this.currentState.lines) {
             const line = this.currentState.lines.find(l => {
                 const pId = extractId(l.product_id);
                 // Logic tìm tương đối qua barcode dòng
                 // Lưu ý: dòng l.product_id trong barcode model thường là Object {id, display_name, barcode...}
                 const pObj = l.product_id; 
                 if (typeof pObj === 'object') {
                     return pObj.barcode === barcode || pObj.default_code === barcode;
                 }
                 return false;
             });
             if (line) product = line.product_id;
        }
        return product;
    }
});