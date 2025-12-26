/** @odoo-module **/

import  BarcodeModel  from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function extractId(field) {
    if (!field) return null;
    if (Array.isArray(field)) return field[0];
    if (typeof field === 'object') return field.id;
    return field;
}

function getLineDemand(line) {
    // Lấy Demand chuẩn theo Odoo 18
    if (line.reserved_uom_qty > 0) return line.reserved_uom_qty;
    if (line.product_uom_qty > 0) return line.product_uom_qty;
    if (line.quantity_product_uom > 0) return line.quantity_product_uom;
    return 0;
}

function safePlaySound(env, type = 'error') {
    try {
        if (env.services.sound) {
            env.services.sound.play(type);
        } else {
            new Audio('/web/static/src/audio/error.mp3').play().catch(() => {});
        }
    } catch (e) {}
}

// =============================================================================
// MAIN LOGIC V24 - FIX LAG SAVE & REMOVE LOCK
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V24: SYNC FIX + NO LOCK");
        
        // Chặn F5 (Browser Native)
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault();
            e.returnValue = 'Dữ liệu chưa lưu xong. Đừng F5!';
        });
    },

    async processBarcode(barcode) {
        // 1. BỎ KHÓA (NO LOCK) -> Giúp quét liên tục không bị miss
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // 2. KIỂM TRA TRƯỚC (VALIDATION)
            const product = await this._identifyProductSafe(barcode);
            
            if (product && this.currentState.lines) {
                const productLines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
                
                let totalDone = 0;
                let totalDemand = 0;

                productLines.forEach(l => {
                    totalDone += parseFloat(l.qty_done || 0);
                    totalDemand += parseFloat(getLineDemand(l));
                });

                // 🛑 CHẶN 1: QUÉT DƯ
                if (totalDemand === 0) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ SẢN PHẨM NGOÀI KẾ HOẠCH!\nSP: ${product.display_name}`);
                    return; 
                }
                
                // Lưu ý: So sánh >= vì chuẩn bị quét thêm 1 cái nữa
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\nSP: ${product.display_name}\nĐã quét: ${totalDone}/${totalDemand}`);
                    return;
                }

                // 🌍 CHẶN 2: SAI VỊ TRÍ
                let currentLoc = this.location;
                let checkLocId = currentLoc ? currentLoc.id : (this.record.location_id ? extractId(this.record.location_id) : null);
                let locName = (currentLoc?.display_name || this.record?.display_name || "");
                let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${result.message || "Không có hàng ở đây!"}`);
                        return;
                    }
                } catch (e) {
                    console.warn("Check location failed, skipping check...");
                }
            }

            // ✅ 3. GỌI ODOO XỬ LÝ (SUPER)
            // Để Odoo tự tăng số lượng, tự tách dòng.
            await super.processBarcode(...arguments);

            // 🕒 4. FIX LỖI "SAVE CHẬM 1 NHỊP"
            // Chờ 50ms để Odoo kịp cập nhật State (RAM) sau khi super chạy xong
            await new Promise(resolve => setTimeout(resolve, 50));

            // 💾 5. LƯU NGAY
            await this.save();
            console.log("✅ Save syncd!");

        } catch (err) {
            console.error(err);
            alert("Lỗi: " + err.message);
        }
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