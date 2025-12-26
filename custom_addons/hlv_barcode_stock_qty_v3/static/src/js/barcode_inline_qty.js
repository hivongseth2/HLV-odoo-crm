/** @odoo-module **/

import  BarcodeModel  from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

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

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V27: STOCK LIMIT CHECK (Fix Negative Scan)");
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault(); e.returnValue = 'Đừng F5 khi đang lưu!';
        });
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // 1. NHẬN DIỆN
            const product = await this._identifyProductSafe(barcode);
            
            // 2. LẤY VỊ TRÍ
            let currentLoc = this.location;
            let currentLocId = currentLoc ? currentLoc.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            if (product && this.currentState.lines) {
                const productLines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
                
                let totalDone = 0;
                let totalDemand = 0;
                let qtyDoneAtCurrentLoc = 0; // Đếm số lượng đã quét tại vị trí đang đứng

                let targetLine = null;
                let localLine = null;
                let sourceLine = null;

                productLines.forEach(l => {
                    const d = parseFloat(l.qty_done || 0);
                    const r = parseFloat(getLineDemand(l));
                    totalDone += d;
                    totalDemand += r;
                    
                    const lineLocId = extractId(l.location_id);
                    // Nếu dòng này nằm đúng vị trí đang check -> Cộng vào bộ đếm
                    if (currentLocId && lineLocId === currentLocId) {
                        localLine = l;
                        qtyDoneAtCurrentLoc += d;
                    } else if (d < r) {
                        sourceLine = l;
                    }
                });

                // 🛑 CHẶN 1: DƯ DEMAND (KẾ HOẠCH)
                if (totalDemand === 0) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ SẢN PHẨM NGOÀI KẾ HOẠCH!\nSP: ${product.display_name}`);
                    return; 
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG KẾ HOẠCH!\nSP: ${product.display_name}`);
                    return;
                }

                // 🌍 CHẶN 2: TỒN KHO THỰC TẾ (QUANTITY LIMIT)
                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    
                    // A. Sai vị trí
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${result.message || "Không có hàng ở đây!"}`);
                        return;
                    }

                    // B. Quá số lượng tồn kho (NEW FIX)
                    // Chỉ check khi ta đang đứng ở 1 vị trí cụ thể và server trả về số lượng
                    if (currentLocId && result && result.qty !== undefined) {
                        // Số sắp quét = Đã quét tại đây + 1
                        const nextQty = qtyDoneAtCurrentLoc + 1;
                        if (nextQty > result.qty) {
                            safePlaySound(this.env, 'error');
                            alert(`⛔ QUÁ TỒN KHO THỰC TẾ!\n\n📍 Vị trí: ${currentLoc.display_name}\n📦 Tồn kho: ${result.qty}\n👉 Bạn đang cố lấy: ${nextQty}`);
                            return; // CHẶN NGAY
                        }
                    }

                } catch (e) { console.warn("Check location skipped"); }

                // 🚀 XỬ LÝ GHI (DIRECT WRITE)
                if (localLine) targetLine = localLine;
                else if (sourceLine) targetLine = sourceLine;

                if (targetLine && targetLine.id && typeof targetLine.id === 'number') {
                    const newQty = (targetLine.qty_done || 0) + 1;
                    const writeVals = { "qty_done": newQty };
                    if (!localLine && currentLocId) writeVals["location_id"] = currentLocId;

                    await this.orm.write("stock.move.line", [targetLine.id], writeVals);
                    
                    targetLine.qty_done = newQty;
                    if (writeVals["location_id"]) targetLine.location_id = currentLoc;
                    this.trigger('update');
                    return;
                }
            }

            // FALLBACK
            await super.processBarcode(...arguments);
            await new Promise(r => setTimeout(r, 50));
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