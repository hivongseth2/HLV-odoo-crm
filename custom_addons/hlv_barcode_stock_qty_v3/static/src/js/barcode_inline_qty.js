/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
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
    // Fallback cho các bản Odoo 17/18
    if (line.quantity_product_uom > 0) return line.quantity_product_uom;
    return 0;
}

// THANH TRẠNG THÁI & NÚT KÍCH HOẠT BẢO VỆ
function updateSaveStatusUI(status) {
    let el = document.getElementById('hlv-status-bar');
    if (!el) {
        el = document.createElement('div');
        el.id = 'hlv-status-bar';
        el.style.cssText = "position: fixed; top: 0; left: 0; width: 100%; height: 40px; z-index: 9999999; text-align: center; color: white; font-weight: bold; line-height: 40px; font-size: 16px; font-family: system-ui; cursor: pointer; display: flex; justify-content: center; align-items: center;";
        document.body.appendChild(el);
        
        // Sự kiện click để kích hoạt quyền chặn F5
        el.addEventListener('click', () => {
             window.hasUserInteracted = true;
             el.innerHTML = "🛡️ ĐÃ KÍCH HOẠT BẢO VỆ F5";
             el.style.backgroundColor = "#17a2b8";
             setTimeout(() => { el.style.display = 'none'; }, 2000);
        });
        
        // Mặc định hiện nhắc nhở
        el.style.backgroundColor = "#fd7e14"; // Màu cam
        el.innerHTML = "⚠️ BẤM VÀO ĐÂY ĐỂ BẬT CHẶN F5";
    }
    
    // Cập nhật trạng thái khi lưu
    if (status === 'saving') {
        el.style.display = 'flex';
        el.style.backgroundColor = '#dc3545'; // ĐỎ
        el.innerText = "⏳ ĐANG LƯU DỮ LIỆU... TUYỆT ĐỐI KHÔNG F5!";
    } else if (status === 'success') {
        el.style.display = 'flex';
        el.style.backgroundColor = '#28a745'; // XANH
        el.innerText = "✅ ĐÃ LƯU XONG";
        setTimeout(() => { el.style.display = 'none'; }, 1000);
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
// 2. MAIN LOGIC (FIX SAVE & F5)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V16: STATE MUTATION FIX + F5 CLICK TRIGGER");
        
        this.isSavingData = false;
        
        // Tạo cờ tương tác global
        window.hasUserInteracted = false;
        
        // Listener click để kích hoạt bảo vệ
        document.addEventListener('click', () => { window.hasUserInteracted = true; });

        // CHẶN F5 CỨNG
        window.onbeforeunload = (e) => {
            // Chỉ hiện thông báo nếu đang lưu
            if (this.isSavingData) {
                e = e || window.event;
                const msg = "DỮ LIỆU ĐANG ĐƯỢC LƯU! F5 SẼ MẤT DỮ LIỆU!";
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
        
        // Khởi tạo thanh trạng thái ngay
        setTimeout(() => updateSaveStatusUI('init'), 1000);
    },

    _setSaving(state) {
        this.isSavingData = state;
        updateSaveStatusUI(state ? 'saving' : (state === false ? 'success' : 'idle'));
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // BẬT CỜ BẢO VỆ
        this._setSaving(true);

        try {
            // 1. NHẬN DIỆN
            const product = await this._identifyProductSafe(barcode);
            
            // 2. LẤY VỊ TRÍ
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

                // 🛑 CHECK LIMIT
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

                // 🌍 CHECK LOCATION
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

                // 🚀 CHECK 3: SMART MOVE & SAFE SAVE (FIX MẤT DATA)
                if (candidateLine && currentLocId) {
                    const lineLocId = extractId(candidateLine.location_id);
                    
                    if (lineLocId !== currentLocId) {
                        console.log(`✅ [HLV] Smart Move (RAM Mutation): ${lineLocId} -> ${currentLocId}`);
                        
                        try {
                            // 1. SỬA TRỰC TIẾP VÀO RAM CỦA ODOO
                            // Việc này giống như bạn thao tác tay trên màn hình
                            candidateLine.location_id = currentLoc; 
                            candidateLine.qty_done = (candidateLine.qty_done || 0) + 1;
                            
                            // 2. UPDATE UI
                            this.trigger('update'); 

                            // 3. GỌI SAVE CỦA ODOO
                            // Hàm này sẽ gom TOÀN BỘ thay đổi (cả dòng này và các dòng quét trước đó) gửi đi 1 lần.
                            // Không dùng orm.write riêng lẻ nữa!
                            await this.save(); 
                            
                            this._setSaving(false); 
                            return; // Chặn super
                        } catch (e) {
                            console.error("Save Error:", e);
                            alert("Lỗi lưu dữ liệu: " + e.message);
                            this._setSaving(null);
                        }
                    }
                }
            }

            // =============================================================
            // FALLBACK NORMAL SCAN
            // =============================================================
            await super.processBarcode(...arguments);

            // Auto Save (Đảm bảo các dòng quét thường cũng được lưu ngay)
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