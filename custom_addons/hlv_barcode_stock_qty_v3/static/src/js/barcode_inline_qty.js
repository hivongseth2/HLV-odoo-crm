/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// PHẦN 1: GIAO DIỆN HIỂN THỊ TỒN KHO (UI RENDERER)
// (Giữ nguyên phần này vì đã hoạt động tốt)
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
    } catch (e) {
        // Silent error
    }
}

function startUiObserver() {
    console.log("🔥🔥🔥 [HLV] UI OBSERVER STARTED 🔥🔥🔥");
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
startUiObserver();


// =============================================================================
// PHẦN 2: LOGIC CHECK SCAN (VALIDATION)
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
        console.log("🔥🔥🔥 [HLV] VALIDATOR PATCHED 🔥🔥🔥");
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault(); e.returnValue = 'Dữ liệu chưa lưu!';
        });
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            console.log(`[HLV] Checking: ${barcode}`);
            
            // 1. NHẬN DIỆN SẢN PHẨM (Nâng cấp)
            const product = this._identifyProductSafe(barcode);
            
            // 2. Lấy vị trí
            let currentLoc = this.location;
            let currentLocId = currentLoc ? currentLoc.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            // 3. THỰC HIỆN CHECK (Chỉ khi là sản phẩm)
            if (product && this.currentState.lines) {
                console.log(`[HLV] Found Product: ${product.display_name} (ID: ${product.id})`);
                
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

                // --- CHECK KẾ HOẠCH ---
                if (totalDemand === 0) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ NGOÀI KẾ HOẠCH!\nSP: ${product.display_name}`);
                    return;
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\nSP: ${product.display_name}`);
                    return;
                }

                // --- CHECK API (VỊ TRÍ & TỒN KHO) ---
                const orm = this.orm || this.env.services.orm;
                if (orm) {
                    // console.log("[HLV] Calling check_barcode_availability...");
                    const res = await orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    
                    if (res && res.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${res.message}`);
                        return;
                    }
                    if (currentLocId && res && res.qty !== undefined) {
                        if (qtyAtLoc + 1 > res.qty) {
                            safePlaySound(this.env, 'error');
                            alert(`⛔ QUÁ TỒN KHO!\n📦 Tồn: ${res.qty}\n👉 Định lấy: ${qtyAtLoc + 1}`);
                            return;
                        }
                    }
                }
            } else {
                console.log("[HLV] Không phải sản phẩm hoặc không tìm thấy trong Cache.");
            }

            // OK -> Cho qua
            await super.processBarcode(...arguments);
            
            // Trigger vẽ lại
            setTimeout(() => {
                document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
            }, 500);

        } catch (err) {
            console.error(err);
            alert("Lỗi: " + err.message);
        }
    },

    // HÀM TÌM SẢN PHẨM MẠNH HƠN
    _identifyProductSafe(barcode) {
        if (!this.cache.products) return null;
        const products = Object.values(this.cache.products);
        
        // 1. Tìm chính xác Barcode hoặc Default Code
        let found = products.find(p => p.barcode === barcode || p.default_code === barcode || p.code === barcode);
        if (found) return found;

        // 2. Tìm trong Packaging (Đóng gói) - Rất quan trọng với Odoo
        if (this.cache.packagings) {
            const pkg = Object.values(this.cache.packagings).find(p => p.barcode === barcode);
            if (pkg && pkg.product_id) {
                // pkg.product_id có thể là ID hoặc mảng [id, name]
                const pid = Array.isArray(pkg.product_id) ? pkg.product_id[0] : pkg.product_id;
                return this.cache.products[pid];
            }
        }

        return null;
    }
});