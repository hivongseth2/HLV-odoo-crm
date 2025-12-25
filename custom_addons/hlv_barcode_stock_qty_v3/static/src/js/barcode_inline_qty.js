/** @odoo-module **/

import  BarcodeModel  from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

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

// HIỂN THỊ NÚT CHẶN F5 (CSS CỰC MẠNH ĐỂ KHÔNG BỊ ẨN)
function showBlockingButton() {
    let old = document.getElementById('hlv-block-f5-btn');
    if (old) old.remove();

    let btn = document.createElement('button');
    btn.id = 'hlv-block-f5-btn';
    btn.innerText = "⚠️ BẤM VÀO ĐÂY ĐỂ BẬT CHẶN F5 (BẮT BUỘC)";
    btn.style.cssText = `
        position: fixed !important;
        top: 0px !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        z-index: 2147483647 !important; /* Max Z-Index */
        background-color: #ff9800 !important;
        color: white !important;
        border: none !important;
        padding: 10px 20px !important;
        font-weight: bold !important;
        font-size: 16px !important;
        cursor: pointer !important;
        box-shadow: 0 4px 8px rgba(0,0,0,0.3) !important;
        border-radius: 0 0 10px 10px !important;
    `;
    
    btn.onclick = function() {
        window.hlv_user_interacted = true; // Đánh dấu đã tương tác
        btn.innerText = "🛡️ ĐÃ BẬT BẢO VỆ F5";
        btn.style.backgroundColor = "#28a745";
        setTimeout(() => btn.remove(), 2000);
    };

    document.body.appendChild(btn);
}

// HIỂN THỊ MÀN HÌNH CHỜ KHI LƯU (BLOCK UI)
function toggleBusy(busy) {
    let el = document.getElementById('hlv-busy-overlay');
    if (!el) {
        el = document.createElement('div');
        el.id = 'hlv-busy-overlay';
        el.style.cssText = "position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.5); z-index: 2147483646; display: none; justify-content: center; align-items: center; color: white; font-size: 24px; font-weight: bold; flex-direction: column;";
        el.innerHTML = '<div>⏳ ĐANG GHI DATABASE...</div><div style="font-size:16px; margin-top:10px">Tuyệt đối không F5 lúc này!</div>';
        document.body.appendChild(el);
    }
    el.style.display = busy ? 'flex' : 'none';
}

async function renderInlineStock(lineEl, orm) {
    let defaultCode = lineEl.dataset.barcode;
    if (!defaultCode) {
        const codeEl = lineEl.querySelector(".o_product_code") || lineEl.querySelector(".o_product_ref");
        if (codeEl) defaultCode = codeEl.textContent.trim();
    }
    if (!defaultCode || lineEl.querySelector(".hlv-inline-stock")) return;

    try {
        const domain = [['product_id.default_code', '=', defaultCode], ['location_id.usage', '=', 'internal']];
        const quants = await orm.call("stock.quant", "search_read", [domain, ['location_id', 'quantity']]);
        
        let textDisplay = "0";
        if (quants && quants.length > 0) {
            const stockMap = {};
            quants.forEach(q => {
                const locName = q.location_id ? q.location_id[1] : ""; 
                const match = locName.match(/\b(TSN|KBC|KHD)\b/i);
                const key = match ? match[1].toUpperCase() : "KHÁC"; 
                if (!stockMap[key]) stockMap[key] = 0;
                stockMap[key] += q.quantity;
            });
            textDisplay = Object.keys(stockMap).map(k => `${k}: ${stockMap[k]}`).join(" | ");
        }

        const qtyContainer = lineEl.querySelector('div[name="quantity"]') || lineEl.querySelector('.o_barcode_scanner_qty')?.parentElement;
        if (qtyContainer) {
            let badge = document.createElement("div"); 
            badge.className = "hlv-inline-stock";
            badge.style.cssText = `font-size: 11px; color: #004085; background-color: #cce5ff; padding: 2px 6px; border-radius: 4px; margin-top: 4px; font-weight: bold; width: fit-content; display: block; border: 1px solid #b8daff;`;
            badge.textContent = `📦 ${textDisplay}`;
            qtyContainer.appendChild(badge);
        }
    } catch(e) {}
}

// =============================================================================
// MAIN LOGIC
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V18: BRUTE FORCE WRITE + UI Z-INDEX FIX");
        
        // 1. CHẶN F5 CỨNG (Global)
        window.hlv_user_interacted = false;
        window.onbeforeunload = (e) => {
            // Luôn hỏi nếu đã tương tác
            if (window.hlv_user_interacted) {
                e.preventDefault();
                e.returnValue = "DỮ LIỆU CÓ THỂ MẤT! BẠN CHẮC CHẮN MUỐN TẢI LẠI?";
                return e.returnValue;
            }
        };

        // 2. Hiện nút kích hoạt sau 1s (để đảm bảo load xong DOM)
        setTimeout(showBlockingButton, 1500);

        const observer = new MutationObserver(() => {
            document.querySelectorAll(".o_barcode_line").forEach(line => renderInlineStock(line, this.orm));
        });
        const wait = setInterval(() => {
            if (document.body) {
                observer.observe(document.body, { childList: true, subtree: true });
                clearInterval(wait);
            }
        }, 1000);
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // KHÓA MÀN HÌNH ĐỂ TRÁNH QUÉT ĐÚP
        toggleBusy(true);

        try {
            // 1. IDENTIFY
            const product = await this._identifyProductSafe(barcode);
            
            // 2. LOCATION INFO
            let currentLoc = this.location;
            let currentLocId = currentLoc ? currentLoc.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            if (product && this.currentState.lines) {
                const productLines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
                
                let totalDone = 0;
                let totalDemand = 0;
                let candidateLine = null;

                productLines.forEach(l => {
                    const d = parseFloat(l.qty_done || 0);
                    const r = parseFloat(getLineDemand(l));
                    totalDone += d;
                    totalDemand += r;
                    if (d < r) candidateLine = l;
                });
                if (!candidateLine && productLines.length > 0) candidateLine = productLines[productLines.length - 1];

                // 🛑 CHECK 1: LIMIT
                const isUnplanned = (totalDemand === 0);
                if (isUnplanned) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ CHẶN NGOÀI KẾ HOẠCH!\n\nSP: ${product.display_name}`);
                    toggleBusy(false);
                    return;
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n\nSP: ${product.display_name}`);
                    toggleBusy(false);
                    return;
                }

                // 🌍 CHECK 2: SERVER
                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                        toggleBusy(false);
                        return;
                    }
                } catch (e) {
                    alert("Lỗi kết nối server!");
                    toggleBusy(false);
                    return;
                }

                // 🚀 CHECK 3: SMART MOVE (BRUTE FORCE WRITE)
                if (candidateLine && currentLocId) {
                    const lineLocId = extractId(candidateLine.location_id);
                    if (lineLocId !== currentLocId) {
                        console.log(`✅ [HLV] Smart Move: ID ${candidateLine.id} -> ${currentLocId}`);
                        
                        try {
                            const newQty = (candidateLine.qty_done || 0) + 1;

                            // A. DÒNG ĐÃ CÓ ID THẬT (Số nguyên) -> DÙNG WRITE
                            if (candidateLine.id && typeof candidateLine.id === 'number') {
                                // 1. Ghi thẳng xuống DB (Bỏ qua cơ chế cache của Odoo)
                                await this.orm.write("stock.move.line", [candidateLine.id], { 
                                    "location_id": currentLocId,
                                    "qty_done": newQty
                                });
                                
                                // 2. Cập nhật UI thủ công để đồng bộ với DB
                                candidateLine.location_id = currentLoc;
                                candidateLine.qty_done = newQty;
                                this.trigger('update'); // Vẽ lại

                                // QUAN TRỌNG: KHÔNG GỌI THIS.SAVE() Ở ĐÂY NỮA
                                // Vì write đã lưu rồi. Gọi save() có thể ghi đè dữ liệu cũ.
                                
                                console.log("✅ Written to DB successfully");
                                toggleBusy(false);
                                return;
                            } 
                            // B. DÒNG MỚI (VIRTUAL ID) -> DÙNG SAVE
                            else {
                                candidateLine.location_id = currentLoc;
                                candidateLine.qty_done = newQty;
                                this.trigger('update');
                                await this.save();
                                toggleBusy(false);
                                return;
                            }

                        } catch (e) {
                            console.error("Write Error:", e);
                            alert("Lỗi lưu DB: " + e.message);
                            toggleBusy(false);
                            return;
                        }
                    }
                }
            }

            // =============================================================
            // FALLBACK NORMAL
            // =============================================================
            await super.processBarcode(...arguments);
            
            // Auto Save
            await this.save();

        } catch (err) {
            console.error(err);
            alert("Lỗi hệ thống: " + err.message);
        } finally {
            toggleBusy(false);
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