/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: UI & HIỂN THỊ
// =============================================================================

function showNotification(env, message, type = 'danger') {
    try {
        if (env && env.services && env.services.notification) {
            env.services.notification.add(message, { 
                type: type, 
                sticky: type === 'danger', 
                title: type === 'danger' ? "CẢNH BÁO" : "Thông báo" 
            });
        }
    } catch (e) { console.error(e); }
}

function playSound(env, type='error') {
    try {
        if (env && env.services && env.services.sound) {
            env.services.sound.play(type);
        } else {
             new Audio('/web/static/src/audio/error.mp3').play().catch(()=>{});
        }
    } catch(e) {}
}

function insertInline(lineEl, text) {
    // Dựa vào HTML bạn gửi: <div name="quantity">...</div>
    const qtyDiv = lineEl.querySelector('div[name="quantity"]');
    if (!qtyDiv) return;

    // Kiểm tra xem đã chèn chưa để tránh trùng lặp
    let badge = qtyDiv.querySelector(".hlv-inline-stock");
    if (!badge) {
        badge = document.createElement("div"); // Dùng div để xuống dòng hoặc span để cùng dòng
        badge.className = "hlv-inline-stock";
        
        // CSS cho đẹp và nổi bật
        badge.style.fontSize = "11px";
        badge.style.color = "#004085"; 
        badge.style.backgroundColor = "#cce5ff";
        badge.style.padding = "2px 5px";
        badge.style.borderRadius = "4px";
        badge.style.marginTop = "2px";
        badge.style.fontWeight = "bold";
        badge.style.display = "inline-block"; // Hiển thị gọn gàng
        
        qtyDiv.appendChild(badge);
    }
    badge.textContent = `📦 ${text}`;
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
    // Kết quả: "TSN: 90 | KBC: 5"
    return Object.keys(stockMap).map(k => `${k}: ${stockMap[k]}`).join(" | ");
}

async function annotateLine(lineEl, orm) {
    // Cờ đánh dấu đã xử lý để không gọi API nhiều lần cho 1 dòng
    if (lineEl.__hlv_done__) return;
    lineEl.__hlv_done__ = true;
    
    // 1. LẤY MÃ SẢN PHẨM CHUẨN (Dựa vào HTML data-barcode)
    // HTML của bạn: <div class="o_barcode_line..." data-barcode="2046R">
    let defaultCode = lineEl.dataset.barcode;

    // Fallback: Nếu không có data-barcode thì tìm trong class o_product_code
    if (!defaultCode) {
        const codeEl = lineEl.querySelector(".o_product_code");
        if (codeEl) defaultCode = codeEl.textContent.trim();
    }

    if (!defaultCode) return;

    try {
        // Gọi search_read để lấy tồn kho
        const domain = [['product_id.default_code', '=', defaultCode],['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        const textDisplay = formatStockResult(quants);
        insertInline(lineEl, textDisplay);
        
        // Check màu đỏ nếu số lượng quét >= yêu cầu
        checkAndHighlightOverflow(lineEl);
    } catch(e) { console.error("[HLV] Lỗi lấy tồn kho:", e); }
}

function checkAndHighlightOverflow(lineEl) {
    try {
        const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
        if (!qtyEl) return;
        const qtyText = qtyEl.textContent || "";
        const match = qtyText.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);
        if (!match) return;
        const qtyDone = parseFloat(match[1]) || 0;
        const demand = parseFloat(match[2]) || 0;

        if (demand > 0 && qtyDone >= demand) {
            qtyEl.style.color = "#d9534f"; // Đỏ
            qtyEl.style.fontWeight = "bold";
        }
    } catch (e) {}
}

function setupObserver(orm) {
    // Quét ngay những dòng đang có trên màn hình
    document.querySelectorAll(".o_barcode_line").forEach(el => annotateLine(el, orm));

    // Lắng nghe thay đổi khi quét tiếp
    if (window.__hlv_observer__) return;
    const obs = new MutationObserver((mutations) => {
        mutations.forEach((m) => {
            m.addedNodes.forEach((node) => {
                if (node instanceof HTMLElement) {
                    if (node.matches(".o_barcode_line")) annotateLine(node, orm);
                    node.querySelectorAll(".o_barcode_line").forEach(el => annotateLine(el, orm));
                }
            });
            if (m.type === 'characterData' || m.type === 'childList') {
                const target = m.target.parentElement;
                if (target && target.closest('.o_barcode_line')) {
                    checkAndHighlightOverflow(target.closest('.o_barcode_line'));
                }
            }
        });
    });
    
    if (document.body) {
        obs.observe(document.body, { childList: true, subtree: true, characterData: true });
        window.__hlv_observer__ = obs;
    }
}

// =============================================================================
// MAIN LOGIC
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("✅ [HLV] Fix Scan Logic Ready");
        // Delay để DOM load xong mới gắn observer
        setTimeout(() => setupObserver(this.orm), 1500);
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        const product = await this._identifyProductSafe(barcode);
        
        // --- 1. CHECK SỐ LƯỢNG (LIMIT) ---
        if (product) {
            const lines = this.currentState.lines || [];
            const matchedLine = lines.find(l => l.product_id.id === product.id);
            if (matchedLine) {
                const done = parseFloat(matchedLine.qty_done || 0);
                const demand = parseFloat(matchedLine.product_uom_qty || 0);
                if (demand > 0 && done >= demand) {
                    showNotification(this.env, `⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n(${done}/${demand})`, 'danger');
                    playSound(this.env, 'error');
                    return; // DỪNG NGAY
                }
            }
        }

        // --- 2. CHECK VỊ TRÍ & TỒN KHO ---
        let sourceLocId = null;
        let whPrefix = null;
        if (this.location) sourceLocId = this.location.id;
        if (!sourceLocId && this.record && this.record.location_id) sourceLocId = typeof(this.record.location_id) === 'object' ? this.record.location_id[0] : this.record.location_id;
        
        if (this.location && this.location.display_name) {
            const m = this.location.display_name.match(/\b(TSN|KBC|KHD)\b/i);
            if (m) whPrefix = m[1].toUpperCase();
        } else if (this.record && this.record.display_name) {
             const m = this.record.display_name.match(/\b(TSN|KBC|KHD)\b/i);
             if (m) whPrefix = m[1].toUpperCase();
        }

        try {
            // Gọi Python check
            const result = await this.orm.call(
                "stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId] 
            );
            
            // XỬ LÝ KẾT QUẢ TRẢ VỀ TỪ PYTHON
            if (result) {
                // Nếu allow = false -> Chặn quét
                if (result.allow === false) {
                    // Hiển thị message từ JSON (VD: "⛔ KHÔNG CÓ HÀNG...")
                    showNotification(this.env, result.message || "Không được phép quét!", 'danger');
                    playSound(this.env, 'error');
                    
                    return; // <--- QUAN TRỌNG: Dừng hàm tại đây, không cho chạy super.processBarcode
                } 
                
                // Nếu allow = true nhưng vẫn có message (ví dụ cảnh báo nhẹ)
                if (result.message) {
                    showNotification(this.env, result.message, 'warning');
                }
            }

        } catch (e) { 
            console.warn("[HLV] Check Error:", e); 
        }

        // --- 3. NẾU QUA ĐƯỢC HẾT CÁC BƯỚC TRÊN THÌ MỚI GỌI SUPER (TĂNG SỐ LƯỢNG) ---
        await super.processBarcode(...arguments);

        // --- 4. LƯU NGAY LẬP TỨC (AUTO SAVE) ---
        try {
            await this.save(); 
            // Không hiện thông báo gì thêm để đỡ ồn ào
        } catch (err) {
            console.error("Save Error:", err);
        }
    },

    async _identifyProductSafe(barcode) {
        let product = null;
        if (this.cache && this.cache.products) {
            product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        }
        if (!product && this.currentState && this.currentState.lines) {
             const line = this.currentState.lines.find(l => 
                l.product_id && (l.product_id.barcode === barcode || l.product_id.default_code === barcode)
             );
             if (line) product = line.product_id;
        }
        return product;
    }
});