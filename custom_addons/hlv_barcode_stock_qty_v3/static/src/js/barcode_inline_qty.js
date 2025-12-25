/** @odoo-module **/

import  BarcodeModel  from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// =============================================================================
// HELPER: UI & UTILS
// =============================================================================

function extractId(field) {
    if (!field) return null;
    if (Array.isArray(field)) return field[0];
    if (typeof field === 'object') return field.id;
    return field;
}

function getLineDemand(line) {
    // Odoo 18 thường dùng 'product_uom_qty' cho demand hoặc 'quantity_product_uom'
    if (line.reserved_uom_qty > 0) return line.reserved_uom_qty;
    if (line.product_uom_qty > 0) return line.product_uom_qty;
    // Fallback cho Odoo 18 mới nhất nếu đổi tên trường
    if (line.demand_qty > 0) return line.demand_qty; 
    return 0;
}

// THANH TRẠNG THÁI (VISUAL STATUS BAR)
function updateSaveStatusUI(status) {
    let el = document.getElementById('hlv-save-status');
    if (!el) {
        el = document.createElement('div');
        el.id = 'hlv-save-status';
        el.style.cssText = "position: fixed; top: 0; left: 0; width: 100%; height: 0px; z-index: 999999; transition: all 0.2s ease-in-out; text-align: center; color: white; font-weight: bold; line-height: 25px; font-size: 14px; overflow: hidden; font-family: system-ui;";
        document.body.appendChild(el);
    }
    
    if (status === 'saving') {
        el.style.backgroundColor = '#d9534f'; // ĐỎ
        el.style.height = '30px';
        el.innerText = "💾 ĐANG LƯU... VUI LÒNG CHỜ (ĐỪNG F5)";
    } else if (status === 'success') {
        el.style.backgroundColor = '#28a745'; // XANH
        el.style.height = '30px';
        el.innerText = "✅ ĐÃ LƯU THÀNH CÔNG";
        setTimeout(() => { el.style.height = '0px'; }, 1500);
    } else {
        el.style.height = '0px';
    }
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

async function renderInlineStock(lineEl, orm) {
    // Logic vẽ Inline Stock (Giữ nguyên vì chỉ thao tác DOM)
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
// MAIN LOGIC (ODOO 18 COMPATIBLE)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] ODOO 18 BARCODE PATCH LOADED");
        
        this.isSavingData = false;

        // Chặn F5
        window.onbeforeunload = (e) => {
            if (this.isSavingData) {
                const msg = "Dữ liệu đang lưu! Đừng tải lại trang!";
                e = e || window.event;
                if (e) e.returnValue = msg;
                return msg;
            }
        };

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

    _setSaving(state) {
        this.isSavingData = state;
        updateSaveStatusUI(state ? 'saving' : (state === false ? 'success' : 'idle'));
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        this._setSaving(true);

        try {
            // 1. NHẬN DIỆN SẢN PHẨM
            const product = await this._identifyProductSafe(barcode);
            
            // 2. LẤY VỊ TRÍ HIỆN TẠI (Nơi đang đứng)
            // Trong Odoo 18, this.location chứa record vị trí hiện tại
            let currentLoc = this.location; 
            let currentLocId = currentLoc ? currentLoc.id : null;
            
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            // Nếu tìm thấy sản phẩm trong danh sách lines
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
                    // Tìm dòng chưa xong để ưu tiên "cướp"
                    if (d < r) candidateLine = l;
                });
                
                // Fallback: nếu xong hết rồi thì lấy dòng cuối cùng (để chặn dư)
                if (!candidateLine && productLines.length > 0) candidateLine = productLines[productLines.length - 1];

                // -------------------------------------------------------------
                // 🛑 CHECK 1: SỐ LƯỢNG (Limit)
                // -------------------------------------------------------------
                const isUnplanned = (totalDemand === 0);
                if (isUnplanned) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ SẢN PHẨM KHÔNG CÓ TRONG PHIẾU!\n\nSP: ${product.display_name}`);
                    this._setSaving(null);
                    return;
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n\nSP: ${product.display_name}\nTiến độ: ${totalDone}/${totalDemand}`);
                    this._setSaving(null);
                    return;
                }

                // -------------------------------------------------------------
                // 🌍 CHECK 2: VỊ TRÍ (Server Check)
                // -------------------------------------------------------------
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

                // -------------------------------------------------------------
                // 🚀 CHECK 3: SMART MOVE & UPDATE (ODOO 18 STYLE)
                // -------------------------------------------------------------
                if (candidateLine && currentLocId) {
                    const lineLocId = extractId(candidateLine.location_id);
                    
                    // Nếu vị trí dòng KHÁC vị trí đang đứng
                    if (lineLocId !== currentLocId) {
                        console.log(`✅ [HLV] Odoo 18 Smart Move: ${lineLocId} -> ${currentLocId}`);
                        
                        try {
                            // TRONG ODOO 18: CHÚNG TA SỬA TRỰC TIẾP STATE OBJECT
                            // 1. Cập nhật vị trí MỚI cho dòng CŨ (Quan trọng để tránh tách dòng)
                            candidateLine.location_id = currentLoc; 
                            
                            // 2. Tăng số lượng
                            candidateLine.qty_done = (candidateLine.qty_done || 0) + 1;
                            
                            // 3. Đánh dấu dòng này đã được sửa (để Odoo 18 biết mà lưu)
                            // Một số bản Odoo cần cờ này, nếu không có cũng không sao vì đã thay đổi qty
                            // candidateLine._isDirty = true; 

                            // 4. Kích hoạt vẽ lại UI
                            this.trigger('update');

                            // 5. GỌI SAVE NGAY
                            await this.save();
                            
                            this._setSaving(false); // Xanh
                            return; // CHẶN SUPER
                        } catch (e) {
                            console.error("Move Error:", e);
                            alert("Lỗi khi chuyển dòng: " + e.message);
                            this._setSaving(null);
                        }
                    }
                }
            }

            // =============================================================
            // FALLBACK
            // =============================================================
            await super.processBarcode(...arguments);
            
            // Auto Save
            await this.save();
            this._setSaving(false);

        } catch (err) {
            console.error(err);
            this._setSaving(null);
        }
    },

    async _identifyProductSafe(barcode) {
        // Hàm này giữ nguyên
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