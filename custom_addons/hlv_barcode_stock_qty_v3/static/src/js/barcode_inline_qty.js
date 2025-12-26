/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

console.error("🔥🔥🔥 [HLV DEBUG] FILE JS V39 ĐÃ ĐƯỢC NẠP! 🔥🔥🔥");

// =============================================================================
// PHẦN 1: GIAO DIỆN HIỂN THỊ TỒN KHO (UI RENDERER)
// =============================================================================

const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_default_code_at_warehouse";

// Hàm gọi API thủ công
async function callKw(model, method, args = [], kwargs = {}) {
    // console.log(`[HLV DEBUG] Đang gọi API lấy tồn kho cho:`, args);
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
    if (!qtyEl) {
        // console.warn("[HLV DEBUG] Không tìm thấy chỗ chèn Badge cho dòng:", lineEl);
        return;
    }
    
    let parent = qtyEl.parentElement || qtyEl;
    let badge = parent.querySelector(".hlv-inline-stock");
    
    if (!badge) {
        badge = document.createElement("div");
        badge.className = "hlv-inline-stock";
        badge.style.cssText = "display: block; margin-top: 4px; font-size: 12px; color: #155724; background-color: #d4edda; padding: 2px 6px; border-radius: 4px; width: fit-content; font-weight: bold; border: 1px solid #c3e6cb;";
        parent.appendChild(badge);
    }
    badge.textContent = `📦 ${text}`;
    // console.log(`[HLV DEBUG] Đã vẽ Badge: ${text}`);
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

        // console.log(`[HLV DEBUG] Tìm thấy dòng mới: ${defaultCode}`);
        const whPrefix = detectWarehousePrefix(lineEl);
        
        const result = await callKw(
            RPC_MODEL,
            RPC_METHOD,
            [defaultCode, whPrefix],
            {}
        );

        const labelPrefix = whPrefix || "Tổng";
        insertInline(lineEl, `${labelPrefix}: ${result.qty} ${result.uom}`);
    } catch (e) {
        console.error("[HLV DEBUG] Lỗi vẽ giao diện:", e);
    }
}

// KHỞI CHẠY UI NGAY LẬP TỨC (KHÔNG CHỜ PATCH)
function startUiObserver() {
    console.warn("[HLV DEBUG] Khởi động Observer vẽ giao diện...");
    
    // Quét ngay lập tức
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
            console.log("[HLV DEBUG] Observer đã gắn vào Body!");
            // Quét lại lần nữa
            document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
        }
    }, 1000);
}
// Gọi ngay ở đây!
startUiObserver();


// =============================================================================
// PHẦN 2: LOGIC KIỂM TRA & CHẶN (VALIDATION PATCH)
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
        console.error("🔥🔥🔥 [HLV DEBUG] BARCODE MODEL PATCHED! 🔥🔥🔥");
        
        // Chặn F5
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault();
            e.returnValue = 'Dữ liệu chưa lưu!';
        });
    },

    async processBarcode(barcode) {
        console.warn(`[HLV DEBUG] >>> ĐANG QUÉT BARCODE: ${barcode}`);
        
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // debugger; // <--- BỎ COMMENT DÒNG NÀY ĐỂ SOI CODE
            
            // 1. Nhận diện sản phẩm
            let product = null;
            if (this.cache.products) product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
            
            console.log("[HLV DEBUG] Nhận diện sản phẩm:", product ? product.display_name : "Không thấy");

            // 2. Xác định vị trí
            let currentLocId = this.location ? this.location.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (this.location?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            console.log(`[HLV DEBUG] Vị trí: ${locName} (ID: ${checkLocId}), Prefix: ${whPrefix}`);

            // 3. Logic Check
            if (product && this.currentState.lines) {
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

                console.log(`[HLV DEBUG] Đã quét: ${totalDone}/${totalDemand}, Tại vị trí này: ${qtyAtLoc}`);

                // Check Kế hoạch
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

                // Check Backend API (Check Barcode Availability)
                const orm = this.orm || this.env.services.orm;
                if (orm) {
                    console.log("[HLV DEBUG] Gọi API check_barcode_availability...");
                    const res = await orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    console.log("[HLV DEBUG] Kết quả API Check:", res);

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
                } else {
                    console.error("[HLV DEBUG] Không tìm thấy ORM để gọi API!");
                }
            }

            // Nếu mọi thứ OK
            console.log("[HLV DEBUG] Check OK -> Gọi super.processBarcode");
            await super.processBarcode(...arguments);
            
            // Trigger vẽ lại UI
            setTimeout(() => {
                document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
            }, 500);

        } catch (err) {
            console.error("[HLV DEBUG] LỖI FATAL:", err);
            alert("Lỗi: " + err.message);
        }
    }
});