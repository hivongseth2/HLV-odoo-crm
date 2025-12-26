/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// PART 1: RAW RENDERER (CODE BẠN CUNG CẤP - ĐÃ TỐI ƯU)
// =============================================================================

const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_default_code_at_warehouse";

// Hàm gọi API thủ công (Bypass Odoo ORM để tránh lỗi module)
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
    // Tìm chỗ hiển thị số lượng
    const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty") || lineEl.querySelector('div[name="quantity"]');
    if (!qtyEl) return;
    
    // Tìm hoặc tạo badge
    let parent = qtyEl.parentElement || qtyEl;
    let badge = parent.querySelector(".hlv-inline-stock");
    
    if (!badge) {
        badge = document.createElement("div"); // Dùng div block cho dễ nhìn
        badge.className = "hlv-inline-stock";
        badge.style.cssText = "font-size: 11px; color: #155724; background-color: #d4edda; padding: 2px 5px; border-radius: 4px; margin-top: 4px; font-weight: bold; width: fit-content; border: 1px solid #c3e6cb;";
        parent.appendChild(badge);
    }
    badge.textContent = `📦 ${text}`;
}

function detectWarehousePrefix(lineEl) {
    // 1. Tìm trong dòng
    const destText = lineEl.querySelector(".o_line_destination_location")?.innerText || "";
    let prefix = (destText.split("/")[0] || "").trim();
    if (["TSN", "KBC", "KHD"].includes(prefix)) return prefix;

    // 2. Tìm trong header location (Tủ 3...)
    const locHeader = document.querySelector(".o_barcode_location_line");
    if (locHeader && locHeader.dataset.location) {
        return locHeader.dataset.location.split("/")[0].toUpperCase();
    }
    return null;
}

function getDefaultCode(lineEl) {
    // Ưu tiên data-barcode vì nó chính xác nhất
    if (lineEl.dataset.barcode) return lineEl.dataset.barcode;

    // Fallback quét text
    let txt = lineEl.querySelector(".o_product_ref .o_product_code")?.textContent?.trim()
           || lineEl.querySelector(".o_product_code")?.textContent?.trim()
           || "";
    return txt;
}

async function annotateLine(lineEl) {
    try {
        const defaultCode = getDefaultCode(lineEl);
        // Đánh dấu dòng đã xử lý để không gọi API lại nhiều lần
        if (!defaultCode || lineEl.classList.contains("hlv-done")) return;
        
        lineEl.classList.add("hlv-done"); // Đánh dấu

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
        console.warn("HLV Render Error", e);
        lineEl.classList.remove("hlv-done"); // Lỗi thì gỡ đánh dấu để lần sau thử lại
    }
}

// SETUP OBSERVER (CHẠY NGẦM)
function setupObserver() {
    console.log("🔥🔥🔥 V36: HYBRID RENDERER STARTED 🔥🔥🔥");
    
    // Quét ngay lần đầu
    document.querySelectorAll(".o_barcode_line").forEach(annotateLine);

    const obs = new MutationObserver((mutations) => {
        for (const m of mutations) {
            m.addedNodes.forEach((node) => {
                if (node instanceof HTMLElement) {
                    if (node.matches(".o_barcode_line")) annotateLine(node);
                    node.querySelectorAll?.(".o_barcode_line").forEach(annotateLine);
                }
            });
        }
    });

    // Đợi body sẵn sàng
    const waitBody = setInterval(() => {
        if (document.body) {
            obs.observe(document.body, { childList: true, subtree: true });
            clearInterval(waitBody);
            // Quét lại phát nữa cho chắc
            document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
        }
    }, 1000);
}

// KHỞI CHẠY UI NGAY LẬP TỨC
setupObserver();


// =============================================================================
// PART 2: LOGIC VALIDATION (PATCH MODEL ODOO)
// =============================================================================
// Phần này giữ lại để chặn F5 và Chặn quét sai (Logic backend)

function getLineDemand(line) {
    if (line.reserved_uom_qty > 0) return line.reserved_uom_qty;
    if (line.product_uom_qty > 0) return line.product_uom_qty;
    if (line.quantity_product_uom > 0) return line.quantity_product_uom;
    return 0;
}

function safePlaySound(env, type = 'error') {
    try {
        if (env.services.sound) {
            env.services.sound.play(type);
        } else {
            new Audio('/web/static/src/audio/error.mp3').play().catch(() => {});
        }
    } catch (e) {}
}

// Patch Model để xử lý Logic nghiệp vụ (Check limit, check location)
patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        // Chặn F5
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault();
            e.returnValue = 'Dữ liệu chưa lưu!';
        });
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // LOGIC CHECK (Giữ nguyên từ V34)
            // 1. Nhận diện sản phẩm
            let product = null;
            if (this.cache.products) product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
            
            // 2. Lấy vị trí
            let currentLocId = this.location ? this.location.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? (this.record.location_id.id || this.record.location_id[0]) : null);

            // 3. Kiểm tra
            if (product && this.currentState.lines) {
                const lines = this.currentState.lines.filter(l => (l.product_id.id || l.product_id[0]) === product.id);
                let totalDone = 0;
                let totalDemand = 0;
                let qtyAtLoc = 0;

                lines.forEach(l => {
                    const d = parseFloat(l.qty_done || 0);
                    const r = parseFloat(getLineDemand(l));
                    totalDone += d;
                    totalDemand += r;
                    const lLocId = l.location_id ? (l.location_id.id || l.location_id[0]) : null;
                    if (currentLocId && lLocId === currentLocId) qtyAtLoc += d;
                });

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

                // Check tồn kho (Gọi hàm check cũ)
                const orm = this.orm || this.env.services.orm; // Fix lấy ORM
                if (orm) {
                    const res = await orm.call("stock.quant", "check_barcode_availability", [barcode, null, checkLocId]);
                    if (res && res.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${res.message}`);
                        return;
                    }
                    if (currentLocId && res && res.qty !== undefined) {
                        if (qtyAtLoc + 1 > res.qty) {
                            safePlaySound(this.env, 'error');
                            alert(`⛔ QUÁ TỒN KHO!\nTồn: ${res.qty}, Đang lấy: ${qtyAtLoc + 1}`);
                            return;
                        }
                    }
                }
            }
            
            // Nếu OK -> Odoo xử lý tiếp
            await super.processBarcode(...arguments);
            
            // Sau khi quét, dòng mới hiện ra -> Trigger vẽ lại UI ngay
            setTimeout(() => {
                document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
            }, 500);

        } catch (e) {
            console.error(e);
            alert("Lỗi: " + e.message);
        }
    }
});