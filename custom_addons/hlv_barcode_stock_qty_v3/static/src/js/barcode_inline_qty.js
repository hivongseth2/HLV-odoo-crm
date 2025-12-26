/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// PHẦN 1: VẼ GIAO DIỆN (Dùng Mã Tham Chiếu - Default Code)
// =============================================================================

const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_default_code_at_warehouse";

// Hàm gọi API thủ công (Fetch trực tiếp)
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

    // 2. Tìm trong header location
    const locHeader = document.querySelector(".o_barcode_location_line");
    if (locHeader && locHeader.dataset.location) {
        return locHeader.dataset.location.split("/")[0].toUpperCase();
    }
    return null;
}

function getDefaultCode(lineEl) {
    // LOGIC RIÊNG CHO UI: Lấy Mã nội bộ (Internal Reference) hiển thị trên màn hình
    // (Thường là thẻ .o_product_code)
    let txt = lineEl.querySelector(".o_product_ref .o_product_code")?.textContent?.trim()
           || lineEl.querySelector(".o_product_code")?.textContent?.trim()
           || "";
    
    // Nếu không thấy, mới fallback sang data-barcode (nhưng ưu tiên Mã nội bộ)
    if (!txt && lineEl.dataset.barcode) return lineEl.dataset.barcode;
    return txt;
}

async function annotateLine(lineEl) {
    try {
        const defaultCode = getDefaultCode(lineEl);
        // Nếu đã vẽ rồi thì bỏ qua
        if (!defaultCode || lineEl.classList.contains("hlv-done")) return;
        
        lineEl.classList.add("hlv-done"); 

        const whPrefix = detectWarehousePrefix(lineEl);
        
        // GỌI API THEO DEFAULT CODE
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
        lineEl.classList.remove("hlv-done");
    }
}

function setupObserver() {
    console.log("🔥🔥🔥 V37: UI STARTED (Default Code Mode) 🔥🔥🔥");
    
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

    const waitBody = setInterval(() => {
        if (document.body) {
            obs.observe(document.body, { childList: true, subtree: true });
            clearInterval(waitBody);
            document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
        }
    }, 1000);
}

// CHẠY UI NGAY
setupObserver();


// =============================================================================
// PHẦN 2: VALIDATE KHI QUÉT (Dùng Barcode)
// =============================================================================

function extractId(field) {
    if (!field) return null;
    if (Array.isArray(field)) return field[0];
    if (typeof field === 'object') return field.id;
    return field;
}

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

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🔥🔥🔥 V37: VALIDATOR STARTED (Barcode Mode) 🔥🔥🔥");
        // Chặn F5
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault();
            e.returnValue = 'Dữ liệu chưa lưu!';
        });
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // LOGIC CHECK NGHIỆM NGẶT THEO BARCODE
            
            // 1. Nhận diện sản phẩm bằng BARCODE
            let product = null;
            if (this.cache.products) product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
            
            // 2. Xác định vị trí đang đứng
            let currentLocId = this.location ? this.location.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? (this.record.location_id.id || this.record.location_id[0]) : null);
            let locName = (this.location?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            // 3. Kiểm tra Logic
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

                // A. Check Kế hoạch
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

                // B. Check Tồn kho & Vị trí (GỌI API THEO BARCODE)
                const orm = this.orm || this.env.services.orm;
                if (orm) {
                    // Gọi check_barcode_availability (Hàm này trong Python phải xử lý tìm theo barcode)
                    const res = await orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    
                    if (res && res.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${res.message}`);
                        return;
                    }
                    
                    // Check số lượng tồn
                    if (currentLocId && res && res.qty !== undefined) {
                        if (qtyAtLoc + 1 > res.qty) {
                            safePlaySound(this.env, 'error');
                            alert(`⛔ QUÁ TỒN KHO!\n📦 Tồn thực tế: ${res.qty}\n👉 Bạn đang lấy cái thứ: ${qtyAtLoc + 1}`);
                            return;
                        }
                    }
                }
            }
            
            // Nếu qua hết các cửa ải -> Odoo xử lý
            await super.processBarcode(...arguments);
            
            // Trigger vẽ lại UI sau khi quét xong
            setTimeout(() => {
                document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
            }, 500);

        } catch (e) {
            console.error(e);
            alert("Lỗi: " + e.message);
        }
    }
});