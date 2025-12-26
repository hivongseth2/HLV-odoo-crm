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
    // Lấy số lượng yêu cầu (Demand)
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

// MÀN HÌNH CHỜ ĐƠN GIẢN (Để tránh quét quá nhanh gây loạn)
function toggleLoading(show) {
    let el = document.getElementById('hlv-loading');
    if (!el) {
        el = document.createElement('div');
        el.id = 'hlv-loading';
        el.style.cssText = "position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.3); z-index: 99999; display: none; cursor: wait;";
        document.body.appendChild(el);
    }
    el.style.display = show ? 'block' : 'none';
}

// =============================================================================
// MAIN LOGIC V23 - GATEKEEPER MODE (CHỈ CHẶN - KHÔNG SỬA)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V23: GATEKEEPER MODE (Simple & Strict)");
        
        // Vẫn giữ chặn F5 để an toàn (Optional)
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault();
            e.returnValue = 'Dữ liệu chưa lưu xong?';
        });
    },

    async processBarcode(barcode) {
        // 1. CHỐNG SPAM (Khóa màn hình khi đang xử lý)
        if (this._isWorking) return;
        
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        this._isWorking = true;
        toggleLoading(true);

        try {
            // 2. NHẬN DIỆN SẢN PHẨM (Để kiểm tra)
            const product = await this._identifyProductSafe(barcode);
            
            if (product && this.currentState.lines) {
                // Tính toán tổng số lượng hiện tại
                const productLines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
                
                let totalDone = 0;
                let totalDemand = 0;

                productLines.forEach(l => {
                    totalDone += parseFloat(l.qty_done || 0);
                    totalDemand += parseFloat(getLineDemand(l));
                });

                // 🛑 CHỐT CHẶN 1: QUÉT DƯ (LIMIT)
                if (totalDemand === 0) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ SẢN PHẨM KHÔNG CÓ TRONG PHIẾU!\nSP: ${product.display_name}`);
                    return; // Dừng ngay, không cho Odoo xử lý
                }
                
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\nSP: ${product.display_name}\nĐã quét: ${totalDone}/${totalDemand}`);
                    return; // Dừng ngay
                }

                // 🌍 CHỐT CHẶN 2: SAI VỊ TRÍ (LOCATION)
                // Lấy thông tin vị trí hiện tại
                let currentLoc = this.location;
                let checkLocId = currentLoc ? currentLoc.id : (this.record.location_id ? extractId(this.record.location_id) : null);
                let locName = (currentLoc?.display_name || this.record?.display_name || "");
                let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${result.message || "Không có hàng ở đây!"}`);
                        return; // Dừng ngay
                    }
                } catch (e) {
                    console.error("Check Location Error", e);
                    // Nếu mất mạng thì có thể cho qua hoặc chặn tùy bạn. Ở đây chặn cho an toàn.
                    alert("Lỗi kết nối kiểm tra vị trí!");
                    return;
                }
            }

            // ✅ NẾU TẤT CẢ OK -> MỞ CỔNG CHO ODOO CHẠY
            // Gọi hàm gốc của Odoo. Odoo sẽ tự động tìm dòng, cộng số lượng, tách dòng theo logic chuẩn của nó.
            await super.processBarcode(...arguments);

            // 💾 LƯU AN TOÀN
            // Gọi lệnh save ngay sau khi quét để đảm bảo F5 không mất dữ liệu.
            // (Không dùng write thủ công nữa)
            await this.save();

        } catch (err) {
            console.error(err);
            alert("Lỗi: " + err.message);
        } finally {
            this._isWorking = false;
            toggleLoading(false);
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