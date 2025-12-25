/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";

// =============================================================================
// HELPER: CÁC HÀM HỖ TRỢ
// =============================================================================

function extractId(field) {
    if (!field) return null;
    if (Array.isArray(field)) return field[0];
    if (typeof field === 'object') return field.id;
    return field;
}

function getLineDemand(line) {
    // Ưu tiên các trường demand của Odoo 18
    if (line.reserved_uom_qty > 0) return line.reserved_uom_qty;
    if (line.product_uom_qty > 0) return line.product_uom_qty;
    if (line.quantity_product_uom > 0) return line.quantity_product_uom;
    return 0;
}

// THANH TRẠNG THÁI (VISUAL STATUS BAR)
function updateSaveStatusUI(status) {
    let el = document.getElementById('hlv-save-status');
    if (!el) {
        el = document.createElement('div');
        el.id = 'hlv-save-status';
        // Style: Nằm trên cùng, font to rõ, z-index cao nhất
        el.style.cssText = "position: fixed; top: 0; left: 0; width: 100%; height: 0px; z-index: 9999999; transition: all 0.2s; text-align: center; color: white; font-weight: bold; line-height: 30px; font-size: 16px; overflow: hidden; font-family: sans-serif;";
        document.body.appendChild(el);
    }
    
    if (status === 'saving') {
        el.style.backgroundColor = '#dc3545'; // ĐỎ ĐẬM
        el.style.height = '35px';
        el.innerText = "⏳ ĐANG GHI DATABASE... KHOAN F5!";
    } else if (status === 'success') {
        el.style.backgroundColor = '#28a745'; // XANH
        el.style.height = '35px';
        el.innerText = "✅ ĐÃ LƯU AN TOÀN!";
        setTimeout(() => { el.style.height = '0px'; }, 2000);
    } else {
        el.style.height = '0px';
    }
}

function safePlaySound(env, type = 'error') {
    try {
        if (env && env.services && env.services.sound) {
            env.services.sound.play(type);
        } else {
            new Audio('/web/static/src/audio/error.mp3').play().catch(() => {});
        }
    } catch (e) {}
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
// MAIN LOGIC (ODOO 18 - HARDCORE SAVE)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V15: HARDCORE WRITE + F5 BLOCKER");
        
        this.isSavingData = false;

        // 1. CƠ CHẾ CHẶN F5 CỨNG (Browser Native)
        window.addEventListener('beforeunload', (e) => {
            // Luôn hiện cảnh báo nếu cờ đang bật
            if (this.isSavingData) {
                e.preventDefault(); 
                e.returnValue = 'DỮ LIỆU CHƯA LƯU XONG! ĐỪNG RỜI ĐI!'; 
                return 'DỮ LIỆU CHƯA LƯU XONG! ĐỪNG RỜI ĐI!';
            }
        });

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

    // Quản lý trạng thái lưu
    _setSaving(state) {
        this.isSavingData = state;
        updateSaveStatusUI(state ? 'saving' : (state === false ? 'success' : 'idle'));
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // BẬT CỜ BẢO VỆ NGAY KHI QUÉT
        this._setSaving(true);

        try {
            // 1. NHẬN DIỆN
            const product = await this._identifyProductSafe(barcode);
            
            // 2. VỊ TRÍ HIỆN TẠI (TỦ 3)
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
                    this._setSaving(null);
                    return;
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n\nSP: ${product.display_name}\nTiến độ: ${totalDone}/${totalDemand}`);
                    this._setSaving(null);
                    return;
                }

                // 🌍 CHECK 2: SERVER CHECK
                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                        this._setSaving(null);
                        return;
                    }
                } catch (e) {
                    alert("Lỗi kết nối kiểm tra vị trí!");
                    this._setSaving(null);
                    return;
                }

                // 🚀 CHECK 3: SMART MOVE & HARD WRITE
                if (candidateLine && currentLocId) {
                    const lineLocId = extractId(candidateLine.location_id);
                    
                    // Nếu khác vị trí -> Cần chuyển kho
                    if (lineLocId !== currentLocId) {
                        console.log(`✅ [HLV] Smart Move Triggered: ${lineLocId} -> ${currentLocId}`);
                        
                        try {
                            const newQty = (candidateLine.qty_done || 0) + 1;

                            // CHIẾN THUẬT: WRITE THẲNG XUỐNG DB (NẾU LÀ DÒNG THẬT)
                            // Nếu candidateLine có ID thật (số nguyên), ta write trực tiếp.
                            if (candidateLine.id && typeof candidateLine.id === 'number') {
                                console.log("💾 Writing direct to DB ID:", candidateLine.id);
                                
                                // GỌI ORM WRITE - CHỜ CHO BẰNG ĐƯỢC
                                await this.orm.write("stock.move.line", [candidateLine.id], { 
                                    "location_id": currentLocId, 
                                    "qty_done": newQty
                                });

                                // Write thành công (không lỗi) -> Mới cập nhật UI
                                candidateLine.qty_done = newQty;
                                candidateLine.location_id = currentLoc; 
                                this.trigger('update');
                                
                                // Đã write xong rồi, tắt cờ
                                this._setSaving(false); 
                                return;
                            } 
                            // Nếu là dòng ảo (New Line): Buộc phải Save
                            else {
                                console.log("💾 Virtual Line -> Using Full Save");
                                candidateLine.qty_done = newQty;
                                candidateLine.location_id = currentLoc;
                                this.trigger('update');
                                await this.save();
                                this._setSaving(false);
                                return;
                            }

                        } catch (e) {
                            console.error("Write Error:", e);
                            alert("❌ LỖI LƯU DỮ LIỆU: " + e.message + "\n\nF5 SẼ MẤT DỮ LIỆU NÀY!");
                            this._setSaving(null);
                            return;
                        }
                    }
                }
            }

            // =============================================================
            // FALLBACK NORMAL SCAN
            // =============================================================
            await super.processBarcode(...arguments);

            // Auto Save
            try {
                 await this.save();
                 this._setSaving(false);
            } catch(e) {
                 this._setSaving(null);
            }

        } catch (err) {
            console.error(err);
            this._setSaving(null);
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