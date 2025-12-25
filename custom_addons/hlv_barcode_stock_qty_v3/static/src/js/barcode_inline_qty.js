/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: CÁC HÀM HỖ TRỢ
// =============================================================================

function extractId(field) {
    if (!field) return null;
    if (Array.isArray(field)) return field[0];
    if (typeof field === 'object') return field.id;
    return field;
}

function getLineDemand(line) {
    if (line.reserved_uom_qty > 0) return line.reserved_uom_qty;
    if (line.product_uom_qty > 0) return line.product_uom_qty;
    return 0;
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
    } catch(e) {}
}

// =============================================================================
// MAIN LOGIC
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V4: AUTO MOVE LOCATION + STRICT LIMIT");
        
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
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // 1. NHẬN DIỆN SẢN PHẨM
        const product = await this._identifyProductSafe(barcode);
        
        // Xác định vị trí ĐANG QUÉT (Nơi bạn đang đứng)
        // Nếu bạn vừa quét mã Tủ 3, thì this.location sẽ là Tủ 3
        let currentLocId = this.location ? this.location.id : null; 

        // =================================================================
        // ⛔ BƯỚC 1: CHECK LIMIT & SMART LOCATION SWITCH
        // =================================================================
        if (product && this.currentState.lines) {
            const productLines = this.currentState.lines.filter(l => {
                const linePid = extractId(l.product_id);
                return linePid === product.id;
            });
            
            let totalDone = 0;
            let totalDemand = 0;
            
            // Tìm dòng tiềm năng để "CƯỚP" (Dòng chưa xong)
            let candidateLine = null;

            productLines.forEach(l => {
                const d = parseFloat(l.qty_done || 0);
                const r = parseFloat(getLineDemand(l));
                totalDone += d;
                totalDemand += r;

                // Nếu dòng này chưa xong (Done < Demand), đây là ứng viên để cập nhật
                if (d < r) {
                    candidateLine = l;
                }
            });

            // 1.1 CHẶN QUÉT DƯ
            const isUnplanned = (totalDemand === 0);
            if (isUnplanned) {
                safePlaySound(this.env, 'error');
                alert(`⚠️ CHẶN NGOÀI KẾ HOẠCH!\n\nSản phẩm: ${product.display_name}\nKhông có trong phiếu yêu cầu.`);
                return;
            }
            if (totalDone >= totalDemand) {
                safePlaySound(this.env, 'error');
                alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n\nSản phẩm: ${product.display_name}\nTiến độ: ${totalDone}/${totalDemand}`);
                return;
            }

            // 1.2 TỰ ĐỘNG ĐỔI VỊ TRÍ (SMART MOVE)
            // Nếu tìm thấy dòng chưa xong, VÀ bạn đang đứng ở vị trí khác với vị trí trong phiếu
            // VÀ vị trí bạn đứng là hợp lệ (đã quét mã vị trí trước đó)
            if (candidateLine && currentLocId) {
                const lineLocId = extractId(candidateLine.location_id);
                
                // Nếu vị trí trên dòng KHÁC vị trí hiện tại
                if (lineLocId !== currentLocId) {
                    console.log(`🔄 [HLV] Auto Moving Line ${candidateLine.id} from ${lineLocId} to ${currentLocId}`);
                    
                    try {
                        // Cập nhật dòng cũ: Đổi vị trí sang chỗ mới + Tăng số lượng + Lưu luôn
                        await this.orm.write("stock.move.line", [candidateLine.id], { 
                            "location_id": currentLocId, // Đổi sang Tủ 3
                            "qty_done": candidateLine.qty_done + 1 // Tăng 1
                        });

                        // Cần reload lại state để giao diện cập nhật dòng 0/4 thành 1/4 (ở vị trí mới)
                        // Chúng ta gọi save() để Odoo sync lại toàn bộ giao diện cho chuẩn
                        await this.save(); 
                        
                        // RETURN LUÔN để không chạy logic mặc định (tránh tạo dòng đỏ mới)
                        return; 
                    } catch (e) {
                        console.error("Move Error:", e);
                    }
                }
            }
        }

        // =================================================================
        // 🌍 BƯỚC 2: CHECK SERVER (VỊ TRÍ)
        // =================================================================
        // Logic check hàng có ở đó không (như cũ)
        let sourceLocId = this.location ? this.location.id : (this.record.location_id ? extractId(this.record.location_id) : null);
        let locName = (this.location?.display_name || this.record?.display_name || "");
        let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

        try {
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId]);
            if (result && result.allow === false) {
                safePlaySound(this.env, 'error');
                alert(`⛔ SAI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                return; 
            }
        } catch (e) { console.error(e); }

        // =================================================================
        // ✅ BƯỚC 3: ODOO XỬ LÝ (NẾU KHÔNG PHẢI TRƯỜNG HỢP ĐỔI KHO)
        // =================================================================
        await super.processBarcode(...arguments);
        
        // Auto Save nhẹ cho trường hợp thường
        try {
             const updatedProduct = await this._identifyProductSafe(barcode);
             if (updatedProduct && this.currentState.lines) {
                 // Tìm lại line vừa update
                 const line = this.currentState.lines.find(l => extractId(l.product_id) === updatedProduct.id && l.qty_done <= getLineDemand(l));
                 if (line && line.id && typeof line.id === 'number') {
                     await this.orm.write("stock.move.line", [line.id], { "qty_done": line.qty_done });
                 }
             }
        } catch(e) {}
    },

    async _identifyProductSafe(barcode) {
        let product = null;
        if (this.cache.products) product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        if (!product && this.currentState.lines) {
             const line = this.currentState.lines.find(l => {
                 const pObj = l.product_id; 
                 if (typeof pObj === 'object') return pObj.barcode === barcode || pObj.default_code === barcode;
                 return false;
             });
             if (line) product = line.product_id;
        }
        return product;
    }
});