/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// PHẦN 1: GIAO DIỆN HIỂN THỊ TỒN KHO (UI RENDERER)
// (Code này dùng fetch raw để vẽ giao diện theo Mã Nội Bộ - Default Code)
// =============================================================================

const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_default_code_at_warehouse";

// 1. Hàm gọi API thủ công (Giữ nguyên logic của bạn)
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

// 2. Hàm chèn Badge vào dòng
function insertInline(lineEl, text) {
    const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
    if (!qtyEl) return;
    
    // Tìm badge cũ hoặc tạo mới
    let badge = qtyEl.parentElement.querySelector(".hlv-inline-stock");
    if (!badge) {
        badge = document.createElement("small");
        badge.className = "hlv-inline-stock";
        badge.style.cssText = "display: block; margin-top: 4px; font-size: 12px; color: #155724; background-color: #d4edda; padding: 2px 6px; border-radius: 4px; width: fit-content; font-weight: bold; border: 1px solid #c3e6cb;";
        qtyEl.parentElement.appendChild(badge);
    }
    badge.textContent = `📦 ${text}`;
}

// 3. Detect Kho (TSN/KBC...)
function detectWarehousePrefix(lineEl) {
    // Tìm trong dòng
    const destText = lineEl.querySelector(".o_line_destination_location")?.innerText || "";
    let prefix = (destText.split("/")[0] || "").trim();
    if (["TSN", "KBC", "KHD"].includes(prefix)) return prefix;

    // Tìm toàn trang
    const locHeader = document.querySelector(".o_barcode_location_line");
    if (locHeader && locHeader.dataset.location) {
        return locHeader.dataset.location.split("/")[0].toUpperCase();
    }
    return null;
}

// 4. Lấy Default Code (Mã nội bộ) để hiển thị
function getDefaultCode(lineEl) {
    let txt = lineEl.querySelector(".o_product_ref .o_product_code")?.textContent?.trim()
           || lineEl.querySelector(".o_product_code")?.textContent?.trim()
           || "";
    
    // Fallback: Nếu không lấy được text, thử lấy từ data-barcode
    if (!txt && lineEl.dataset.barcode) return lineEl.dataset.barcode;
    
    if (!txt) {
        const refText = lineEl.querySelector(".o_product_ref")?.textContent?.trim() || "";
        const m = refText.match(/^[A-Z0-9._-]+/i);
        if (m) txt = m[0];
    }
    return txt;
}

// 5. Hàm xử lý từng dòng
async function annotateLine(lineEl) {
    try {
        const defaultCode = getDefaultCode(lineEl);
        // Nếu không có mã hoặc đã vẽ rồi thì thôi
        if (!defaultCode || lineEl.querySelector('.hlv-inline-stock')) return;

        const whPrefix = detectWarehousePrefix(lineEl);
        
        // GỌI API LẤY TỒN KHO
        const result = await callKw(
            RPC_MODEL,
            RPC_METHOD,
            [defaultCode, whPrefix],
            {}
        );

        const labelPrefix = whPrefix || (result.base_location?.split("/")?.[0]) || "Tổng";
        insertInline(lineEl, `${labelPrefix}: ${result.qty} ${result.uom}`);
    } catch (e) {
        // Silent error
    }
}

// 6. Hàm quét lại giao diện
function scanExisting() {
    document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
}

// 7. Khởi tạo Observer
function setupObserver() {
    console.log("🔥🔥🔥 UI OBSERVER STARTED 🔥🔥🔥");
    if (window.__hlv_stock_inline_observer__) return;

    const obs = new MutationObserver((mutations) => {
        for (const m of mutations) {
            m.addedNodes.forEach((node) => {
                if (!(node instanceof HTMLElement)) return;
                if (node.matches(".o_barcode_line")) annotateLine(node);
                node.querySelectorAll?.(".o_barcode_line").forEach(annotateLine);
            });
        }
    });

    const waitBody = () => {
        if (document.body) {
            obs.observe(document.body, { childList: true, subtree: true });
            window.__hlv_stock_inline_observer__ = obs;
            scanExisting();
        } else {
            requestAnimationFrame(waitBody);
        }
    };
    waitBody();
}


// =============================================================================
// PHẦN 2: LOGIC KIỂM TRA & CHẶN (VALIDATION PATCH)
// (Code này chạy khi bạn bấm nút quét hoặc gõ barcode)
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
        console.log("🔥🔥🔥 LOGIC VALIDATOR ATTACHED 🔥🔥🔥");
        
        // Kích hoạt UI Observer ngay khi Model khởi tạo
        setupObserver();

        // Chặn F5
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault();
            e.returnValue = 'Dữ liệu chưa lưu!';
        });
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // -----------------------------------------------------------------
            // BƯỚC 1: KIỂM TRA LOGIC (Dùng Barcode để check chính xác)
            // -----------------------------------------------------------------
            
            // A. Nhận diện sản phẩm
            let product = null;
            if (this.cache.products) product = Object.values(this.cache.products).find(p => p.barcode === barcode || p.default_code === barcode);
            
            // B. Xác định vị trí và Prefix kho
            let currentLoc = this.location;
            let currentLocId = currentLoc ? currentLoc.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            // C. Thực hiện kiểm tra
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
                    // Đếm số lượng đã quét tại vị trí đang đứng
                    if (currentLocId && extractId(l.location_id) === currentLocId) {
                        qtyAtLoc += d;
                    }
                });

                // --- CHECK 1: KẾ HOẠCH (DEMAND) ---
                if (totalDemand === 0) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ SẢN PHẨM NGOÀI KẾ HOẠCH!\nSP: ${product.display_name}`);
                    return; // Chặn ngay
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\nSP: ${product.display_name}\nĐã xong: ${totalDone}/${totalDemand}`);
                    return; // Chặn ngay
                }

                // --- CHECK 2: VỊ TRÍ & TỒN KHO (Gọi API check_barcode_availability) ---
                const orm = this.orm || this.env.services.orm;
                if (orm) {
                    // Gọi hàm check backend (Phải dùng đúng Barcode để check)
                    const res = await orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    
                    if (res && res.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${res.message}`);
                        return; // Chặn ngay
                    }
                    
                    // Check giới hạn tồn kho thực tế
                    if (currentLocId && res && res.qty !== undefined) {
                        // Nếu quét thêm 1 cái nữa mà vượt quá tồn kho
                        if (qtyAtLoc + 1 > res.qty) {
                            safePlaySound(this.env, 'error');
                            alert(`⛔ QUÁ TỒN KHO!\n📦 Tồn thực tế tại đây: ${res.qty}\n👉 Bạn đang cố lấy cái thứ: ${qtyAtLoc + 1}`);
                            return; // Chặn ngay
                        }
                    }
                }
            }

            // -----------------------------------------------------------------
            // BƯỚC 2: NẾU HỢP LỆ -> CHO ODOO XỬ LÝ TIẾP
            // -----------------------------------------------------------------
            await super.processBarcode(...arguments);

            // -----------------------------------------------------------------
            // BƯỚC 3: CẬP NHẬT LẠI GIAO DIỆN (Để số tồn kho hiện lên dòng mới)
            // -----------------------------------------------------------------
            setTimeout(() => {
                scanExisting();
            }, 500);

        } catch (err) {
            console.error(err);
            alert("Lỗi hệ thống: " + err.message);
        }
    }
});