/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: LƯU DB & HIỂN THỊ
// =============================================================================

/**
 * Hàm ghi đè dữ liệu xuống DB (Bỏ qua web_save để tránh lỗi 500)
 */
async function forceSaveLine(orm, line) {
    // Chỉ write được nếu dòng đó đã có ID thật trong DB
    if (!line || !line.id || typeof line.id !== 'number') {
        return false; // Trả về false để báo hiệu cần dùng save() tổng
    }
    try {
        // Dùng 'write' nhẹ và nhanh hơn 'web_save'
        await orm.write("stock.move.line", [line.id], { 
            "qty_done": line.qty_done 
        });
        return true;
    } catch (e) {
        console.error("❌ Write Error:", e);
        return false;
    }
}

function formatStockResult(quants) {
    if (!quants || quants.length === 0) return "Hết hàng";
    const stockMap = {};
    quants.forEach(q => {
        const locName = q.location_id ? q.location_id[1] : ""; 
        const match = locName.match(/\b(TSN|KBC|KHD)\b/i);
        const key = match ? match[1].toUpperCase() : "KHÁC"; 
        if (!stockMap[key]) stockMap[key] = 0;
        stockMap[key] += q.quantity;
    });
    return Object.keys(stockMap).map(k => `${k}: ${stockMap[k]}`).join(" | ");
}

/**
 * Hàm vẽ lại Inline Stock (Chạy mỗi khi DOM thay đổi)
 */
async function renderInlineStock(lineEl, orm) {
    const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
    if (!codeEl) return;
    
    // Đánh dấu đã xử lý để tránh gọi API lặp lại cho cùng 1 element
    if (lineEl.dataset.hlvStockLoaded === "true") return;
    
    const defaultCode = codeEl.textContent.trim();
    if (!defaultCode) return;

    // Set cờ đang load
    lineEl.dataset.hlvStockLoaded = "true";

    try {
        // Lấy số lượng
        const domain = [['product_id.default_code', '=', defaultCode], ['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        const textDisplay = formatStockResult(quants);

        // Tìm vị trí chèn (Sau số lượng)
        const qtyDiv = lineEl.querySelector('.o_barcode_scanner_qty');
        if (qtyDiv && !qtyDiv.parentElement.querySelector(".hlv-inline-stock")) {
            let badge = document.createElement("div"); 
            badge.className = "hlv-inline-stock";
            badge.style.cssText = `font-size: 11px; color: #004085; background-color: #cce5ff; padding: 2px 6px; border-radius: 4px; margin-top: 5px; font-weight: bold; width: fit-content;`;
            badge.textContent = `📦 ${textDisplay}`;
            qtyDiv.parentElement.appendChild(badge);
        }
        
        // Check đỏ nếu đủ hàng
        checkOverflow(lineEl);
    } catch(e) { 
        lineEl.dataset.hlvStockLoaded = "false"; // Retry nếu lỗi
    }
}

function checkOverflow(lineEl) {
    const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
    if (!qtyEl) return;
    const parts = (qtyEl.innerText || "").split("/");
    if (parts.length < 2) return;
    const done = parseFloat(parts[0]);
    const demand = parseFloat(parts[1]);
    if (demand > 0 && done >= demand) {
        qtyEl.style.color = "#d9534f";
        qtyEl.style.fontWeight = "bold";
    }
}

// =============================================================================
// LOGIC CHÍNH
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        this._startObserver();
    },

    _startObserver() {
        // Observer để render Inline Stock bất chấp Odoo render lại
        const observer = new MutationObserver(() => {
            document.querySelectorAll(".o_barcode_line").forEach(line => renderInlineStock(line, this.orm));
        });
        const wait = setInterval(() => {
            if (document.body) {
                observer.observe(document.body, { childList: true, subtree: true });
                clearInterval(wait);
            }
        }, 500);
    },

    async processBarcode(barcode) {
        // 0. Bỏ qua lệnh hệ thống
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // 1. Xác định Product & Context Check
        const product = await this._identifyProductSafe(barcode);
        
        let sourceLocId = this.location ? this.location.id : (this.record.location_id ? (Array.isArray(this.record.location_id) ? this.record.location_id[0] : this.record.location_id) : null);
        let locName = (this.location?.display_name || this.record?.display_name || "");
        let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

        // =================================================================
        // BƯỚC 1: CHECK VỊ TRÍ (QUAN TRỌNG NHẤT)
        // =================================================================
        try {
            // Gọi Python: check_barcode_availability
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId]);
            
            // Nếu Python trả về allow: False => CHẶN TUYỆT ĐỐI
            if (result && result.allow === false) {
                if (this.env.services.notification) {
                    // Hiển thị thông báo "Không có hàng..."
                    this.env.services.notification.add(result.message || "Vị trí không hợp lệ!", { type: 'danger' });
                }
                if (this.env.services.sound) this.env.services.sound.play('error');
                
                return; // <--- DỪNG TẠI ĐÂY (Không chạy super, không Write DB)
            }
            
            // Nếu có cảnh báo nhẹ (allow: true nhưng vẫn muốn nhắc)
            if (result && result.message) {
                this.env.services.notification.add(result.message, { type: 'warning' });
            }

        } catch (e) {
            console.warn("⚠️ Skip Check due to Error:", e);
            // Nếu lỗi mạng/server thì tùy bạn: Cho qua hay chặn? Ở đây tôi cho qua để không treo app.
        }

        // =================================================================
        // BƯỚC 2: CẬP NHẬT GIAO DIỆN (RAM)
        // =================================================================
        // Chỉ chạy xuống đây nếu Bước 1 đã OK
        await super.processBarcode(...arguments);

        // =================================================================
        // BƯỚC 3: AUTO SAVE / WRITE (DB)
        // =================================================================
        try {
            // Lấy lại line vừa được update
            const updatedProduct = await this._identifyProductSafe(barcode);
            if (updatedProduct && this.currentState.lines) {
                const line = this.currentState.lines.find(l => l.product_id.id === updatedProduct.id);
                
                if (line) {
                    // Thử Write trực tiếp (Nhanh)
                    const success = await forceSaveLine(this.orm, line);
                    
                    if (!success) {
                        // Nếu Write thất bại (do line mới chưa có ID), gọi Save tổng
                        // console.log("💾 Saving Picking (New Line)...");
                        await this.save();
                    } else {
                        // console.log("✅ Auto Write Success");
                    }
                }
            }
        } catch (err) {
            console.error("❌ Auto Save Failed:", err);
        }
    },

    async _identifyProductSafe(barcode) {
        let product = null;
        if (this.cache.products) product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        if (!product && this.currentState.lines) {
             const line = this.currentState.lines.find(l => l.product_id && (l.product_id.barcode === barcode || l.product_id.default_code === barcode));
             if (line) product = line.product_id;
        }
        return product;
    }
});