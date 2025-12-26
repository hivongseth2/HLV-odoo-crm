/** @odoo-module **/

import  BarcodeModel  from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER FUNCTIONS
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

// Hàm lấy tên kho hiện tại từ giao diện (VD: KBC)
function getCurrentWarehousePrefix() {
    const locEl = document.querySelector('.o_barcode_location_line');
    if (locEl && locEl.dataset.location) {
        return locEl.dataset.location.split('/')[0].toUpperCase();
    }
    return "";
}

// HÀM VẼ GIAO DIỆN (ĐÃ ĐƯỢC MANG TRỞ LẠI)
async function renderInlineStock(lineEl, orm) {
    // 1. Lấy mã barcode từ DOM
    let defaultCode = lineEl.dataset.barcode;
    if (!defaultCode) {
        // Fallback tìm trong phần tử con nếu dataset trống
        const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
        if (codeEl) defaultCode = codeEl.textContent.trim();
    }
    
    // Nếu không có mã hoặc đã vẽ rồi -> Bỏ qua
    if (!defaultCode || lineEl.querySelector(".hlv-inline-stock")) return;

    try {
        // 2. Gọi API lấy tồn kho
        const domain = [['product_id.default_code', '=', defaultCode], ['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        // 3. Tính tổng theo Kho (VD: KBC)
        let totalQty = 0;
        let whPrefix = getCurrentWarehousePrefix() || "KHO"; // Mặc định nếu không tìm thấy

        if (quants && quants.length > 0) {
            quants.forEach(q => {
                const locName = q.location_id ? q.location_id[1] : ""; 
                // Cộng dồn nếu tên vị trí chứa prefix kho (VD: "KBC")
                if (locName.toUpperCase().includes(whPrefix)) {
                    totalQty += q.quantity;
                }
            });
        }

        // 4. Chèn vào giao diện
        const qtyContainer = lineEl.querySelector('div[name="quantity"]');
        if (qtyContainer) {
            let badge = document.createElement("div"); 
            badge.className = "hlv-inline-stock";
            badge.style.cssText = `
                font-size: 11px; 
                color: #155724; 
                background-color: #d4edda; 
                padding: 1px 6px; 
                border-radius: 4px; 
                margin-top: 2px; 
                font-weight: bold; 
                width: fit-content; 
                display: block; 
                border: 1px solid #c3e6cb;
            `;
            badge.innerHTML = `<i class="fa fa-cube"></i> ${whPrefix}: ${totalQty}`;
            qtyContainer.appendChild(badge);
        }
    } catch(e) {
        // Silent error
    }
}

// =============================================================================
// MAIN LOGIC V30
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V30: FINAL (UI + VALIDATOR)");

        // 1. CHẶN F5
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault();
            e.returnValue = 'Dữ liệu chưa lưu! Đừng F5!';
        });

        // 2. KÍCH HOẠT VẼ GIAO DIỆN (MutationObserver)
        // Đây là phần bị thiếu ở V27/V28 khiến nó không hiện số
        this._observer = new MutationObserver((mutations) => {
            document.querySelectorAll(".o_barcode_line").forEach(line => renderInlineStock(line, this.orm));
        });

        const waitLoop = setInterval(() => {
            // Tìm vùng chứa các dòng quét
            const listEl = document.querySelector('.o_barcode_lines'); 
            if (listEl || document.body) {
                // Theo dõi toàn bộ body để bắt sự kiện Odoo vẽ dòng mới
                this._observer.observe(document.body, { childList: true, subtree: true });
                clearInterval(waitLoop);
                // Quét ngay lần đầu tiên
                document.querySelectorAll(".o_barcode_line").forEach(line => renderInlineStock(line, this.orm));
            }
        }, 1000);
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // --- LOGIC KIỂM TRA (GIỮ NGUYÊN TỪ V28) ---
            const product = await this._identifyProductSafe(barcode);
            
            // Lấy thông tin vị trí
            let currentLoc = this.location;
            let currentLocId = currentLoc ? currentLoc.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            if (product && this.currentState.lines) {
                const productLines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
                let totalDone = 0;
                let totalDemand = 0;
                let qtyDoneAtCurrentLoc = 0;

                productLines.forEach(l => {
                    const d = parseFloat(l.qty_done || 0);
                    const r = parseFloat(getLineDemand(l));
                    totalDone += d;
                    totalDemand += r;
                    
                    const lineLocId = extractId(l.location_id);
                    if (currentLocId && lineLocId === currentLocId) qtyDoneAtCurrentLoc += d;
                });

                // Check 1: Kế hoạch
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

                // Check 2: Vị trí & Tồn kho
                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    
                    // A. Sai vị trí
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${result.message || "Không có hàng ở đây!"}`);
                        return;
                    }

                    // B. Quá tồn kho
                    if (currentLocId && result && result.qty !== undefined) {
                        const nextQty = qtyDoneAtCurrentLoc + 1;
                        if (nextQty > result.qty) {
                            safePlaySound(this.env, 'error');
                            alert(`⛔ QUÁ TỒN KHO THỰC TẾ!\n📦 Tồn tại đây: ${result.qty}\n👉 Bạn muốn lấy: ${nextQty}`);
                            return;
                        }
                    }
                } catch (e) {}
            }

            // --- CHO QUA (LOGIC GỐC ODOO) ---
            await super.processBarcode(...arguments);

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