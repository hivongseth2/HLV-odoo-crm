/** @odoo-module **/

// 1. SỬA IMPORT (Thêm ngoặc nhọn { } là quan trọng nhất)
import { BarcodeModel } from "@stock_barcode/models/barcode_model";
import { LineComponent } from "@stock_barcode/components/line"; // Component vẽ giao diện dòng
import { patch } from "@web/core/utils/patch";
import { onMounted, onPatched } from "@odoo/owl"; // Hook của OWL

// Test xem file chạy chưa
console.log("🔥🔥🔥 V33 LOADED 🔥🔥🔥");

// =============================================================================
// HELPER: LOGIC VẼ TỒN KHO (UI)
// =============================================================================

async function renderStockForLine(component) {
    // component.el là phần tử HTML của dòng đó
    const lineEl = component.el;
    if (!lineEl || lineEl.querySelector(".hlv-inline-stock")) return;

    const lineData = component.props.line; // Dữ liệu dòng từ Odoo props
    const product = lineData.product_id;

    if (!product) return;

    try {
        // Gọi API tìm tồn kho
        const domain = [
            ['product_id', '=', product.id],
            ['location_id.usage', '=', 'internal']
        ];
        
        // Lấy prefix kho từ tên vị trí hiện tại của dòng
        // VD: KBC/Tồn kho -> KBC
        let whPrefix = "KHO";
        const locEl = document.querySelector('.o_barcode_location_line');
        if (locEl && locEl.dataset.location) {
            whPrefix = locEl.dataset.location.split('/')[0].toUpperCase();
        }

        const orm = component.env.model.orm; // Lấy ORM từ môi trường component
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        let totalQty = 0;
        if (quants && quants.length > 0) {
            quants.forEach(q => {
                const locName = q.location_id ? q.location_id[1] : ""; 
                if (locName.toUpperCase().includes(whPrefix)) {
                    totalQty += q.quantity;
                }
            });
        }

        // Vẽ Badge
        const destContainer = lineEl.querySelector('div[name="destination_location"]') || lineEl.querySelector('div[name="quantity"]');
        if (destContainer) {
            let badge = document.createElement("span"); 
            badge.className = "hlv-inline-stock";
            badge.style.cssText = "display: inline-block; background-color: #17a2b8; color: white; font-weight: bold; font-size: 11px; padding: 2px 6px; border-radius: 4px; margin-left: 5px; z-index: 99; border: 1px solid white;";
            badge.innerHTML = `<i class="fa fa-cubes"></i> ${whPrefix}: ${totalQty}`;
            destContainer.appendChild(badge);
        }

    } catch(e) {
        console.warn("UI Render Error:", e);
    }
}

// =============================================================================
// PATCH 1: UI OVERRIDE (Can thiệp vào LineComponent)
// =============================================================================
// Đây là cách chuẩn để sửa giao diện: Hook vào lúc Component được vẽ (Mounted)
patch(LineComponent.prototype, {
    setup() {
        super.setup();
        // Khi dòng được vẽ lần đầu
        onMounted(() => {
            renderStockForLine(this);
        });
        // Khi dòng được cập nhật (ví dụ quét thêm số lượng)
        onPatched(() => {
            renderStockForLine(this);
        });
    }
});

// =============================================================================
// PATCH 2: LOGIC OVERRIDE (Can thiệp vào BarcodeModel)
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

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V33: LOGIC PATCHED SUCCESSFULLY");
        
        // Chặn F5
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault();
            e.returnValue = 'Dữ liệu chưa lưu!';
        });
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            console.log("⚡ Checking barcode:", barcode); // Log để debug
            
            const product = await this._identifyProductSafe(barcode);
            let currentLoc = this.location;
            let currentLocId = currentLoc ? currentLoc.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            if (product && this.currentState.lines) {
                const productLines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
                let totalDone = 0;
                let totalDemand = 0;
                let qtyDoneAtCurrentLoc = 0;

                productLines.forEach(l => {
                    const d = parseFloat(l.qty_done || 0);
                    const r = parseFloat(getLineDemand(l));
                    totalDone += d;
                    totalDemand += r;
                    if (currentLocId && extractId(l.location_id) === currentLocId) qtyDoneAtCurrentLoc += d;
                });

                // CHECK LIMIT
                if (totalDemand === 0) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ SẢN PHẨM NGOÀI KẾ HOẠCH!\nSP: ${product.display_name}`);
                    return;
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\nSP: ${product.display_name}`);
                    return;
                }

                // CHECK STOCK
                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${result.message}`);
                        return;
                    }
                    if (currentLocId && result && result.qty !== undefined) {
                        const nextQty = qtyDoneAtCurrentLoc + 1;
                        if (nextQty > result.qty) {
                            safePlaySound(this.env, 'error');
                            alert(`⛔ QUÁ TỒN KHO THỰC TẾ!\n📦 Tồn: ${result.qty}\n👉 Bạn muốn lấy: ${nextQty}`);
                            return;
                        }
                    }
                } catch (e) { console.warn(e); }
            }

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