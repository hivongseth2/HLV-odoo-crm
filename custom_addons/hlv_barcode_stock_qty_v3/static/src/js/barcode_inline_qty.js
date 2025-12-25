/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// PHẦN 1: CUSTOM AUTO SAVE (GIẢ LẬP WEB_SAVE NHƯ FETCH API)
// =============================================================================

async function forceSaveLine(orm, line) {
    // Chỉ save được nếu line đã có ID thật trong database (là số, không phải chuỗi ảo 'virtual_...')
    if (!line || !line.id || typeof line.id !== 'number') {
        // console.log("⚠️ Line chưa có ID thật, gọi hàm save() tổng của Picking");
        return false; 
    }

    try {
        // console.log(`💾 Đang Force Save Line ID: ${line.id}, Qty: ${line.qty_done}`);
        
        // Gọi chính xác method web_save như trong Network Tab bạn gửi
        await orm.call("stock.move.line", "web_save", [
            [line.id], 
            { "qty_done": line.qty_done }
        ]);
        
        return true;
    } catch (e) {
        console.error("❌ Force Save Error:", e);
        return false;
    }
}

// =============================================================================
// PHẦN 2: HIỂN THỊ TỒN KHO INLINE (FIX SELECTOR)
// =============================================================================

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

async function updateLineStock(lineEl, orm) {
    // 1. Tìm chính xác phần tử chứa Mã SP dựa trên HTML bạn gửi
    // HTML: <div class="o_product_ref"><span class="o_product_code">2046R</span></div>
    const codeEl = lineEl.querySelector(".o_product_code");
    if (!codeEl) return;

    const defaultCode = codeEl.textContent.trim();
    if (!defaultCode) return;

    // Đánh dấu đã xử lý để tránh gọi API liên tục, NHƯNG nếu Odoo render lại mất badge thì phải làm lại
    if (lineEl.querySelector(".hlv-inline-stock")) return; 

    try {
        // console.log("🔍 Đang lấy tồn kho cho:", defaultCode);
        const domain = [['product_id.default_code', '=', defaultCode], ['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        const textDisplay = formatStockResult(quants);

        // Chèn vào UI
        // Tìm chỗ hiển thị số lượng: <div name="quantity">
        const qtyDiv = lineEl.querySelector('div[name="quantity"]');
        
        if (qtyDiv) {
            let badge = document.createElement("div"); 
            badge.className = "hlv-inline-stock";
            badge.style.fontSize = "11px";
            badge.style.color = "#0056b3"; // Xanh đậm dễ đọc
            badge.style.backgroundColor = "#e7f1ff";
            badge.style.padding = "2px 6px";
            badge.style.borderRadius = "4px";
            badge.style.marginTop = "4px";
            badge.style.fontWeight = "bold";
            badge.style.width = "fit-content";
            badge.textContent = `📦 ${textDisplay}`;
            
            qtyDiv.appendChild(badge);
        }

        // Check warning
        checkAndHighlightOverflow(lineEl);

    } catch(e) { console.error(e); }
}

function checkAndHighlightOverflow(lineEl) {
    const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
    if (!qtyEl) return;
    
    const qtyText = qtyEl.textContent || "";
    const match = qtyText.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);
    if (!match) return;
    
    const qtyDone = parseFloat(match[1]) || 0;
    const demand = parseFloat(match[2]) || 0;

    if (demand > 0 && qtyDone >= demand) {
        qtyEl.style.color = "#dc3545"; // Đỏ
        qtyEl.style.fontWeight = "bold";
    }
}

// =============================================================================
// MAIN LOGIC
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        this._setupObserver();
    },

    _setupObserver() {
        // MutationObserver để bắt việc Odoo vẽ lại giao diện
        const observer = new MutationObserver((mutations) => {
            // Mỗi khi DOM thay đổi, tìm tất cả các dòng barcode và check xem đã có inline stock chưa
            const lines = document.querySelectorAll(".o_barcode_line");
            lines.forEach(line => updateLineStock(line, this.orm));
        });

        // Chờ body sẵn sàng
        const waitLoop = setInterval(() => {
            if (document.body) {
                observer.observe(document.body, { childList: true, subtree: true });
                clearInterval(waitLoop);
                // Chạy thủ công 1 lần đầu
                document.querySelectorAll(".o_barcode_line").forEach(line => updateLineStock(line, this.orm));
            }
        }, 500);
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        const product = await this._identifyProductSafe(barcode);
        
        // --- 1. CHECK SỐ LƯỢNG (CLIENT) ---
        if (product) {
            const line = this.currentState.lines.find(l => l.product_id.id === product.id);
            if (line) {
                const done = parseFloat(line.qty_done || 0);
                const demand = parseFloat(line.product_uom_qty || 0);
                if (demand > 0 && done >= demand) {
                    this.env.services.notification.add(`⚠️ Đủ số lượng rồi! (${done}/${demand})`, { type: 'danger' });
                    this.env.services.sound.play('error');
                    return;
                }
            }
        }

        // --- 2. CHECK TỒN KHO & VỊ TRÍ (SERVER) ---
        let sourceLocId = this.location ? this.location.id : (this.record.location_id ? (Array.isArray(this.record.location_id) ? this.record.location_id[0] : this.record.location_id) : null);
        let locName = (this.location?.display_name || this.record?.display_name || "");
        let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

        try {
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId]);
            if (result && result.allow === false) {
                this.env.services.notification.add(result.message || "Không đúng vị trí!", { type: 'danger' });
                this.env.services.sound.play('error');
                return;
            }
        } catch (e) { console.warn("Check skip:", e); }

        // --- 3. GHI NHẬN VÀO RAM (SUPER) ---
        await super.processBarcode(...arguments);

        // --- 4. HARDCORE SAVE (GỌI WEB_SAVE TRỰC TIẾP) ---
        // Tìm lại dòng vừa được cập nhật để lấy ID thật
        try {
            // Lấy lại product lần nữa (vì dòng có thể vừa được tạo ra)
            const updatedProduct = await this._identifyProductSafe(barcode);
            if (updatedProduct) {
                const updatedLine = this.currentState.lines.find(l => l.product_id.id === updatedProduct.id);
                
                if (updatedLine) {
                    // Thử gọi web_save trực tiếp vào dòng đó
                    const success = await forceSaveLine(this.orm, updatedLine);
                    
                    if (!success) {
                        // Nếu không có ID thật (dòng mới tạo), buộc phải dùng save() của Picking
                        // console.log("🔄 Fallback sang Save Picking...");
                        await this.save();
                    } else {
                         // console.log("✅ Đã lưu dòng thành công!");
                    }
                }
            }
        } catch (err) {
            console.error("Save Error:", err);
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