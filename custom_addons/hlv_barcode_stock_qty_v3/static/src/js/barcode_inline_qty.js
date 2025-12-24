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
        
        // Odoo 18: Danh sách dòng nằm trong this.currentState.lines
       const lines = this.currentState.lines || [];
        const matchedLine = lines.find(l => (l.product_id.barcode === barcode || l.product_id.default_code === barcode));
        if (matchedLine) {
            const done = parseFloat(matchedLine.qty_done || 0);
            const demand = parseFloat(matchedLine.product_uom_qty || 0);
            if (demand > 0 && done >= demand) {
                this.notification.add(`⚠️ Đã đủ số lượng (${done}/${demand})`, { type: "danger" });
                this._beep("error");
                return;
            }
        }

        // 2. LẤY THÔNG TIN VỊ TRÍ (QUAN TRỌNG)
        let whPrefix = null;
        let sourceLocId = null;

        // A. Thử lấy ID vị trí nguồn (Source Location) từ Picking
        if (this.record && this.record.location_id) {
            sourceLocId = this.record.location_id.id;
            // Tiện thể lấy luôn prefix từ tên vị trí nguồn
            const locName = this.record.location_id.display_name || ""; // "KBC/Tồn kho/TỦ 3"
            const m = locName.match(/\b(TSN|KBC|KHD)\b/i);
            if (m) whPrefix = m[1].toUpperCase();
        }

        // B. Nếu chưa có prefix, quét vét cạn mọi nơi trên giao diện
        if (!whPrefix) {
            const candidates = [
                this.record?.display_name, // Tên phiếu
                document.querySelector(".o_breadcrumb")?.innerText, // Breadcrumb
                document.querySelector(".o_barcode_header")?.innerText, // Header
                document.body.innerText // Toàn trang (Fallback cuối cùng)
            ];
            for (const txt of candidates) {
                if (txt) {
                    const m = txt.match(/\b(TSN|KBC|KHD)\b/i);
                    if (m) {
                        whPrefix = m[1].toUpperCase();
                        break;
                    }
                }
            }
        }

        // Nếu vẫn null thì gán tạm giá trị để server biết mà log lỗi (không để null)
        if (!whPrefix) whPrefix = "UNKNOWN";

        console.log(`[HLV] Check Server: Prefix=${whPrefix}, LocID=${sourceLocId}`);

        // 3. GỌI SERVER CHECK
        try {
            // Truyền thêm tham số thứ 3 là sourceLocId
            const result = await this.orm.call(
                "stock.quant", 
                "check_barcode_availability", 
                [barcode, whPrefix, sourceLocId]
            );
            
            if (result && result.allow === false) {
                // CHẶN + BÁO LỖI
                this.notification.add(result.message, { type: "danger", sticky: true, title: "CẢNH BÁO KHO" });
                this._beep("error");
                
                // Dùng alert để chắc chắn user phải bấm OK mới quét tiếp được
                // alert(result.message); 
                
                return; // ⛔ STOP
            }

        } catch (e) {
            console.error("[HLV] RPC Error:", e);
            // Nếu lỗi server (500), chặn luôn cho an toàn?
            this.notification.add("Lỗi kết nối Server khi check tồn kho!", { type: "danger" });
            return; 
        }

        return super.processBarcode(...arguments);
    }
});