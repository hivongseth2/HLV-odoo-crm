/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: AN TOÀN TUYỆT ĐỐI (SAFE HELPERS)
// =============================================================================

/**
 * Hàm thông báo an toàn: Nếu Odoo Services lỗi thì dùng Alert của trình duyệt
 * Đảm bảo người dùng luôn thấy thông báo
 */
function safeNotify(env, message, type = 'warning') {
    try {
        if (env && env.services && env.services.notification) {
            env.services.notification.add(message, { type: type, sticky: type === 'danger' });
        } else {
            console.warn("[HLV Fallback Notify]", message);
            // Nếu là lỗi chặn (danger), bắt buộc hiện Popup Alert
            if (type === 'danger') {
                alert(message);
            }
        }
    } catch (e) {
        // Fallback cuối cùng nếu mọi thứ đều lỗi
        if (type === 'danger') alert(message);
    }
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

/**
 * Hàm hiển thị Inline Stock (Đã sửa selector theo hình ảnh bạn gửi)
 */
async function renderInlineStock(lineEl, orm) {
    // 1. Lấy Code: Ưu tiên lấy từ attribute data-barcode (Chính xác nhất)
    let defaultCode = lineEl.dataset.barcode;
    
    // Nếu không có dataset, tìm trong giao diện (class o_product_code trong hình bạn gửi)
    if (!defaultCode) {
        const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
        if (codeEl) defaultCode = codeEl.textContent.trim();
    }

    if (!defaultCode) return;

    // Check xem đã vẽ chưa
    if (lineEl.querySelector(".hlv-inline-stock")) return;

    try {
        // Lấy tồn kho
        const domain = [['product_id.default_code', '=', defaultCode], ['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        // Format hiển thị
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

        // Vẽ UI: Tìm thẻ bao quanh số lượng để chèn vào
        // Trong hình bạn gửi: thẻ chứa số lượng có class 'o_barcode_scanner_qty' nằm trong div[name="quantity"]
        const qtyContainer = lineEl.querySelector('div[name="quantity"]') || lineEl.querySelector('.o_barcode_scanner_qty')?.parentElement;

        if (qtyContainer) {
            let badge = document.createElement("div"); 
            badge.className = "hlv-inline-stock";
            badge.style.cssText = `
                font-size: 11px; 
                color: #004085; 
                background-color: #cce5ff; 
                padding: 2px 6px; 
                border-radius: 4px; 
                margin-top: 4px; 
                font-weight: bold; 
                width: fit-content; 
                display: block; 
                border: 1px solid #b8daff;
            `;
            badge.textContent = `📦 ${textDisplay}`;
            qtyContainer.appendChild(badge);
        }
        
        // Check Overflow (Đổi màu đỏ nếu đủ)
        const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
        if (qtyEl) {
            const parts = qtyEl.innerText.split("/");
            if (parts.length >= 2) {
                const done = parseFloat(parts[0]);
                const demand = parseFloat(parts[1]);
                if (demand > 0 && done >= demand) {
                    qtyEl.style.color = "#d9534f";
                    qtyEl.style.fontWeight = "bold";
                }
            }
        }
    } catch(e) { 
        console.error("Inline Error:", e);
    }
}

// =============================================================================
// MAIN LOGIC
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] Barcode Patched - Safe Mode");
        
        // Observer vẽ Inline Stock
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

        // 1. Chuẩn bị params
        let sourceLocId = this.location ? this.location.id : (this.record.location_id ? (Array.isArray(this.record.location_id) ? this.record.location_id[0] : this.record.location_id) : null);
        let locName = (this.location?.display_name || this.record?.display_name || "");
        let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

        // =================================================================
        // BƯỚC 1: CHECK VỊ TRÍ (CÓ TRY/CATCH AN TOÀN)
        // =================================================================
        try {
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId]);
            
            console.log("📩 Check Result:", result);

            // NẾU BỊ CHẶN (Allow = False)
            if (result && result.allow === false) {
                console.error("⛔ [HLV] BLOCKED!");
                
                // Gọi Safe Notify (Không bao giờ crash)
                safePlaySound(this.env, 'error');
                safeNotify(this.env, result.message || "Không có hàng tại vị trí này!", 'danger');
                
                // QUAN TRỌNG: RETURN NGAY ĐỂ NGĂN QUÉT
                return; 
            }
            
            // Warning nhẹ
            if (result && result.message) {
                safeNotify(this.env, result.message, 'warning');
            }

        } catch (e) {
            console.error("❌ Check Error:", e);
            // Nếu code check bị lỗi, ta chọn AN TOÀN là chặn lại và báo lỗi, thay vì cho quét bừa
            alert("Lỗi kiểm tra tồn kho: " + e.message);
            return; 
        }

        // =================================================================
        // BƯỚC 2: ODOO XỬ LÝ QUÉT (CHỈ CHẠY NẾU BƯỚC 1 KHÔNG RETURN)
        // =================================================================
        await super.processBarcode(...arguments);

        // =================================================================
        // BƯỚC 3: AUTO SAVE (WRITE)
        // =================================================================
        try {
            // Tìm product ID từ cache
            let product = null;
            if (this.cache.products) product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
            
            if (product && this.currentState.lines) {
                const line = this.currentState.lines.find(l => l.product_id.id === product.id);
                if (line) {
                    if (line.id && typeof line.id === 'number') {
                        // Write thẳng xuống DB
                        await this.orm.write("stock.move.line", [line.id], { "qty_done": line.qty_done });
                    } else {
                        // Line mới -> Gọi Save tổng
                        await this.save();
                    }
                }
            }
        } catch (err) {
            console.error("Save Error:", err);
        }
    }
});