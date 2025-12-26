/** @odoo-module **/

import  BarcodeModel  from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// 1. HELPER FUNCTIONS
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

// Hàm lấy Prefix kho hiện tại từ giao diện (VD: KBC)
function getCurrentWarehousePrefix() {
    const locEl = document.querySelector('.o_barcode_location_line');
    if (locEl && locEl.dataset.location) {
        // Lấy chữ cái đầu tiên trước dấu / (VD: KBC/Tồn kho -> KBC)
        return locEl.dataset.location.split('/')[0].toUpperCase();
    }
    return "KHO";
}

// HÀM VẼ TỒN KHO LÊN GIAO DIỆN
async function renderInlineStock(lineEl, orm) {
    // 1. Lấy mã sản phẩm từ dòng
    let defaultCode = lineEl.dataset.barcode;
    if (!defaultCode) {
        const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
        if (codeEl) defaultCode = codeEl.textContent.trim();
    }
    
    // Nếu đã vẽ rồi hoặc không có mã -> Bỏ qua
    if (!defaultCode || lineEl.querySelector(".hlv-inline-stock")) return;

    try {
        // 2. Gọi API lấy tồn kho (Search Quants)
        const domain = [['product_id.default_code', '=', defaultCode], ['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        // 3. Tính tổng theo Kho hiện tại (VD: KBC)
        let totalQty = 0;
        let whPrefix = getCurrentWarehousePrefix();

        if (quants && quants.length > 0) {
            quants.forEach(q => {
                const locName = q.location_id ? q.location_id[1] : ""; 
                // Chỉ cộng nếu vị trí thuộc kho này (có chứa KBC)
                if (locName.toUpperCase().includes(whPrefix)) {
                    totalQty += q.quantity;
                }
            });
        }

        // 4. Chèn vào giao diện
        // Tìm chỗ trống div[name="quantity"] để nhét vào
        const qtyContainer = lineEl.querySelector('div[name="quantity"]');
        if (qtyContainer) {
            let badge = document.createElement("div"); 
            badge.className = "hlv-inline-stock";
            // Style đẹp mắt: Màu xanh đậm, nền xanh nhạt
            badge.style.cssText = `
                font-size: 12px; 
                color: #155724; 
                background-color: #d4edda; 
                padding: 2px 8px; 
                border-radius: 10px; 
                margin-top: 5px; 
                font-weight: bold; 
                width: fit-content; 
                display: block; 
                border: 1px solid #c3e6cb;
            `;
            badge.textContent = `📦 ${whPrefix}: ${totalQty}`;
            qtyContainer.appendChild(badge);
        }
    } catch(e) {
        console.warn("Render Stock Error", e);
    }
}

// =============================================================================
// 2. MAIN LOGIC V29
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V29: GUI STOCK + F5 BLOCKER");
        
        // --- A. CHẶN F5 (FIX LỖI KHÔNG HIỆN) ---
        // 1. Gắn sự kiện chặn
        window.addEventListener('beforeunload', (e) => {
            // Chuẩn hiện đại: Phải set returnValue
            e.preventDefault();
            e.returnValue = 'Dữ liệu chưa lưu! Đừng F5!';
            return 'Dữ liệu chưa lưu! Đừng F5!';
        });

        // 2. Mẹo kích hoạt tương tác (Trick):
        // Tự động gắn sự kiện click vào body để trình duyệt biết người dùng đã tương tác
        document.body.addEventListener('click', () => { window._userHasInteracted = true; }, { once: true });

        // --- B. VẼ TỒN KHO TỰ ĐỘNG ---
        // Dùng Observer để theo dõi khi Odoo vẽ dòng mới ra màn hình thì ta chèn số vào
        this._observer = new MutationObserver((mutations) => {
            document.querySelectorAll(".o_barcode_line").forEach(line => renderInlineStock(line, this.orm));
        });

        // Chờ DOM load xong thì gắn Observer
        const waitLoop = setInterval(() => {
            const listEl = document.querySelector('.o_barcode_lines'); // Container chứa các dòng
            if (listEl || document.body) {
                this._observer.observe(document.body, { childList: true, subtree: true });
                clearInterval(waitLoop);
                // Quét 1 lượt đầu tiên cho các dòng đã có sẵn
                document.querySelectorAll(".o_barcode_line").forEach(line => renderInlineStock(line, this.orm));
            }
        }, 1000);
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // --- LOGIC VALIDATOR (GIỮ NGUYÊN TỪ V28) ---
            const product = await this._identifyProductSafe(barcode);
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
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${result.message}`);
                        return;
                    }
                    // Check quá tồn kho
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

            // --- CHO QUA ---
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