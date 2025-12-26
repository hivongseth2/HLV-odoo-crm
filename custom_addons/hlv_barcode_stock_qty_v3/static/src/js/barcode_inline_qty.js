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
// MAIN LOGIC V25 - DIRECT WRITE (GHI THẲNG DB - KHÔNG CHỜ SUPER)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V25: DIRECT WRITE MODE (Fix Lag & Loss)");
        
        // Chặn F5 (Browser Native)
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault();
            e.returnValue = 'Dữ liệu chưa lưu xong. Đừng F5!';
        });
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // 1. NHẬN DIỆN SẢN PHẨM
            const product = await this._identifyProductSafe(barcode);
            
            // 2. LẤY THÔNG TIN VỊ TRÍ
            let currentLoc = this.location;
            let currentLocId = currentLoc ? currentLoc.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            // Nếu nhận diện được sản phẩm, ta sẽ tự xử lý (để tránh lag)
            if (product && this.currentState.lines) {
                const productLines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
                
                let totalDone = 0;
                let totalDemand = 0;
                
                // Logic tìm dòng mục tiêu (Target Line)
                // Ưu tiên 1: Dòng đang ở đúng vị trí (Tủ 3) -> Cộng dồn
                // Ưu tiên 2: Dòng ở kho nguồn (chưa làm) -> Lấy để chuyển
                let targetLine = null;
                let localLine = null;
                let sourceLine = null;

                productLines.forEach(l => {
                    const d = parseFloat(l.qty_done || 0);
                    const r = parseFloat(getLineDemand(l));
                    totalDone += d;
                    totalDemand += r;
                    
                    const lineLocId = extractId(l.location_id);
                    if (currentLocId && lineLocId === currentLocId) localLine = l;
                    else if (d < r) sourceLine = l;
                });

                // 🛑 CHẶN 1: QUÉT DƯ
                if (totalDemand === 0) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ SẢN PHẨM NGOÀI KẾ HOẠCH!\nSP: ${product.display_name}`);
                    return; 
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\nSP: ${product.display_name}\nĐã quét: ${totalDone}/${totalDemand}`);
                    return;
                }

                // 🌍 CHẶN 2: SAI VỊ TRÍ
                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${result.message || "Không có hàng ở đây!"}`);
                        return;
                    }
                } catch (e) { /* Bỏ qua lỗi mạng check, ưu tiên cho quét */ }

                // 🚀 XỬ LÝ GHI DỮ LIỆU (QUAN TRỌNG)
                if (localLine) targetLine = localLine;
                else if (sourceLine) targetLine = sourceLine;

                // NẾU TÌM ĐƯỢC DÒNG CÓ ID THẬT (Đã lưu trong DB)
                // -> Ta dùng ORM WRITE để ghi thẳng +1 vào DB. Nhanh và chắc chắn 100%.
                if (targetLine && targetLine.id && typeof targetLine.id === 'number') {
                    console.log(`✅ [HLV] Direct Write ID: ${targetLine.id}`);
                    
                    const newQty = (targetLine.qty_done || 0) + 1;
                    
                    // 1. GHI DB (Quan trọng nhất)
                    await this.orm.write("stock.move.line", [targetLine.id], { 
                        "qty_done": newQty,
                        "location_id": currentLocId || extractId(targetLine.location_id) // Cập nhật luôn vị trí nếu cần
                    });

                    // 2. CẬP NHẬT GIAO DIỆN (Để người dùng thấy ngay)
                    targetLine.qty_done = newQty;
                    if (currentLoc) targetLine.location_id = currentLoc;
                    this.trigger('update');

                    // 3. DONE (Không gọi super, Không gọi save nữa vì đã write rồi)
                    return;
                }
            }

            // FALLBACK: Nếu là dòng mới tinh (chưa có ID) hoặc không tìm thấy dòng
            // Thì mới nhờ Odoo xử lý hộ (chấp nhận rủi ro lag nhẹ ở các dòng mới này)
            await super.processBarcode(...arguments);
            await this.save();

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