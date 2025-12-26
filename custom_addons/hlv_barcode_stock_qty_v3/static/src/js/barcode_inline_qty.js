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

// =============================================================================
// UI RENDERER (LOGIC VẼ GIAO DIỆN)
// =============================================================================

async function renderInlineStock(lineEl, orm) {
    // [DEBUG] 1. Kiểm tra phần tử dòng
    // console.log("🔍 Checking Line:", lineEl);

    // Bỏ qua nếu đã vẽ rồi
    if (lineEl.querySelector(".hlv-inline-stock")) return;

    // 1. Lấy mã sản phẩm
    let searchCode = lineEl.dataset.barcode; 
    let displayCode = "";
    
    // Fallback: Tìm trong HTML nếu dataset trống
    const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
    if (codeEl) displayCode = codeEl.textContent.trim();
    if (!searchCode) searchCode = displayCode;

    if (!searchCode) {
        console.warn("⚠️ Line has no barcode/code. Skipping.");
        return;
    }

    console.groupCollapsed(`🛠️ Rendering Stock for: ${searchCode}`);

    try {
        // 2. Gọi API (Search Quants)
        const domain = [
            '|', 
            ['product_id.barcode', '=', searchCode], 
            ['product_id.default_code', '=', searchCode],
            ['location_id.usage', '=', 'internal']
        ];
        
        console.log("📡 Calling stock.quant search_read...");
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        console.log("📩 API Result:", quants);

        // 3. Tính tổng
        let totalQty = 0;
        let qtyDetails = [];

        if (quants && quants.length > 0) {
            quants.forEach(q => {
                totalQty += q.quantity;
                qtyDetails.push(`${q.location_id[1]}: ${q.quantity}`);
            });
        }

        console.log(`🧮 Total Qty: ${totalQty}`);

        // 4. Vẽ lên giao diện
        // Cố gắng tìm nhiều vị trí để chèn, ưu tiên Destination Location
        const destContainer = lineEl.querySelector('div[name="destination_location"]');
        const qtyContainer = lineEl.querySelector('div[name="quantity"]');
        const targetContainer = destContainer || qtyContainer;

        if (targetContainer) {
            let badge = document.createElement("span"); 
            badge.className = "hlv-inline-stock";
            // Style cứng (Inline Style) để không bị đè
            badge.style.cssText = "display: inline-block; background-color: #17a2b8; color: white; font-weight: bold; font-size: 11px; padding: 2px 6px; border-radius: 4px; margin-left: 5px; z-index: 999; border: 1px solid white; box-shadow: 0 1px 2px rgba(0,0,0,0.2);";
            badge.innerHTML = `<i class="fa fa-cubes"></i> Tồn: ${totalQty}`;
            badge.title = qtyDetails.join("\n"); // Hover vào xem chi tiết

            targetContainer.appendChild(badge);
            console.log("✅ Badge injected successfully!");
        } else {
            console.error("❌ Cannot find container (destination_location or quantity) to inject badge.");
        }

    } catch(e) {
        console.error("❌ Render Error:", e);
    } finally {
        console.groupEnd();
    }
}

// =============================================================================
// MAIN LOGIC V32
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V32: LOGGER EDITION STARTED");

        // 1. CHÈN NÚT F5 (Cứng đầu nhất có thể)
        setTimeout(() => {
            if (!document.getElementById('hlv-f5-btn')) {
                const f5Btn = document.createElement('div');
                f5Btn.id = 'hlv-f5-btn';
                f5Btn.innerText = "⚠️ BẤM VÀO ĐÂY ĐỂ BẬT CHẶN F5";
                f5Btn.style.cssText = "position: fixed; bottom: 10px; right: 10px; width: 200px; height: 40px; background: #dc3545; color: white; text-align: center; line-height: 40px; font-weight: bold; cursor: pointer; z-index: 2147483647; border-radius: 5px; box-shadow: 0 0 10px rgba(0,0,0,0.5);";
                
                f5Btn.onclick = () => {
                    window._f5Protected = true;
                    f5Btn.innerText = "🛡️ ĐÃ BẢO VỆ";
                    f5Btn.style.background = "#28a745";
                };
                document.body.appendChild(f5Btn);
            }
        }, 2000);

        // Logic chặn F5
        window.addEventListener('beforeunload', (e) => {
            if (window._f5Protected) {
                e.preventDefault();
                e.returnValue = 'DỮ LIỆU CHƯA LƯU!';
                return 'DỮ LIỆU CHƯA LƯU!';
            }
        });

        // 2. QUÉT GIAO DIỆN LIÊN TỤC (BRUTE FORCE RENDER)
        // Chạy mỗi 2 giây để đảm bảo nếu Odoo vẽ lại làm mất số thì ta vẽ lại tiếp
        setInterval(() => {
            // console.log("🔄 Re-scanning DOM for barcode lines...");
            const lines = document.querySelectorAll(".o_barcode_line");
            if (lines.length > 0) {
                lines.forEach(line => renderInlineStock(line, this.orm));
            }
        }, 2000);
    },

    async processBarcode(barcode) {
        // Tự động bật bảo vệ F5 khi quét
        if (!window._f5Protected) {
            window._f5Protected = true;
            const btn = document.getElementById('hlv-f5-btn');
            if(btn) { btn.innerText = "🛡️ ĐÃ BẢO VỆ"; btn.style.background = "#28a745"; }
        }

        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        try {
            // --- VALIDATOR LOGIC (GIỮ NGUYÊN) ---
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
                } catch (e) {
                    console.error("Validator Error:", e);
                }
            }

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