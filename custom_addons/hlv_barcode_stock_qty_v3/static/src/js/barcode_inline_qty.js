/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// PHẦN 1: HELPER - LƯU DỮ LIỆU & HIỂN THỊ
// =============================================================================

/**
 * Hàm lưu cứng (Hard Save) dùng phương thức write chuẩn của ORM
 * Thay vì web_save (dễ lỗi), ta dùng write (an toàn, nhanh)
 */
async function forceSaveLine(orm, line) {
    // 1. Kiểm tra ID: Nếu là ID ảo (VD: "virtual_123") thì chưa có trong DB -> Không write được
    if (!line || !line.id || typeof line.id !== 'number') {
        // console.log("⚠️ Line mới (Virtual ID), cần gọi save() tổng");
        return false; 
    }

    try {
        // 2. Gọi lệnh write update số lượng
        // console.log(`💾 [HLV] Writing DB Line ID: ${line.id}, Qty: ${line.qty_done}`);
        await orm.write("stock.move.line", [line.id], { 
            "qty_done": line.qty_done 
        });
        return true;
    } catch (e) {
        console.error("❌ [HLV] Write Error:", e);
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
 * Hàm vẽ lại số tồn kho
 */
async function renderInlineStock(lineEl, orm) {
    // Tìm mã sản phẩm
    const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
    if (!codeEl) return;
    const defaultCode = codeEl.textContent.trim();
    if (!defaultCode) return;

    // Kiểm tra xem đã vẽ chưa? (tránh vẽ chồng lên nhau)
    const qtyDiv = lineEl.querySelector('.o_barcode_scanner_qty');
    if (!qtyDiv) return;
    
    // Nếu đã có badge rồi thì thôi, trừ khi muốn update số (ở đây ta giữ đơn giản)
    if (qtyDiv.parentElement.querySelector(".hlv-inline-stock")) return;

    try {
        // Lấy dữ liệu tồn kho
        const domain = [['product_id.default_code', '=', defaultCode], ['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        const textDisplay = formatStockResult(quants);

        // Tạo phần tử hiển thị
        let badge = document.createElement("div"); 
        badge.className = "hlv-inline-stock";
        badge.style.cssText = `
            font-size: 11px;
            color: #004085;
            background-color: #cce5ff;
            padding: 2px 6px;
            border-radius: 4px;
            margin-top: 5px;
            font-weight: bold;
            display: inline-block;
            white-space: nowrap;
        `;
        badge.textContent = `📦 ${textDisplay}`;
        
        // Chèn vào sau phần hiển thị số lượng
        if (qtyDiv.parentElement) {
            qtyDiv.parentElement.appendChild(badge);
        }

        // Check overflow (Đỏ nếu đủ hàng)
        checkOverflow(lineEl);

    } catch(e) { console.error(e); }
}

function checkOverflow(lineEl) {
    const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
    if (!qtyEl) return;
    
    const qtyText = qtyEl.innerText || "";
    // Parse "1/5"
    const parts = qtyText.split("/");
    if (parts.length < 2) return;
    
    const done = parseFloat(parts[0]);
    const demand = parseFloat(parts[1]);

    if (demand > 0 && done >= demand) {
        qtyEl.style.color = "#d9534f";
        qtyEl.style.fontWeight = "bold";
    }
}

// =============================================================================
// PHẦN 2: PATCH BARCODE MODEL
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("✅ [HLV] Barcode Logic: Active (Write Method)");
        this._startObserver();
    },

    _startObserver() {
        // Observer này sẽ chạy liên tục mỗi khi giao diện thay đổi
        // Để đảm bảo "Inline Stock" luôn hiện kể cả khi Odoo render lại dòng đó
        const observer = new MutationObserver((mutations) => {
            const lines = document.querySelectorAll(".o_barcode_line");
            lines.forEach(line => renderInlineStock(line, this.orm));
        });

        // Đợi DOM load xong
        const wait = setInterval(() => {
            if (document.body) {
                observer.observe(document.body, { childList: true, subtree: true });
                clearInterval(wait);
            }
        }, 500);
    },

    async processBarcode(barcode) {
        // 1. Logic gốc (Để Odoo xử lý logic cộng trừ số lượng trên RAM)
        await super.processBarcode(...arguments);

        // 2. Logic Check Tồn Kho (Server Side) & Cảnh báo
        // (Bạn nói phần check ok rồi nên tôi để nó chạy ngầm, quan trọng là phần Save dưới đây)
        
        // 3. AUTO SAVE (FIX LỖI RPC ERROR)
        try {
            // Tìm sản phẩm vừa quét
            const product = await this._identifyProductSafe(barcode);
            if (product) {
                // Tìm dòng (line) tương ứng trong Picking hiện tại
                const line = this.currentState.lines.find(l => l.product_id.id === product.id);
                
                if (line) {
                    // CÁCH 1: Nếu dòng này ĐÃ CÓ trong database (ID là số) -> Gọi write update thẳng
                    const success = await forceSaveLine(this.orm, line);
                    
                    // CÁCH 2: Nếu dòng này MỚI TINH (ID là chuỗi ảo) hoặc Cách 1 thất bại
                    if (!success) {
                        // console.log("🔄 Line mới, gọi Save tổng...");
                        await this.save(); // Gọi hàm save chuẩn của Odoo (lưu cả phiếu)
                    } else {
                        // console.log("✅ Đã lưu nhanh (Write)");
                    }
                    
                    // Nếu đã đủ số lượng -> Cảnh báo âm thanh
                    const done = parseFloat(line.qty_done || 0);
                    const demand = parseFloat(line.product_uom_qty || 0);
                    if (demand > 0 && done >= demand) {
                         if (this.env.services.sound) this.env.services.sound.play('error');
                         if (this.env.services.notification) {
                            this.env.services.notification.add(`⚠️ Đã đủ số lượng (${done}/${demand})`, { type: 'danger' });
                         }
                    }
                }
            }
        } catch (err) {
            console.error("❌ [HLV] Auto Save Failed:", err);
            // Fallback cuối cùng: Cố gắng save lần nữa bằng phương thức chuẩn
            try { await this.save(); } catch(e) {}
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