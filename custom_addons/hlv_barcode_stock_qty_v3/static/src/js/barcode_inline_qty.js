/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: CÁC CÔNG CỤ AN TOÀN (KHÔNG CRASH)
// =============================================================================

// 1. Lấy ID an toàn
function extractId(field) {
    if (!field) return null;
    if (Array.isArray(field)) return field[0];
    if (typeof field === 'object') return field.id;
    return field;
}

// 2. Lấy số lượng Yêu cầu (Demand) thông minh
// Odoo mỗi bản mỗi khác, hàm này sẽ quét hết các trường có thể chứa số lượng
function getLineDemand(line) {
    // Ưu tiên reserved_uom_qty (số đã giữ chỗ)
    if (line.reserved_uom_qty > 0) return line.reserved_uom_qty;
    // Tiếp theo là product_uom_qty
    if (line.product_uom_qty > 0) return line.product_uom_qty;
    // Các trường hợp lạ khác
    if (line.qty_reserved > 0) return line.qty_reserved;
    if (line.demand_qty > 0) return line.demand_qty;
    return 0;
}

// 3. Âm thanh an toàn
function playSystemSound() {
    try {
        // Thử phát file chuẩn
        const audio = new Audio('/web/static/src/audio/error.mp3');
        const playPromise = audio.play();
        if (playPromise !== undefined) {
            playPromise.catch(error => {
                // Nếu lỗi file, thử dùng beep hệ thống nếu có thể (hoặc bỏ qua)
                console.warn("Audio play failed, relying on Alert.");
            });
        }
    } catch (e) {}
}

// 4. Inline Stock
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
    } catch(e) {}
}

// =============================================================================
// MAIN LOGIC
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] FINAL FIX v3: STARTING...");
        
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
        // --- 0. Bỏ qua lệnh hệ thống ---
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // --- 1. NHẬN DIỆN SẢN PHẨM ---
        const product = await this._identifyProductSafe(barcode);
        
        if (!product) {
            // Không nhận diện được thì để mặc định Odoo xử lý
            return super.processBarcode(...arguments);
        }

        // =================================================================
        // ⛔ BƯỚC 1: CHECK LIMIT (TÍNH TỔNG CỘNG DỒN)
        // =================================================================
        if (this.currentState.lines) {
            let totalDone = 0;
            let totalDemand = 0;
            let foundLines = false;
            let debugLine = null; // Để log xem object nó chứa cái gì

            // Lặp qua TOÀN BỘ dòng để tìm sản phẩm này
            for (const line of this.currentState.lines) {
                const linePid = extractId(line.product_id);
                
                if (linePid === product.id) {
                    foundLines = true;
                    debugLine = line; // Lưu mẫu 1 dòng để soi

                    // Cộng dồn
                    totalDone += parseFloat(line.qty_done || 0);
                    // Dùng hàm thông minh để lấy Demand
                    totalDemand += parseFloat(getLineDemand(line));
                }
            }

            // --- DEBUG QUAN TRỌNG: MỞ F12 NẾU VẪN LỖI ĐỂ XEM ---
            console.log(`🔍 [HLV] CHECKING: ${product.display_name}`);
            console.log(`   - Total Done: ${totalDone}`);
            console.log(`   - Total Demand: ${totalDemand}`);
            if (debugLine && totalDemand === 0) {
                console.warn("⚠️ Demand is 0. Inspecting line object keys:", Object.keys(debugLine));
                console.warn("⚠️ Line Data:", debugLine);
            }
            // ----------------------------------------------------

            // LOGIC CHẶN:
            const isUnplanned = (totalDemand === 0);
            // Lưu ý: Chỉ chặn dư nếu demand > 0. 
            // Nếu bạn muốn cho phép quét hàng ngoài (Unplanned) thì bỏ dòng isUnplanned bên dưới đi.
            // Nhưng theo yêu cầu là "Cấm quét dư", tức là phải có trong phiếu mới được quét.

            if (isUnplanned) {
                console.error("⛔ BLOCK: UNPLANNED");
                playSystemSound();
                alert(`⚠️ CHẶN NGOÀI KẾ HOẠCH!\n\nSản phẩm: ${product.display_name}\nKhông có trong phiếu yêu cầu (Demand = 0).`);
                return; 
            }

            if (totalDone >= totalDemand) {
                console.error("⛔ BLOCK: OVER LIMIT");
                playSystemSound();
                alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n\nSản phẩm: ${product.display_name}\nTiến độ: ${totalDone}/${totalDemand}\n\nKhông thể quét thêm.`);
                return; 
            }
        }

        // =================================================================
        // 🌍 BƯỚC 2: CHECK SERVER (VỊ TRÍ)
        // =================================================================
        let sourceLocId = this.location ? this.location.id : (this.record.location_id ? extractId(this.record.location_id) : null);
        let locName = (this.location?.display_name || this.record?.display_name || "");
        let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

        try {
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId]);
            
            if (result && result.allow === false) {
                console.error("⛔ BLOCK: LOCATION");
                playSystemSound();
                alert(`⛔ SAI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                return; // CHẶN
            }

        } catch (e) {
            console.error("❌ Check Location Error:", e);
            alert("Lỗi kết nối kiểm tra vị trí! Vui lòng thử lại.");
            return; // Dừng nếu lỗi để đảm bảo an toàn
        }

        // =================================================================
        // ✅ BƯỚC 3: OK HẾT -> CHO PHÉP ODOO XỬ LÝ
        // =================================================================
        await super.processBarcode(...arguments);
    },

    async _identifyProductSafe(barcode) {
        let product = null;
        if (this.cache.products) {
            product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        }
        // Fallback tìm trong lines
        if (!product && this.currentState.lines) {
             const line = this.currentState.lines.find(l => {
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