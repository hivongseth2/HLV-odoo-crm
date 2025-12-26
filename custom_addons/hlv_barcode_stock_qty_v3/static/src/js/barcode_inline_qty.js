/** @odoo-module **/

import { BarcodeModel } from "@stock_barcode/models/barcode_model";
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
// MAIN LOGIC V28 - PURE VALIDATOR (CHỈ CHECK - KHÔNG SAVE)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V28: VALIDATOR ONLY (No Auto-Save)");
        
        // Cảnh báo F5 (Vẫn cần thiết vì bây giờ dữ liệu nằm trên RAM, F5 là mất sạch)
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault();
            e.returnValue = 'Dữ liệu chưa được lưu vào Database! Bạn có chắc muốn tải lại?';
        });
    },

    async processBarcode(barcode) {
        // Nếu là lệnh đặc biệt (O-CMD) hoặc barcode rỗng -> Cho qua
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // 1. NHẬN DIỆN SẢN PHẨM (Để lấy thông tin kiểm tra)
            const product = await this._identifyProductSafe(barcode);
            
            // 2. LẤY THÔNG TIN VỊ TRÍ HIỆN TẠI
            let currentLoc = this.location;
            let currentLocId = currentLoc ? currentLoc.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            // Nếu nhận diện được sản phẩm thì mới kiểm tra
            if (product && this.currentState.lines) {
                const productLines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
                
                let totalDone = 0;
                let totalDemand = 0;
                let qtyDoneAtCurrentLoc = 0; // Đếm số lượng đã quét tại vị trí đang đứng

                productLines.forEach(l => {
                    const d = parseFloat(l.qty_done || 0);
                    const r = parseFloat(getLineDemand(l));
                    totalDone += d;
                    totalDemand += r;
                    
                    const lineLocId = extractId(l.location_id);
                    // Nếu dòng này nằm đúng vị trí đang check -> Cộng vào bộ đếm
                    if (currentLocId && lineLocId === currentLocId) {
                        qtyDoneAtCurrentLoc += d;
                    }
                });

                // 🛑 CHECK 1: KIỂM TRA KẾ HOẠCH (DEMAND)
                if (totalDemand === 0) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ SẢN PHẨM NGOÀI KẾ HOẠCH!\nSP: ${product.display_name}`);
                    return; // Chặn ngay
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\nSP: ${product.display_name}\nĐã quét: ${totalDone}/${totalDemand}`);
                    return; // Chặn ngay
                }

                // 🌍 CHECK 2: KIỂM TRA VỊ TRÍ & TỒN KHO THỰC TẾ
                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    
                    // A. Sai vị trí
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${result.message || "Không có hàng ở đây!"}`);
                        return; // Chặn ngay
                    }

                    // B. Quá số lượng tồn kho (Limit Check)
                    // Logic: Số dự kiến = (Đã quét ở đây + 1) > Tồn kho thực tế -> Báo lỗi
                    if (currentLocId && result && result.qty !== undefined) {
                        const nextQty = qtyDoneAtCurrentLoc + 1;
                        if (nextQty > result.qty) {
                            safePlaySound(this.env, 'error');
                            alert(`⛔ QUÁ TỒN KHO THỰC TẾ!\n\n📍 Vị trí: ${currentLoc.display_name}\n📦 Tồn kho: ${result.qty}\n👉 Bạn đang cố lấy cái thứ: ${nextQty}`);
                            return; // Chặn ngay
                        }
                    }

                } catch (e) { console.warn("Check location skipped (Network/Error)"); }
            }

            // ✅ NẾU TẤT CẢ OK -> CHO ODOO CHẠY LOGIC MẶC ĐỊNH
            // Hàm này sẽ tự xử lý việc tìm dòng, cộng số lượng vào RAM.
            // Chúng ta KHÔNG can thiệp thêm gì nữa.
            await super.processBarcode(...arguments);

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