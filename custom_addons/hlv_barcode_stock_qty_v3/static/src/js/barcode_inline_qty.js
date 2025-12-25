/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
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
    return 0;
}

function safeNotify(env, message, type = 'warning') {
    try {
        if (env && env.services && env.services.notification) {
            // Sticky = true nếu là danger để bắt người dùng phải tắt
            env.services.notification.add(message, { type: type, sticky: type === 'danger' });
        }
    } catch (e) {}
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
        console.log("🚀 [HLV] V10: ANTI-F5 PROTECTION ENABLED");
        
        this.isSaving = false; // Cờ đánh dấu đang lưu

        // 1. Gắn sự kiện chặn F5/Reload
        window.addEventListener("beforeunload", this._onBeforeUnload.bind(this));

        // 2. Observer vẽ Inline Stock
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

    // Hàm xử lý khi người dùng cố F5 hoặc tắt tab
    _onBeforeUnload(ev) {
        // Nếu đang trong quá trình lưu (isSaving = true)
        if (this.isSaving) {
            ev.preventDefault();
            ev.returnValue = 'Dữ liệu đang được lưu. Bạn có chắc muốn rời đi không?';
            return ev.returnValue;
        }
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        const product = await this._identifyProductSafe(barcode);
        
        let currentLocId = this.location ? this.location.id : null;
        let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
        let locName = (this.location?.display_name || this.record?.display_name || "");
        let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

        if (product && this.currentState.lines) {
            const productLines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
            
            let totalDone = 0;
            let totalDemand = 0;
            let candidateLine = null;

            productLines.forEach(l => {
                const d = parseFloat(l.qty_done || 0);
                const r = parseFloat(getLineDemand(l));
                totalDone += d;
                totalDemand += r;
                if (d < r) candidateLine = l;
            });
            // Nếu không có candidate (đã đủ hết), lấy dòng cuối cùng để xử lý fallback
            if (!candidateLine && productLines.length > 0) candidateLine = productLines[productLines.length - 1];

            // 🛑 CHECK 1: LIMIT
            if (totalDemand === 0) {
                safePlaySound(this.env, 'error');
                alert(`⚠️ CHẶN NGOÀI KẾ HOẠCH!\n\nSản phẩm: ${product.display_name}`);
                return;
            }
            if (totalDone >= totalDemand) {
                safePlaySound(this.env, 'error');
                alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n\nSản phẩm: ${product.display_name}\nTiến độ: ${totalDone}/${totalDemand}`);
                return;
            }

            // 🌍 CHECK 2: SERVER LOCATION
            try {
                const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                if (result && result.allow === false) {
                    safePlaySound(this.env, 'error');
                    safeNotify(this.env, result.message, 'danger');
                    alert(`⛔ SAI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                    return;
                }
            } catch (e) {
                alert("Lỗi kết nối kiểm tra vị trí!");
                return;
            }

            // 🚀 CHECK 3: SMART MOVE & UPDATE
            if (candidateLine && currentLocId) {
                const lineLocId = extractId(candidateLine.location_id);
                // Nếu khác vị trí -> Thực hiện chuyển kho
                if (lineLocId !== currentLocId) {
                    console.log(`✅ [HLV] Smart Move Triggered`);
                    
                    try {
                        this.isSaving = true; // 🔴 BẬT CỜ CHẶN F5
                        safeNotify(this.env, "💾 Đang đồng bộ dữ liệu... ĐỪNG F5!", 'warning');

                        // 1. Update RAM (Để UI mượt)
                        candidateLine.qty_done += 1;
                        if (this.location) candidateLine.location_id = this.location;
                        this.trigger('update'); 

                        // 2. Lưu xuống DB (Dùng Save để đảm bảo cấu trúc Picking được cập nhật)
                        await this.save();
                        
                        safeNotify(this.env, "✅ Đã lưu thành công!", 'success');
                        this.isSaving = false; // 🟢 TẮT CỜ CHẶN F5
                        
                        return; // Done
                    } catch (e) {
                        this.isSaving = false;
                        console.error("Smart Move Error:", e);
                        alert("Lỗi khi lưu dữ liệu: " + e.message);
                    }
                }
            }
        }

        // =================================================================
        // FALLBACK NORMAL SCAN
        // =================================================================
        await super.processBarcode(...arguments);

        // Auto Save cho trường hợp thường
        try {
             this.isSaving = true; // 🔴 BẬT CỜ
             const updatedProduct = await this._identifyProductSafe(barcode);
             if (updatedProduct && this.currentState.lines) {
                 const line = this.currentState.lines.find(l => extractId(l.product_id) === updatedProduct.id && l.qty_done <= getLineDemand(l));
                 if (line) {
                     if (line.id && typeof line.id === 'number') {
                         await this.orm.write("stock.move.line", [line.id], { "qty_done": line.qty_done });
                     } else {
                         await this.save();
                     }
                 }
             }
             this.isSaving = false; // 🟢 TẮT CỜ
        } catch(e) {
            this.isSaving = false;
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