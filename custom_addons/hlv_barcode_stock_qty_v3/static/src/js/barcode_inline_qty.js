/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model"; 
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

console.log("🔥🔥🔥 HLV: FILE JS ĐÃ ĐƯỢC LOAD THÀNH CÔNG !!! 🔥🔥🔥");

// -------------------------------------------------------------------------
// PHẦN 1: LOGIC HIỂN THỊ TRÊN DOM (Giữ nguyên logic visual cũ của bạn)
// -------------------------------------------------------------------------
// (Phần này để vẽ chữ "tồn: 10" lên giao diện, chạy độc lập với logic chặn)

const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_default_code_at_warehouse";

async function callKw(orm, model, method, args = [], kwargs = {}) {
    // Trong Odoo 18, ta dùng orm service được truyền vào model
    return await orm.call(model, method, args, kwargs);
}

function insertInline(lineEl, text) {
    const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
    if (!qtyEl) return;
    let badge = qtyEl.parentElement.querySelector(".hlv-inline-stock");
    if (!badge) {
        badge = document.createElement("small");
        badge.className = "hlv-inline-stock";
        badge.style.marginLeft = "8px";
        badge.style.fontSize = "12px";
        badge.style.color = "#0a7";
        qtyEl.parentElement.appendChild(badge);
    }
    badge.textContent = `| ${text}`;
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

        if (qtyDone >= demand && demand > 0) {
            qtyEl.style.color = "#d9534f";
            qtyEl.style.fontWeight = "bold";
            // Thêm icon warning
            if (!qtyEl.parentElement.querySelector(".hlv-warning-icon")) {
                const icon = document.createElement("span");
                icon.className = "hlv-warning-icon";
                icon.textContent = " ⚠️";
                icon.style.color = "#d9534f";
                qtyEl.parentElement.appendChild(icon);
            }
        }
    } catch (e) {}
}

// Hàm fetch tồn kho hiển thị (chạy ngầm)
async function annotateLine(lineEl, orm) {
    if (lineEl.__hlv_done__) return;
    lineEl.__hlv_done__ = true;
    
    // Lấy default code từ DOM
    let defaultCode = lineEl.querySelector(".o_product_ref")?.textContent?.trim() || "";
    // Fallback regex nếu dính chữ
    if (!defaultCode || defaultCode.includes("\n")) {
         const m = (lineEl.innerText || "").match(/^[A-Z0-9._-]+/);
         if (m) defaultCode = m[0];
    }
    
    if (!defaultCode) return;

    // Lấy prefix kho
    const breadcrumb = document.querySelector(".o_control_panel")?.innerText || "";
    const prefixMatch = breadcrumb.match(/\b(TSN|KBC|KHD)\b/i);
    const whPrefix = prefixMatch ? prefixMatch[1].toUpperCase() : null;

    try {
        const result = await orm.call("stock.quant", "get_qty_by_default_code_at_warehouse", [defaultCode, whPrefix]);
        const labelPrefix = whPrefix || (result.base_location?.split("/")?.[0]) || "tổng";
        insertInline(lineEl, `tồn (${labelPrefix}): ${result.qty} ${result.uom}`);
        checkAndHighlightOverflow(lineEl);
    } catch(e) {}
}

// Observer để vẽ UI
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
            // Check update qty
            if (m.type === 'characterData' || m.type === 'childList') {
                const target = m.target.parentElement;
                if (target && target.closest('.o_barcode_line')) {
                    checkAndHighlightOverflow(target.closest('.o_barcode_line'));
                }
            }
        });
    });
    const target = document.querySelector('.o_content'); 
    if (target) {
        obs.observe(document.body, { childList: true, subtree: true, characterData: true });
        window.__hlv_observer__ = obs;
        // Scan initial
        document.querySelectorAll(".o_barcode_line").forEach(el => annotateLine(el, orm));
    }
}

patch(BarcodeModel.prototype, {
    
    setup() {
        super.setup(...arguments);
        console.log("✅ [HLV] BarcodeModel setup xong.");
    },

    async processBarcode(barcode) {
        console.log("🚀 [HLV] >>> ĐANG QUÉT MÃ:", barcode);

        if (!barcode || barcode.startsWith("O-CMD")) {
            return super.processBarcode(...arguments);
        }

        // ---------------------------------------------------------
        // 1. TÌM DÒNG KHỚP VỚI BARCODE (LOGIC MỚI - KHÔNG DÙNG CACHE)
        // ---------------------------------------------------------
        // Thay vì tìm trong cache (dễ lỗi), ta tìm trực tiếp trong danh sách dòng đang hiển thị
        let matchedLine = null;
        
        // Odoo 18: Danh sách dòng nằm trong this.currentState.lines
        const lines = this.currentState.lines || [];
        
        for (const line of lines) {
            const product = line.product_id || {};
            // So sánh Barcode hoặc Default Code (Internal Reference)
            if (product.barcode === barcode || product.default_code === barcode) {
                matchedLine = line;
                break; // Tìm thấy dòng đầu tiên khớp thì dừng
            }
        }

        // ---------------------------------------------------------
        // 2. CHECK CLIENT: ĐỦ SỐ LƯỢNG CHƯA?
        // ---------------------------------------------------------
        if (matchedLine) {
            const done = parseFloat(matchedLine.qty_done || 0);
            const demand = parseFloat(matchedLine.product_uom_qty || 0);
            const productName = matchedLine.product_id.display_name;

            console.log(`[HLV] Line Found: ${productName} | Done: ${done} / Demand: ${demand}`);

            if (demand > 0 && done >= demand) {
                const msg = `⚠️ SẢN PHẨM ĐÃ ĐỦ SỐ LƯỢNG!\n📦 ${productName}\n✅ Đã quét: ${done}/${demand}`;
                this.notification.add(msg, { type: "danger", sticky: false });
                this._beep("error");
                console.warn("[HLV] BLOCK: Đã đủ số lượng");
                return; // ⛔ CHẶN
            }
        } else {
            console.log("[HLV] Không tìm thấy dòng nào trong phiếu khớp với mã này (có thể là sp mới).");
        }

        // ---------------------------------------------------------
        // 3. TÌM PREFIX KHO (CẢI TIẾN)
        // ---------------------------------------------------------
        let whPrefix = null;

        // Ưu tiên 1: Lấy từ Source Location (Vị trí nguồn) của phiếu
        // this.record.location_id là object {id, display_name}
        if (this.record && this.record.location_id) {
            const locName = this.record.location_id.display_name || ""; // VD: "KBC/Tồn kho"
            const m = locName.match(/\b(TSN|KBC|KHD)\b/i);
            if (m) whPrefix = m[1].toUpperCase();
        }

        // Ưu tiên 2: Nếu không có, mới tìm trong tên phiếu
        if (!whPrefix && this.record && this.record.display_name) {
            const m = this.record.display_name.match(/\b(TSN|KBC|KHD)\b/i);
            if (m) whPrefix = m[1].toUpperCase();
        }

        console.log("[HLV] Check Server với prefix:", whPrefix);

        // ---------------------------------------------------------
        // 4. CHECK SERVER: TỒN KHO THỰC TẾ
        // ---------------------------------------------------------
        try {
            // Gọi RPC check
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix]);
            
            console.log("[HLV] Kết quả RPC:", result);

            if (result && result.allow === false) {
                this.notification.add(result.message, { type: "danger", sticky: true, title: "HẾT HÀNG / LỖI KHO" });
                this._beep("error");
                console.warn("[HLV] BLOCK: Server chặn");
                return; // ⛔ CHẶN
            }

        } catch (e) {
            console.error("[HLV] Lỗi RPC Check:", e);
            // Lỗi mạng thì cho qua để không chặn người dùng
        }

        // 5. PASS -> GỌI ODOO GỐC
        console.log("✅ [HLV] OK -> Pass cho Odoo xử lý");
        return super.processBarcode(...arguments);
    },
    
    // Xóa hàm _identifyProduct bị lỗi đi, không cần dùng nữa vì ta loop qua lines rồi
});