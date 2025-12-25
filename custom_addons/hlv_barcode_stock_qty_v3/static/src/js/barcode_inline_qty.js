/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// =============================================================================
// PHẦN 1: GIAO DIỆN & HIỂN THỊ TỒN KHO CHI TIẾT (TSN:3, KBC:4)
// =============================================================================

function insertInline(lineEl, text) {
    const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
    if (!qtyEl) return;
    
    // Tìm hoặc tạo element hiển thị tồn kho
    let badge = qtyEl.parentElement.querySelector(".hlv-inline-stock");
    if (!badge) {
        badge = document.createElement("span");
        badge.className = "hlv-inline-stock";
        // Style cho đẹp và gọn
        badge.style.marginLeft = "10px";
        badge.style.fontSize = "13px";
        badge.style.fontWeight = "bold";
        badge.style.color = "#17a2b8"; // Màu xanh dương nhạt cho dễ nhìn
        badge.style.backgroundColor = "#eef";
        badge.style.padding = "0px 4px";
        badge.style.borderRadius = "4px";
        qtyEl.parentElement.appendChild(badge);
    }
    badge.textContent = `📦 ${text}`;
}

// Hàm format số lượng: TSN: 5, KBC: 3
function formatStockResult(quants) {
    if (!quants || quants.length === 0) return "Hết hàng";
    
    // Object chứa tổng: { "TSN": 10, "KBC": 5, "KHÁC": 2 }
    const stockMap = {};

    quants.forEach(q => {
        const locName = q.location_id ? q.location_id[1] : ""; // Ví dụ: "WH/Stock/TSN/Kệ 1"
        // Regex tìm TSN, KBC, KHD...
        const match = locName.match(/\b(TSN|KBC|KHD)\b/i);
        const key = match ? match[1].toUpperCase() : "KHÁC"; 
        
        if (!stockMap[key]) stockMap[key] = 0;
        stockMap[key] += q.quantity;
    });

    // Chuyển Object thành chuỗi "TSN: 10, KBC: 5"
    const parts = Object.keys(stockMap).map(k => `${k}: ${stockMap[k]}`);
    return parts.join(" | ");
}

async function annotateLine(lineEl, orm) {
    if (lineEl.__hlv_done__) return;
    lineEl.__hlv_done__ = true;
    
    // 1. Lấy Mã sản phẩm (Default Code) từ giao diện
    let defaultCode = lineEl.querySelector(".o_product_ref")?.textContent?.trim() || "";
    if (!defaultCode || defaultCode.includes("\n")) {
         const m = (lineEl.innerText || "").match(/^[A-Z0-9._-]+/);
         if (m) defaultCode = m[0];
    }
    if (!defaultCode) return;

    try {
        // 2. Gọi trực tiếp stock.quant search_read (Không cần sửa Python)
        // Lấy tất cả quant của mã này ở kho nội bộ
        const domain = [
            ['product_id.default_code', '=', defaultCode],
            ['location_id.usage', '=', 'internal'] 
        ];
        
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        // 3. Xử lý hiển thị
        const textDisplay = formatStockResult(quants);
        insertInline(lineEl, textDisplay);

        // Check overflow (Cảnh báo nếu quét dư)
        checkAndHighlightOverflow(lineEl);
        
    } catch(e) {
        console.error("Lỗi lấy tồn kho:", e);
    }
}

function checkAndHighlightOverflow(lineEl) {
    try {
        const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
        if (!qtyEl) return;
        const qtyText = qtyEl.textContent || "";
        // Parse dạng "5/10"
        const match = qtyText.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);
        if (!match) return;
        const qtyDone = parseFloat(match[1]) || 0;
        const demand = parseFloat(match[2]) || 0;

        if (demand > 0 && qtyDone >= demand) {
            qtyEl.style.color = "#d9534f"; // Đỏ
            qtyEl.style.fontWeight = "bold";
            if (!qtyEl.parentElement.querySelector(".hlv-warning-icon")) {
                const icon = document.createElement("span");
                icon.className = "hlv-warning-icon";
                icon.textContent = " ✅"; // Đã đủ
                qtyEl.parentElement.appendChild(icon);
            }
        }
    } catch (e) {}
}

function setupObserver(orm) {
    if (window.__hlv_observer__) return;
    const obs = new MutationObserver((mutations) => {
        mutations.forEach((m) => {
            m.addedNodes.forEach((node) => {
                if (node instanceof HTMLElement) {
                    if (node.matches(".o_barcode_line")) annotateLine(node, orm);
                    node.querySelectorAll(".o_barcode_line").forEach(el => annotateLine(el, orm));
                }
            });
            // Nếu số lượng thay đổi thì check lại màu sắc
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
        document.querySelectorAll(".o_barcode_line").forEach(el => annotateLine(el, orm));
    }
}

// =============================================================================
// PHẦN 2: LOGIC XỬ LÝ BARCODE & LƯU IM LẶNG (SILENT SAVE)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("✅ [HLV] Barcode System v3.0 - Silent Save & Multi-Stock Ready!");
        setTimeout(() => setupObserver(this.orm), 1000);
    },

    async processBarcode(barcode) {
        // --- GIỮ NGUYÊN LOGIC CHECK CŨ ---
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // 1. Check Product
        const product = await this._identifyProductSafe(barcode);
        
        // --- NẾU LÀ SẢN PHẨM: CHECK CẢNH BÁO TRƯỚC KHI QUÉT ---
        if (product) {
            const lines = this.currentState.lines || [];
            const matchedLine = lines.find(l => l.product_id.id === product.id);
            if (matchedLine) {
                const done = parseFloat(matchedLine.qty_done || 0);
                const demand = parseFloat(matchedLine.product_uom_qty || 0);
                if (demand > 0 && done >= demand) {
                    // Cảnh báo âm thanh + Notify đỏ
                    this.env.services.notification.add(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n(${done}/${demand})`, { type: 'danger' });
                    this._playErrorSound();
                    return; // Chặn không cho quét
                }
            }
        }

        // 2. GỌI LOGIC GỐC CỦA ODOO (Để nó tăng số lượng trên giao diện)
        await super.processBarcode(...arguments);

        // 3. LƯU TỰ ĐỘNG & IM LẶNG (SILENT AUTO SAVE)
        // Đây là bước quan trọng để F5 không mất dữ liệu
        try {
            // Mẹo: Tạm thời vô hiệu hóa hàm notification.add để nó không hiện popup xanh
            const originalNotify = this.env.services.notification.add;
            this.env.services.notification.add = () => {}; // Mute

            console.log("💾 [HLV] Đang lưu ngầm vào DB...");
            await this.save(); // Gọi lệnh lưu xuống server
            console.log("✅ [HLV] Đã lưu xong.");

            // Khôi phục lại notification service
            this.env.services.notification.add = originalNotify; 
        } catch (err) {
            console.error("❌ [HLV] Lỗi lưu tự động:", err);
            // Nếu lỗi save thì PHẢI báo user biết, nên ta dùng alert thô thiển để chắc chắn họ thấy
            // alert("Lỗi mạng! Dữ liệu chưa được lưu. Vui lòng kiểm tra lại.");
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
    },

    _playErrorSound() {
        try {
            if (this.env.services.sound) {
                this.env.services.sound.play('error');
            } else {
                const audio = new Audio('/custom_barcode_scan_redirect/static/src/sound/error.mp3'); // Fallback sound gốc odoo
                audio.play().catch(() => {});
            }
        } catch(e) {}
    }
});