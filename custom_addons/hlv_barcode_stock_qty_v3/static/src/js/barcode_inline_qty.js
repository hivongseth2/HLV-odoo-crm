/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: CÁC HÀM HỖ TRỢ (LƯU DB & HIỂN THỊ)
// =============================================================================

/**
 * Hàm ghi đè dữ liệu xuống DB (Dùng write thay vì web_save để tránh lỗi 500)
 */
async function forceSaveLine(orm, line) {
    // Chỉ write được nếu dòng đó đã có ID thật trong DB (ID là số)
    if (!line || !line.id || typeof line.id !== 'number') {
        return false; // Trả về false để báo hiệu cần dùng save() tổng
    }
    try {
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
 * Hàm vẽ lại Inline Stock (Bắt buộc chạy mỗi khi DOM thay đổi)
 */
async function renderInlineStock(lineEl, orm) {
    // Tìm phần tử chứa mã sản phẩm
    const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
    if (!codeEl) return;
    
    // Kiểm tra xem đã vẽ chưa để tránh lặp (Dùng class check)
    if (lineEl.querySelector(".hlv-inline-stock")) return;

    const defaultCode = codeEl.textContent.trim();
    if (!defaultCode) return;

    try {
        // Lấy số lượng
        const domain = [['product_id.default_code', '=', defaultCode], ['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        const textDisplay = formatStockResult(quants);

        // Tìm vị trí chèn: Tìm div chứa số lượng
        const qtyDiv = lineEl.querySelector('.o_barcode_scanner_qty');
        
        if (qtyDiv) {
            let badge = document.createElement("div"); 
            badge.className = "hlv-inline-stock";
            // Style cứng để đảm bảo hiển thị đẹp
            badge.style.cssText = `
                font-size: 11px; 
                color: #004085; 
                background-color: #cce5ff; 
                padding: 2px 6px; 
                border-radius: 4px; 
                margin-top: 5px; 
                font-weight: bold; 
                width: fit-content;
                display: block;
                border: 1px solid #b8daff;
            `;
            badge.textContent = `📦 ${textDisplay}`;
            
            // Chèn vào ngay sau số lượng
            if (qtyDiv.parentElement) {
                qtyDiv.parentElement.appendChild(badge);
            }
        }
        
        // Check đỏ nếu đủ hàng
        checkOverflow(lineEl);
    } catch(e) { 
        console.error("Inline Error:", e);
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
// LOGIC CHÍNH: PATCH BARCODE MODEL
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("✅ [HLV] Security Gate & Auto Save: ACTIVE");
        this._startObserver();
    },

    _startObserver() {
        // Dùng MutationObserver để vẽ lại Inline Stock bất cứ khi nào Odoo vẽ lại màn hình
        const observer = new MutationObserver(() => {
            const lines = document.querySelectorAll(".o_barcode_line");
            lines.forEach(line => renderInlineStock(line, this.orm));
        });
        
        // Đợi Body load xong thì gắn observer
        const wait = setInterval(() => {
            if (document.body) {
                observer.observe(document.body, { childList: true, subtree: true });
                clearInterval(wait);
            }
        }, 500);
    },

    async processBarcode(barcode) {
        // 0. Bỏ qua lệnh hệ thống (O-CMD)
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // 1. Xác định Product & Thông tin kho
        const product = await this._identifyProductSafe(barcode);
        
        let sourceLocId = this.location ? this.location.id : (this.record.location_id ? (Array.isArray(this.record.location_id) ? this.record.location_id[0] : this.record.location_id) : null);
        let locName = (this.location?.display_name || this.record?.display_name || "");
        let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

        // =================================================================
        // BƯỚC 1: CHECK VỊ TRÍ (CỔNG AN NINH)
        // =================================================================
        // Lưu ý: Phải dùng await để code dừng lại chờ server trả lời
        try {
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId]);
            
            // NẾU KHÔNG CÓ HÀNG (allow = false)
            if (result && result.allow === false) {
                // 1. Phát âm thanh lỗi
                if (this.env.services.sound) this.env.services.sound.play('error');
                
                // 2. Hiện thông báo chi tiết trả về từ Python
                if (this.env.services.notification) {
                    this.env.services.notification.add(result.message || "⛔ Vị trí không hợp lệ!", { 
                        type: 'danger',
                        sticky: true // Ghim lại để nhân viên đọc
                    });
                }

                // 3. QUAN TRỌNG NHẤT: RETURN NGAY LẬP TỨC
                // Lệnh này chặn không cho code chạy xuống dòng super.processBarcode bên dưới
                console.log("⛔ [HLV] Blocked scan due to unavailability.");
                return; 
            }
            
            // Nếu có cảnh báo nhẹ (allow = true nhưng có message)
            if (result && result.message) {
                this.env.services.notification.add(result.message, { type: 'warning' });
            }

        } catch (e) {
            console.warn("⚠️ Skip Check due to Error (Network/Server):", e);
            // Nếu mất mạng, ta có thể chọn chặn hoặc cho qua. Ở đây cho qua để không treo máy.
        }

        // =================================================================
        // BƯỚC 2: CẬP NHẬT GIAO DIỆN (CHỈ CHẠY KHI BƯỚC 1 OK)
        // =================================================================
        console.log("✅ Check OK -> Processing Scan...");
        await super.processBarcode(...arguments);

        // =================================================================
        // BƯỚC 3: AUTO SAVE / WRITE (DB)
        // =================================================================
        try {
            // Lấy lại line vừa được update trong RAM
            const updatedProduct = await this._identifyProductSafe(barcode);
            if (updatedProduct && this.currentState.lines) {
                const line = this.currentState.lines.find(l => l.product_id.id === updatedProduct.id);
                
                if (line) {
                    // Thử Write trực tiếp (Nhanh, không load lại trang)
                    const success = await forceSaveLine(this.orm, line);
                    
                    if (!success) {
                        // Nếu dòng mới chưa có ID thật -> Gọi Save tổng
                        // console.log("💾 New Line detected -> Full Save...");
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