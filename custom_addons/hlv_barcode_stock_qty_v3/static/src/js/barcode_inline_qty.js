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

// Lấy Prefix kho (VD: KBC)
function getCurrentWarehousePrefix() {
    const locEl = document.querySelector('.o_barcode_location_line');
    if (locEl && locEl.dataset.location) {
        return locEl.dataset.location.split('/')[0].toUpperCase();
    }
    return "";
}

// =============================================================================
// LOGIC HIỂN THỊ TỒN KHO (FIXED)
// =============================================================================

async function renderInlineStock(lineEl, orm) {
    // 1. Lấy mã để tìm kiếm (Ưu tiên Barcode, nếu không có lấy Mã nội bộ)
    let searchCode = lineEl.dataset.barcode; // VD: 489...
    let displayCode = ""; // Để lấy prefix check
    
    // Lấy thêm Mã nội bộ (M18 HB8) từ giao diện để đối chiếu
    const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
    if (codeEl) displayCode = codeEl.textContent.trim();
    if (!searchCode) searchCode = displayCode;

    // Nếu đã vẽ rồi hoặc không có mã -> Bỏ qua
    if (!searchCode || lineEl.querySelector(".hlv-inline-stock")) return;

    try {
        // 2. SEARCH ĐA NĂNG: Tìm theo Barcode HOẶC Default Code
        // Domain: (barcode = code OR default_code = code) AND usage = internal
        const domain = [
            '|', 
            ['product_id.barcode', '=', searchCode], 
            ['product_id.default_code', '=', searchCode],
            ['location_id.usage', '=', 'internal']
        ];
        
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        // 3. Tính tổng theo Prefix Kho (KBC)
        let totalQty = 0;
        let whPrefix = getCurrentWarehousePrefix() || "KHO"; 

        if (quants && quants.length > 0) {
            quants.forEach(q => {
                const locName = q.location_id ? q.location_id[1] : ""; 
                if (locName.toUpperCase().includes(whPrefix)) {
                    totalQty += q.quantity;
                }
            });
        }

        // 4. Vẽ lên giao diện
        // Chèn vào bên dưới tên sản phẩm hoặc bên cạnh số lượng
        const destLocDiv = lineEl.querySelector('div[name="destination_location"]'); // Chèn vào chỗ "Vị trí đích" cho thoáng
        
        if (destLocDiv) {
            let badge = document.createElement("span"); 
            badge.className = "hlv-inline-stock";
            badge.style.cssText = `
                font-size: 11px; 
                color: #fff; 
                background-color: #28a745; 
                padding: 1px 6px; 
                border-radius: 4px; 
                margin-left: 8px;
                font-weight: bold; 
                display: inline-block;
            `;
            badge.innerHTML = `<i class="fa fa-database"></i> ${whPrefix}: ${totalQty}`;
            destLocDiv.appendChild(badge);
        }
    } catch(e) {
        console.warn("HLV Render Error:", e);
    }
}

// =============================================================================
// MAIN LOGIC V31
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V31: ROBUST SEARCH + UI FIX");

        // 1. NÚT KÍCH HOẠT F5 (Bắt buộc người dùng bấm để trình duyệt ghi nhận tương tác)
        const f5Btn = document.createElement('div');
        f5Btn.innerText = "🔒 BẢO VỆ DỮ LIỆU (ĐANG TẮT)";
        f5Btn.style.cssText = "position: fixed; bottom: 10px; right: 10px; background: #6c757d; color: white; padding: 5px 10px; border-radius: 5px; font-size: 10px; z-index: 9999; cursor: pointer; opacity: 0.7;";
        f5Btn.onclick = function() {
            f5Btn.innerText = "🛡️ ĐÃ BẬT CHẶN F5";
            f5Btn.style.background = "#28a745";
            f5Btn.style.opacity = "1";
            window._f5Protected = true;
        };
        document.body.appendChild(f5Btn);

        // Sự kiện chặn thoát
        window.addEventListener('beforeunload', (e) => {
            // Chỉ chặn nếu người dùng đã bấm nút hoặc đã có tương tác
            if (window._f5Protected) {
                e.preventDefault();
                e.returnValue = 'Dữ liệu chưa lưu! Đừng F5!';
                return 'Dữ liệu chưa lưu! Đừng F5!';
            }
        });

        // 2. KÍCH HOẠT VẼ UI LIÊN TỤC
        this._observer = new MutationObserver((mutations) => {
            document.querySelectorAll(".o_barcode_line").forEach(line => renderInlineStock(line, this.orm));
        });

        const waitLoop = setInterval(() => {
            if (document.body) {
                this._observer.observe(document.body, { childList: true, subtree: true });
                clearInterval(waitLoop);
                // Trigger lần đầu
                document.querySelectorAll(".o_barcode_line").forEach(line => renderInlineStock(line, this.orm));
            }
        }, 1000);
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // Tự động bật bảo vệ F5 khi bắt đầu quét
        if (!window._f5Protected) {
            window._f5Protected = true;
            const btn = document.querySelector('div[style*="position: fixed; bottom: 10px"]');
            if(btn) { btn.innerText = "🛡️ ĐÃ BẬT CHẶN F5"; btn.style.background = "#28a745"; btn.style.opacity = "1"; }
        }

        try {
            // --- LOGIC VALIDATOR ---
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