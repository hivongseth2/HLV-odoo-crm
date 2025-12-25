/** @odoo-module **/

import BarcodeModel  from "@stock_barcode/models/barcode_model"; 
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// =============================================================================
// HELPER: UI & SOUND & NOTIFICATION
// =============================================================================

function playErrorSound(env) {
    try {
        if (env && env.services && env.services.sound) {
            env.services.sound.play('error');
            return;
        }
        const audio = new Audio('/custom_barcode_scan_redirect/static/src/sound/error.mp3');
        audio.play().catch(() => {});
    } catch (e) {}
}

function showNotification(env, message, type = 'danger') {
    try {
        if (env && env.services && env.services.notification) {
            env.services.notification.add(message, { 
                type: type, 
                sticky: type === 'danger', 
                title: type === 'danger' ? "CẢNH BÁO" : "Thông báo" 
            });
        } else {
            alert(message);
        }
    } catch (e) { console.error(e); }
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

        if (demand > 0 && qtyDone >= demand) {
            qtyEl.style.color = "#d9534f";
            qtyEl.style.fontWeight = "bold";
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

async function annotateLine(lineEl, orm) {
    if (lineEl.__hlv_done__) return;
    lineEl.__hlv_done__ = true;
    
    let defaultCode = lineEl.querySelector(".o_product_ref")?.textContent?.trim() || "";
    if (!defaultCode || defaultCode.includes("\n")) {
         const m = (lineEl.innerText || "").match(/^[A-Z0-9._-]+/);
         if (m) defaultCode = m[0];
    }
    if (!defaultCode) return;

    const breadcrumb = document.body.innerText;
    const m = breadcrumb.match(/\b(TSN|KBC|KHD)\b/i);
    const whPrefix = m ? m[1].toUpperCase() : null;

    try {
        const result = await orm.call("stock.quant", "get_qty_by_default_code_at_warehouse", [defaultCode, whPrefix]);
        const labelPrefix = whPrefix || (result.base_location?.split("/")?.[0]) || "tổng";
        insertInline(lineEl, `tồn (${labelPrefix}): ${result.qty} ${result.uom}`);
        checkAndHighlightOverflow(lineEl);
    } catch(e) {}
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
// MAIN LOGIC: PATCH BARCODE MODEL (AUTO SAVE)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("✅ [HLV] Barcode v2.1 - Auto Save Ready!");
        setTimeout(() => setupObserver(this.orm), 1000);
    },

    async processBarcode(barcode) {
        // --- 1. CÁC BƯỚC CHECK (GIỮ NGUYÊN) ---
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        const product = await this._identifyProductSafe(barcode);
        if (!product) return super.processBarcode(...arguments);

        // Check Limit
        const lines = this.currentState.lines || [];
        const matchedLine = lines.find(l => l.product_id.id === product.id);
        if (matchedLine) {
            const done = parseFloat(matchedLine.qty_done || 0);
            const demand = parseFloat(matchedLine.product_uom_qty || 0);
            if (demand > 0 && done >= demand) {
                showNotification(this.env, `⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n(${done}/${demand})`, 'danger');
                playErrorSound(this.env);
                return;
            }
        }

        // Check Stock
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
            const result = await this.orm.call(
                "stock.quant", "check_barcode_availability", [barcode, whPrefix, sourceLocId] 
            );
            if (result && result.allow === false) {
                showNotification(this.env, result.message, 'danger');
                playErrorSound(this.env);
                return; 
            }
        } catch (e) { console.error("[HLV] RPC Error:", e); }

        // --- 2. GỌI LOGIC GỐC ĐỂ CẬP NHẬT UI ---
        // Lưu ý: Phải dùng await để chờ nó xong việc cập nhật số lượng trên RAM
        await super.processBarcode(...arguments);

        // --- 3. [MỚI] TỰ ĐỘNG LƯU VÀO DB ---
        try {
            console.log("💾 [HLV] Auto Saving...");
            await this.save(); 
            // Nếu dùng Odoo 17/18, hàm save() của model sẽ trigger việc ghi xuống backend
            showNotification(this.env, "Đã lưu!", "success");
        } catch (err) {
            console.warn("[HLV] Auto Save Failed:", err);
            // Không chặn lỗi này để tránh treo màn hình, chỉ log ra thôi
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