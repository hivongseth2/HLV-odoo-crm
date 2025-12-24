/** @odoo-module **/

import { BarcodeModel } from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

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


// -------------------------------------------------------------------------
// PHẦN 2: PATCH BARCODE MODEL (QUAN TRỌNG NHẤT)
// -------------------------------------------------------------------------
// Đây là nơi ta chặn việc quét mã nếu hết hàng hoặc đủ số lượng

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        // Kích hoạt observer UI khi model khởi tạo
        // Dùng setTimeout để đợi DOM render
        setTimeout(() => setupObserver(this.orm), 1000);
    },

    /**
     * Override hàm xử lý barcode chính của Odoo
     * @param {string} barcode 
     */
    async processBarcode(barcode) {
        console.log("[HLV] Processing Barcode:", barcode);

        // 1. Kiểm tra: Nếu barcode rỗng hoặc là lệnh đặc biệt (O-CMD...) thì cho qua
        if (!barcode || barcode.startsWith("O-CMD")) {
            return super.processBarcode(...arguments);
        }

        // 2. LOGIC CHẶN 1: ĐÃ ĐỦ SỐ LƯỢNG CHƯA?
        // Trong Odoo 18, dữ liệu nằm trong this.currentState.lines (không cần cào DOM)
        // Tìm dòng khớp với barcode này trong bộ nhớ của JS
        
        // Cần tìm product tương ứng với barcode này trước để biết nó là dòng nào
        const product = await this._identifyProduct(barcode); 
        
        if (product) {
            // Tìm dòng đang xử lý cho sản phẩm này
            // this.currentState.lines là Map hoặc Array tùy version, kiểm tra kỹ
            const lines = this.currentState.lines || [];
            // Tìm dòng chưa hoàn thành hoặc dòng của sản phẩm đó
            const line = lines.find(l => l.product_id.id === product.id);

            if (line) {
                const qtyDone = line.qty_done || 0;
                const demand = line.product_uom_qty || 0; // Số lượng yêu cầu (reserved)

                // Nếu có Demand (đơn hàng) và đã quét >= Demand
                if (demand > 0 && qtyDone >= demand) {
                    this.notification.add(_t("⚠️ Sản phẩm này đã quét ĐỦ số lượng!"), { type: "danger" });
                    this._beep("error"); // Phát âm thanh lỗi
                    return; // <--- DỪNG LẠI NGAY, KHÔNG GỌI SUPER
                }
            }
        }

        // 3. LOGIC CHẶN 2: CHECK TỒN KHO ONLINE (Gọi về server)
        try {
            // Lấy prefix kho từ tên (đang hiển thị trên breadcrumb hoặc config)
            // Trong Model có this.config hoặc this.record (picking)
            // Lấy tên picking
            const pickingName = this.record ? this.record.display_name : "";
            let whPrefix = null;
            if (pickingName) {
                const m = pickingName.match(/\b(TSN|KBC|KHD)\b/i);
                if (m) whPrefix = m[1].toUpperCase();
            }

            // Gọi RPC check
            const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix]);
            
            if (!result.allow) {
                // HẾT HÀNG
                this.notification.add(result.message, { type: "danger", sticky: true });
                this._beep("error");
                // Dùng Dialog cảnh báo (native confirm của browser cho nhanh gọn, hoặc dùng Dialog service)
                // Odoo 18 Dialog:
                // await this.dialog.add(AlertDialog, { body: result.message });
                return; // <--- CHẶN
            }

        } catch (e) {
            console.error("Lỗi check tồn kho:", e);
            // Nếu lỗi mạng, nên cho qua hay chặn? Tùy bạn. Ở đây cho qua để không tắc nghẽn.
        }

        // 4. Nếu mọi thứ OK, gọi logic gốc của Odoo để tăng số lượng
        return super.processBarcode(...arguments);
    },

    // Helper nội bộ để tìm product từ barcode (dựa trên cache của BarcodeModel)
    async _identifyProduct(barcode) {
        // Odoo có cache sản phẩm trong this.cache.products
        // Logic tìm kiếm giống Odoo: check barcode, check internal ref...
        let product = Object.values(this.cache.products).find(p => p.barcode === barcode);
        if (!product) {
            // Fallback: check default_code
            product = Object.values(this.cache.products).find(p => p.default_code === barcode);
        }
        // Nếu chưa có trong cache, có thể Odoo sẽ tự fetch trong super(), 
        // nhưng để chặn trước thì ta chỉ chặn những gì đã biết.
        return product;
    }
});