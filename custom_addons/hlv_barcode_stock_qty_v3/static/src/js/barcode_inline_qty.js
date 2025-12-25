/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: UI & HIỂN THỊ (INLINE STOCK)
// =============================================================================

function showNotification(env, message, type = 'danger') {
    try {
        if (env && env.services && env.services.notification) {
            env.services.notification.add(message, { 
                type: type, 
                sticky: type === 'danger', 
                title: type === 'danger' ? "CẢNH BÁO" : "Thông báo" 
            });
        } else {
            // Fallback nếu không gọi được service
            alert(message);
        }
    } catch (e) { console.error(e); }
}

function playSound(env, type='error') {
    try {
        if (env && env.services && env.services.sound) {
            env.services.sound.play(type);
        } else {
             const audio = new Audio('/custom_barcode_scan_redirect/static/src/sound/error.mp3');
             audio.play().catch(()=>{});
        }
    } catch(e) {}
}

function insertInline(lineEl, text) {
    // Tìm vị trí hiển thị số lượng
    const qtyDiv = lineEl.querySelector('div[name="quantity"]') || lineEl.querySelector('.o_barcode_scanner_qty')?.parentElement;
    if (!qtyDiv) return;

    let badge = qtyDiv.querySelector(".hlv-inline-stock");
    if (!badge) {
        badge = document.createElement("div"); 
        badge.className = "hlv-inline-stock";
        
        // Style Inline badge
        badge.style.fontSize = "11px";
        badge.style.color = "#004085"; 
        badge.style.backgroundColor = "#cce5ff";
        badge.style.padding = "2px 5px";
        badge.style.borderRadius = "4px";
        badge.style.marginTop = "4px";
        badge.style.fontWeight = "bold";
        badge.style.display = "inline-block";
        badge.style.width = "100%"; // Xuống dòng cho gọn
        
        qtyDiv.appendChild(badge);
    }
    badge.textContent = `📦 ${text}`;
}

// Format kết quả tồn kho: "TSN: 5 | KBC: 3"
function formatStockResult(quants) {
    if (!quants || quants.length === 0) return "Hết hàng";
    const stockMap = {};
    quants.forEach(q => {
        const locName = q.location_id ? q.location_id[1] : ""; 
        const match = locName.match(/\b(TSN|KBC|KHD)\b/i); // Detect kho
        const key = match ? match[1].toUpperCase() : "KHÁC"; 
        if (!stockMap[key]) stockMap[key] = 0;
        stockMap[key] += q.quantity;
    });
    return Object.keys(stockMap).map(k => `${k}: ${stockMap[k]}`).join(" | ");
}

// Logic hiển thị tồn kho từng dòng
async function annotateLine(lineEl, orm) {
    if (lineEl.__hlv_done__) return;
    lineEl.__hlv_done__ = true;
    
    // 1. Lấy mã sản phẩm (Ưu tiên lấy từ dataset do Odoo render)
    let defaultCode = lineEl.dataset.barcode; // Odoo thường gắn barcode vào đây
    if (!defaultCode) {
        // Fallback: Tìm trong UI
        const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
        if (codeEl) defaultCode = codeEl.textContent.trim();
    }
    
    // Nếu vẫn không có code thì chịu
    if (!defaultCode) return;

    try {
        // Gọi search_read trực tiếp, không cần qua hàm Python trung gian để lấy inline
        // Lấy hàng ở location nội bộ
        const domain = [['product_id.default_code', '=', defaultCode], ['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        const textDisplay = formatStockResult(quants);
        insertInline(lineEl, textDisplay);
        
        // Check màu đỏ nếu đủ số lượng
        checkAndHighlightOverflow(lineEl);
    } catch(e) { console.error("[HLV] Lỗi Inline Stock:", e); }
}

function checkAndHighlightOverflow(lineEl) {
    try {
        const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
        if (!qtyEl) return;
        
        // Parse "1/5"
        const qtyText = qtyEl.textContent || "";
        const match = qtyText.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);
        if (!match) return;
        
        const qtyDone = parseFloat(match[1]) || 0;
        const demand = parseFloat(match[2]) || 0;

        if (demand > 0 && qtyDone >= demand) {
            qtyEl.style.color = "#d9534f"; // Đỏ
            qtyEl.style.fontWeight = "bold";
            // Thêm icon cảnh báo nếu chưa có
            if (!qtyEl.parentElement.querySelector(".hlv-warning-icon")) {
                const icon = document.createElement("span");
                icon.className = "hlv-warning-icon";
                icon.textContent = " ✅";
                qtyEl.parentElement.appendChild(icon);
            }
        }
    } catch (e) {}
}

function setupObserver(orm) {
    // Chạy lần đầu cho các dòng đã có
    document.querySelectorAll(".o_barcode_line").forEach(el => annotateLine(el, orm));

    if (window.__hlv_observer__) return;
    
    // Theo dõi DOM thay đổi để gắn inline cho dòng mới quét
    const obs = new MutationObserver((mutations) => {
        mutations.forEach((m) => {
            m.addedNodes.forEach((node) => {
                if (node instanceof HTMLElement) {
                    if (node.matches(".o_barcode_line")) annotateLine(node, orm);
                    node.querySelectorAll(".o_barcode_line").forEach(el => annotateLine(el, orm));
                }
            });
            // Update lại màu sắc khi số lượng thay đổi
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
// MAIN LOGIC: BARCODE MODEL PATCH
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("✅ [HLV] Barcode Logic Active");
        // Đợi 1.5s để DOM ổn định rồi mới gắn Observer hiển thị Inline
        setTimeout(() => setupObserver(this.orm), 1500);
    },

    async processBarcode(barcode) {
        // Bỏ qua các lệnh hệ thống Odoo
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // 1. Xác định sản phẩm (Tìm trong cache nội bộ của Barcode App)
        const product = await this._identifyProductSafe(barcode);
        
        // --- 2. CHECK SỐ LƯỢNG (CLIENT SIDE) ---
        // Logic: Nếu dòng đó đã quét đủ thì chặn luôn, không cần hỏi server
        if (product) {
            const lines = this.currentState.lines || [];
            const matchedLine = lines.find(l => l.product_id.id === product.id);
            if (matchedLine) {
                const done = parseFloat(matchedLine.qty_done || 0);
                const demand = parseFloat(matchedLine.product_uom_qty || 0);
                if (demand > 0 && done >= demand) {
                    showNotification(this.env, `⚠️ Sản phẩm này đã đủ số lượng!\n(${done}/${demand})`, 'danger');
                    playSound(this.env, 'error');
                    return; // Dừng tại đây
                }
            }
        }

        // --- 3. CHECK TỒN KHO & VỊ TRÍ (SERVER SIDE) ---
        // Lấy ID vị trí nguồn hiện tại
        let sourceLocId = null;
        let whPrefix = null;
        
        // Lấy location ID từ context barcode
        if (this.location) sourceLocId = this.location.id;
        // Fallback lấy từ record picking
        if (!sourceLocId && this.record && this.record.location_id) {
            sourceLocId = Array.isArray(this.record.location_id) ? this.record.location_id[0] : this.record.location_id;
        }
        
        // Detect tên kho (TSN, KBC...) để truyền vào hàm check python
        const locName = (this.location && this.location.display_name) || (this.record && this.record.display_name) || "";
        const m = locName.match(/\b(TSN|KBC|KHD)\b/i);
        if (m) whPrefix = m[1].toUpperCase();

        try {
            // Gọi hàm check_barcode_availability từ backend
            // Hàm này trả về { allow: boolean, message: string }
            const result = await this.orm.call(
                "stock.quant", 
                "check_barcode_availability", 
                [barcode, whPrefix, sourceLocId] 
            );
            
            if (result) {
                // Nếu backend trả về Allow = False => Chặn, hiện lỗi
                if (result.allow === false) {
                    // Đây chính là chỗ hiện thông báo "Bạn đang quét... không có hàng..."
                    showNotification(this.env, result.message || "Không có hàng tại vị trí này!", 'danger');
                    playSound(this.env, 'error');
                    return; // Dừng, không cho super.processBarcode chạy
                } 
                
                // Nếu Allow = True nhưng có message (cảnh báo nhẹ)
                if (result.message) {
                    showNotification(this.env, result.message, 'warning');
                }
            }
        } catch (e) { 
            console.warn("[HLV] Skip Check (Server Error):", e); 
            // Nếu lỗi server (ví dụ mất mạng), có thể cho phép quét tiếp hoặc chặn tùy bạn. 
            // Ở đây tôi cho qua để không làm gián đoạn vận hành.
        }

        // --- 4. GHI NHẬN QUÉT (SUPER) ---
        // Nếu các bước trên OK hết thì mới gọi logic gốc của Odoo
        await super.processBarcode(...arguments);

        // --- 5. TỰ ĐỘNG LƯU (AUTO SAVE) ---
        try {
            await this.save(); 
        } catch (err) {
            console.error("Save Error:", err);
        }
    },

    // Hàm an toàn để tìm product từ barcode (tránh lỗi crash app)
    async _identifyProductSafe(barcode) {
        let product = null;
        // Tìm trong cache (nhanh nhất)
        if (this.cache && this.cache.products) {
            product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        }
        // Tìm trong các dòng đang có trên màn hình
        if (!product && this.currentState && this.currentState.lines) {
             const line = this.currentState.lines.find(l => 
                l.product_id && (l.product_id.barcode === barcode || l.product_id.default_code === barcode)
             );
             if (line) product = line.product_id;
        }
        return product;
    }
});