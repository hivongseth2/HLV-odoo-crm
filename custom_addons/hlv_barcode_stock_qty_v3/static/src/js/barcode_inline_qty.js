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

// UI KHÓA MÀN HÌNH (QUAN TRỌNG ĐỂ CHỐNG QUÉT ĐÚP)
function toggleBlockingScreen(show) {
    let el = document.getElementById('hlv-blocking-screen');
    if (!el) {
        el = document.createElement('div');
        el.id = 'hlv-blocking-screen';
        el.style.cssText = "position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.6); z-index: 99999999; display: none; justify-content: center; align-items: center; flex-direction: column; color: white; font-family: system-ui;";
        el.innerHTML = `
            <div style="font-size: 40px; margin-bottom: 20px;">⏳</div>
            <div style="font-size: 24px; font-weight: bold;">ĐANG LƯU...</div>
            <div style="font-size: 16px; margin-top: 10px; color: #ffc107;">Vui lòng đợi lưu xong mới quét tiếp!</div>
        `;
        document.body.appendChild(el);
    }
    el.style.display = show ? 'flex' : 'none';
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
// MAIN LOGIC V21 - PRIORITY: LOCAL LINE > SOURCE LINE
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V21: LOCATION PRIORITY FIX");
        
        this.isLocked = false;

        // CHẶN F5 CỨNG
        window.addEventListener('beforeunload', (e) => {
            e.preventDefault();
            e.returnValue = 'DỮ LIỆU CÓ THỂ BỊ MẤT. ĐỪNG F5!';
            return 'DỮ LIỆU CÓ THỂ BỊ MẤT. ĐỪNG F5!';
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

    async processBarcode(barcode) {
        if (this.isLocked) {
            safePlaySound(this.env, 'error'); 
            return; 
        }

        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        this.isLocked = true;
        toggleBlockingScreen(true);

        try {
            // 1. NHẬN DIỆN
            const product = await this._identifyProductSafe(barcode);
            
            // 2. VỊ TRÍ HIỆN TẠI (NƠI ĐỨNG)
            let currentLoc = this.location;
            let currentLocId = currentLoc ? currentLoc.id : null;
            
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            if (product && this.currentState.lines) {
                const productLines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
                
                let totalDone = 0;
                let totalDemand = 0;
                
                // PHÂN LOẠI DÒNG:
                // - localLine: Dòng ĐANG Ở vị trí mình đứng (Tủ 3)
                // - sourceLine: Dòng ĐANG Ở kho nguồn (Tồn kho) chưa làm xong
                let localLine = null;
                let sourceLine = null;

                productLines.forEach(l => {
                    const d = parseFloat(l.qty_done || 0);
                    const r = parseFloat(getLineDemand(l));
                    totalDone += d;
                    totalDemand += r;
                    
                    const lineLocId = extractId(l.location_id);
                    
                    // Logic tìm dòng ưu tiên
                    if (currentLocId && lineLocId === currentLocId) {
                        // Đã có dòng ở Tủ 3 rồi -> Ưu tiên số 1 (cộng dồn vào đây)
                        localLine = l;
                    } else if (d < r) {
                        // Dòng ở chỗ khác chưa xong -> Ưu tiên số 2 (để chuyển kho)
                        sourceLine = l;
                    }
                });

                // 🛑 CHECK LIMIT (TÍNH TỔNG)
                if (totalDemand === 0) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ CHẶN NGOÀI KẾ HOẠCH!\n\nSP: ${product.display_name}`);
                    return;
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n\nSP: ${product.display_name}`);
                    return;
                }

                // 🌍 CHECK LOCATION
                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                        return;
                    }
                } catch (e) {
                    alert("Lỗi mạng!"); return;
                }

                // 🚀 SMART LOGIC V21 (QUAN TRỌNG)
                let targetLine = null;
                
                // ƯU TIÊN 1: Nếu đã có dòng ở Tủ 3 -> Chọn nó để cộng dồn
                if (localLine) {
                    console.log(`✅ [HLV] Found Existing Line at ${currentLocId} (ID: ${localLine.id}) -> Incrementing`);
                    targetLine = localLine;
                } 
                // ƯU TIÊN 2: Nếu chưa có -> Lấy dòng ở nguồn để chuyển qua
                else if (sourceLine && currentLocId) {
                    console.log(`✅ [HLV] No local line. Stealing from Source (ID: ${sourceLine.id}) -> Moving`);
                    targetLine = sourceLine;
                    // Đổi vị trí ngay
                    targetLine.location_id = currentLoc;
                }

                // THỰC HIỆN UPDATE
                if (targetLine) {
                    // Update RAM
                    targetLine.qty_done = (targetLine.qty_done || 0) + 1;
                    this.trigger('update');

                    // SAVE VÀ CHỜ KẾT QUẢ
                    await this.save();
                    
                    console.log("✅ Save Success");
                    return; // Xong
                }
            }

            // FALLBACK
            await super.processBarcode(...arguments);
            await this.save();

        } catch (err) {
            console.error(err);
            alert("Lỗi: " + err.message);
        } finally {
            this.isLocked = false;
            toggleBlockingScreen(false);
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