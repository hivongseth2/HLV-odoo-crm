/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// PHẦN 1: GIAO DIỆN HIỂN THỊ TỒN KHO (UI RENDERER) - GIỮ NGUYÊN
// =============================================================================

const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_default_code_at_warehouse";

async function callKw(model, method, args = [], kwargs = {}) {
    const res = await fetch("/web/dataset/call_kw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            jsonrpc: "2.0",
            method: "call",
            params: { model, method, args, kwargs },
            id: Date.now(),
        }),
    });
    const json = await res.json();
    if (json.error) throw json.error;
    return json.result;
}

function insertInline(lineEl, text) {
    const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty") || lineEl.querySelector('div[name="quantity"]');
    if (!qtyEl) return;
    
    let parent = qtyEl.parentElement || qtyEl;
    let badge = parent.querySelector(".hlv-inline-stock");
    if (!badge) {
        badge = document.createElement("div");
        badge.className = "hlv-inline-stock";
        badge.style.cssText = "display: block; margin-top: 4px; font-size: 11px; color: #155724; background-color: #d4edda; padding: 2px 6px; border-radius: 4px; width: fit-content; font-weight: bold; border: 1px solid #c3e6cb;";
        parent.appendChild(badge);
    }
    badge.textContent = `📦 ${text}`;
}

function getDefaultCode(lineEl) {
    let txt = lineEl.querySelector(".o_product_ref .o_product_code")?.textContent?.trim()
           || lineEl.querySelector(".o_product_code")?.textContent?.trim()
           || "";
    if (!txt && lineEl.dataset.barcode) return lineEl.dataset.barcode;
    if (!txt) {
        const refText = lineEl.querySelector(".o_product_ref")?.textContent?.trim() || "";
        const m = refText.match(/^[A-Z0-9._-]+/i);
        if (m) txt = m[0];
    }
    return txt;
}

function detectWarehousePrefix(lineEl) {
    const destText = lineEl.querySelector(".o_line_destination_location")?.innerText || "";
    let prefix = (destText.split("/")[0] || "").trim();
    if (["TSN", "KBC", "KHD"].includes(prefix)) return prefix;
    const locHeader = document.querySelector(".o_barcode_location_line");
    if (locHeader && locHeader.dataset.location) {
        return locHeader.dataset.location.split("/")[0].toUpperCase();
    }
    return null;
}

async function annotateLine(lineEl) {
    try {
        const defaultCode = getDefaultCode(lineEl);
        if (!defaultCode || lineEl.querySelector('.hlv-inline-stock')) return;
        const whPrefix = detectWarehousePrefix(lineEl);
        const result = await callKw(RPC_MODEL, RPC_METHOD, [defaultCode, whPrefix], {});
        const labelPrefix = whPrefix || "Tổng";
        insertInline(lineEl, `${labelPrefix}: ${result.qty} ${result.uom}`);
    } catch (e) { }
}

function startUiObserver() {
    console.log("🔥🔥🔥 [HLV] UI STARTED 🔥🔥🔥");
    document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
    const obs = new MutationObserver((mutations) => {
        for (const m of mutations) {
            m.addedNodes.forEach((node) => {
                if (!(node instanceof HTMLElement)) return;
                if (node.matches(".o_barcode_line")) annotateLine(node);
                node.querySelectorAll?.(".o_barcode_line").forEach(annotateLine);
            });
        }
    });
    const waitBody = setInterval(() => {
        if (document.body) {
            obs.observe(document.body, { childList: true, subtree: true });
            clearInterval(waitBody);
            document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
        }
    }, 1000);
}


// =============================================================================
// PHẦN 2: VALIDATOR (LOGIC KIỂM TRA & CHẶN F5 MẠNH MẼ)
// =============================================================================

function extractId(field) { return field && field.id ? field.id : (Array.isArray(field) ? field[0] : field); }

function getLineDemand(line) {
    if (line.reserved_uom_qty > 0) return line.reserved_uom_qty;
    if (line.product_uom_qty > 0) return line.product_uom_qty;
    if (line.quantity_product_uom > 0) return line.quantity_product_uom;
    return 0;
}

function safePlaySound(env, type = 'error') {
    try {
        if (env.services.sound) env.services.sound.play(type);
        else new Audio('/web/static/src/audio/error.mp3').play().catch(() => {});
    } catch (e) {}
}

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V45: FIX F5 + ACTION 364");
        
        startUiObserver();

        // --- CƠ CHẾ CHẶN F5 (HARDCORE) ---
        // Gán trực tiếp vào window.onbeforeunload để tránh bị ghi đè
        window.onbeforeunload = function (e) {
            e = e || window.event;
            const msg = 'Dữ liệu chưa lưu! Bạn có chắc muốn tải lại?';
            
            // Cho các trình duyệt cũ (IE, Firefox cũ)
            if (e) { e.returnValue = msg; }
            
            // Cho Chrome, Safari, Edge hiện đại
            return msg;
        };
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // ----------------------------------------------------------------
            // BƯỚC 1: KIỂM TRA URL (Action 364 - Kiểm kê)
            // ----------------------------------------------------------------
            const currentUrl = window.location.href;
            const isInventoryAction = currentUrl.includes("action=364") || currentUrl.includes("action-364");

            if (isInventoryAction) {
                console.log("🛡️ [HLV] Action 364 (Kiểm kê) -> Allow All.");
                await super.processBarcode(...arguments);
                setTimeout(() => { document.querySelectorAll(".o_barcode_line").forEach(annotateLine); }, 500);
                return; 
            }

            // ----------------------------------------------------------------
            // BƯỚC 2: LOGIC CHO CÁC PHIẾU KHÁC
            // ----------------------------------------------------------------
            
            const product = await this._identifyProductSafe(barcode);
            
            let currentLoc = this.location;
            let currentLocId = currentLoc ? currentLoc.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            if (product && this.currentState.lines) {
                
                // Xác định: Phiếu Kế hoạch (có demand) hay Tự do (không demand)
                const isPlannedOperation = this.currentState.lines.some(l => getLineDemand(l) > 0);

                const lines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
                let totalDone = 0;
                let totalDemand = 0;
                let qtyAtLoc = 0;

                lines.forEach(l => {
                    const d = parseFloat(l.qty_done || 0);
                    const r = parseFloat(getLineDemand(l));
                    totalDone += d;
                    totalDemand += r;
                    if (currentLocId && extractId(l.location_id) === currentLocId) qtyAtLoc += d;
                });

                // A. CHECK KẾ HOẠCH
                if (isPlannedOperation) {
                    if (totalDemand === 0) {
                        safePlaySound(this.env, 'error');
                        alert(`⚠️ SẢN PHẨM NGOÀI KẾ HOẠCH!\nSP: ${product.display_name}`);
                        return; 
                    }
                    if (totalDone >= totalDemand) {
                        safePlaySound(this.env, 'error');
                        alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\nSP: ${product.display_name}`);
                        return; 
                    }
                }

                // B. CHECK TỒN KHO THỰC TẾ
                const orm = this.orm || this.env.services.orm;
                if (orm) {
                    const res = await orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    
                    if (res && res.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${res.message}`);
                        return; 
                    }

                    if (currentLocId && res && res.qty !== undefined) {
                        const nextQty = qtyAtLoc + 1;
                        if (nextQty > res.qty) {
                            safePlaySound(this.env, 'error');
                            alert(`⛔ QUÁ TỒN KHO!\n📦 Tồn thực tế: ${res.qty}\n👉 Bạn muốn lấy: ${nextQty}`);
                            return; 
                        }
                    }
                }
            }

            // OK -> Odoo xử lý
            await super.processBarcode(...arguments);
            
            setTimeout(() => {
                document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
            }, 500);

        } catch (err) {
            console.error(err);
            alert("Lỗi: " + err.message);
        }
    },

    async _identifyProductSafe(barcode) {
        let product = null;
        if (this.cache.products) product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
        if (!product && this.currentState.lines) {
             const line = this.currentState.lines.find(l => {
                 const pObj = l.product_id; 
                 if (typeof pObj === 'object') return pObj.barcode === barcode || pObj.default_code === barcode;
                 return false;
             });
             if (line) product = line.product_id;
        }
        return product;
    }
});