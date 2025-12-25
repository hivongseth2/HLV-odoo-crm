/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
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
    return 0;
}

// THANH TRẠNG THÁI (VISUAL STATUS BAR)
function updateSaveStatusUI(status) {
    let el = document.getElementById('hlv-save-status');
    if (!el) {
        el = document.createElement('div');
        el.id = 'hlv-save-status';
        // Thanh trạng thái nằm trên cùng, z-index cao nhất
        el.style.cssText = "position: fixed; top: 0; left: 0; width: 100%; height: 0px; z-index: 999999; transition: all 0.2s ease-in-out; text-align: center; color: white; font-weight: bold; line-height: 25px; font-size: 14px; overflow: hidden;";
        document.body.appendChild(el);
    }
    
    if (status === 'saving') {
        el.style.backgroundColor = '#d9534f'; // ĐỎ
        el.style.height = '30px';
        el.innerText = "💾 ĐANG LƯU... ĐỪNG F5!!!";
    } else if (status === 'success') {
        el.style.backgroundColor = '#28a745'; // XANH
        el.style.height = '30px';
        el.innerText = "✅ ĐÃ LƯU XONG";
        setTimeout(() => { el.style.height = '0px'; }, 1500);
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
// MAIN LOGIC
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V13: MANUAL UPDATE FIX + F5 BLOCKER");
        
        this.isSavingData = false; // Biến cờ theo dõi trạng thái lưu

        // 1. Gắn sự kiện chặn F5 (Dùng window object trực tiếp)
        window.onbeforeunload = (e) => {
            if (this.isSavingData) {
                const msg = "Dữ liệu đang được lưu! Nếu bạn tải lại trang bây giờ, dữ liệu sẽ bị MẤT.";
                e = e || window.event;
                if (e) e.returnValue = msg;
                return msg;
            }
        };

        // 2. Observer vẽ Inline Stock
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

    // Hàm set trạng thái
    _setSaving(state) {
        this.isSavingData = state;
        updateSaveStatusUI(state ? 'saving' : (state === false ? 'success' : 'idle'));
    },

    async processBarcode(barcode) {
        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // Bật trạng thái đang xử lý -> Chặn F5 ngay lập tức
        this._setSaving(true);

        try {
            // --- NHẬN DIỆN ---
            const product = await this._identifyProductSafe(barcode);
            
            let currentLoc = this.location; // Object vị trí hiện tại
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
                // Fallback nếu đủ hết thì lấy dòng cuối
                if (!candidateLine && productLines.length > 0) candidateLine = productLines[productLines.length - 1];

                // --- CHECK 1: LIMIT ---
                const isUnplanned = (totalDemand === 0);
                if (isUnplanned) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ CHẶN NGOÀI KẾ HOẠCH!\n\nSản phẩm: ${product.display_name}`);
                    this._setSaving(null); // Tắt cờ
                    return;
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n\nSản phẩm: ${product.display_name}\nTiến độ: ${totalDone}/${totalDemand}`);
                    this._setSaving(null);
                    return;
                }

                // --- CHECK 2: SERVER LOCATION ---
                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                        this._setSaving(null);
                        return;
                    }
                } catch (e) {
                    alert("Lỗi kết nối server!");
                    this._setSaving(null);
                    return;
                }

                // --- CHECK 3: SMART MOVE & UPDATE (LOGIC V13 - MANUAL RAM UPDATE) ---
                if (candidateLine && currentLocId) {
                    const lineLocId = extractId(candidateLine.location_id);
                    // Nếu khác vị trí -> Thực hiện update
                    if (lineLocId !== currentLocId) {
                        console.log(`✅ [HLV] Smart Move (Manual Fix): ${lineLocId} -> ${currentLocId}`);
                        
                        try {
                            // 1. Cập nhật dữ liệu trực tiếp vào RAM (Thay thế hàm _updateLine bị thiếu)
                            candidateLine.qty_done = (candidateLine.qty_done || 0) + 1;
                            
                            // Quan trọng: Gán object location đầy đủ để Odoo hiện đúng tên
                            candidateLine.location_id = currentLoc; 

                            // 2. Kích hoạt Odoo vẽ lại màn hình ngay (để người dùng thấy số nhảy)
                            this.trigger('update'); 

                            // 3. Gọi Save tổng để đồng bộ xuống DB
                            // Hàm này sẽ tự đọc dữ liệu từ RAM (đã sửa ở bước 1) để gửi đi
                            await this.save();
                            
                            this._setSaving(false); // Xong -> Xanh
                            return; // Done -> Chặn super
                        } catch (e) {
                            console.error("Smart Move Error:", e);
                            this._setSaving(null);
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
                 this._setSaving(false); // Xanh
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