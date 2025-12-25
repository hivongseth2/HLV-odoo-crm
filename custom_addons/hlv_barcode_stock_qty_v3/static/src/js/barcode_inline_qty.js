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

// UI: MÀN HÌNH CHỜ (BLOCK UI)
function toggleBusyScreen(busy) {
    let el = document.getElementById('hlv-busy-screen');
    if (!el) {
        el = document.createElement('div');
        el.id = 'hlv-busy-screen';
        el.style.cssText = "position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.3); z-index: 9999999; display: none; justify-content: center; align-items: center; color: white; font-size: 20px; font-weight: bold; flex-direction: column;";
        el.innerHTML = '<div>⏳ ĐANG LƯU... VUI LÒNG ĐỢI...</div><div style="font-size:14px; margin-top:10px">Không quét tiếp cho đến khi thông báo này tắt</div>';
        document.body.appendChild(el);
    }
    el.style.display = busy ? 'flex' : 'none';
}

// UI: NÚT KÍCH HOẠT CHẶN F5
function showF5Activator() {
    let el = document.getElementById('hlv-f5-lock');
    if (!el) {
        el = document.createElement('div');
        el.id = 'hlv-f5-lock';
        el.style.cssText = "position: fixed; top: 0; left: 0; width: 100%; height: 30px; background: #fd7e14; color: white; text-align: center; line-height: 30px; z-index: 999999; cursor: pointer; font-weight: bold;";
        el.innerText = "⚠️ BẤM VÀO ĐÂY ĐỂ BẬT CHẾ ĐỘ CHẶN F5";
        
        el.onclick = () => {
            el.style.backgroundColor = "#28a745";
            el.innerText = "🛡️ ĐÃ BẬT BẢO VỆ F5";
            setTimeout(() => { el.style.display = 'none'; }, 2000);
        };
        document.body.appendChild(el);
    }
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
        console.log("🚀 [HLV] V17: LOCK PROCESSING + ALWAYS BLOCK F5");
        
        this.isProcessing = false; // Cờ khóa xử lý (Tránh bắn 2 phát dồn dập)

        // 1. LUÔN LUÔN CHẶN F5 (Vĩnh viễn)
        window.onbeforeunload = (e) => {
            e = e || window.event;
            const msg = "DỮ LIỆU CÓ THỂ BỊ MẤT! BẠN CÓ CHẮC MUỐN TẢI LẠI?";
            if (e) e.returnValue = msg;
            return msg;
        };

        // 2. Hiện nút kích hoạt
        setTimeout(showF5Activator, 1000);

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
        // 0. NẾU ĐANG XỬ LÝ CÁI CŨ -> CHẶN CÁI MỚI NGAY
        if (this.isProcessing) {
            console.warn("🚫 [HLV] Ignored scan because previous one is saving...");
            safePlaySound(this.env, 'error'); // Bíp lỗi để biết là chưa nhận
            return; 
        }

        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        // BẬT KHÓA (Hiện màn hình chờ)
        this.isProcessing = true;
        toggleBusyScreen(true);

        try {
            // --- NHẬN DIỆN ---
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
                    // MỞ KHÓA
                    this.isProcessing = false; toggleBusyScreen(false);
                    return;
                }
                if (totalDone >= totalDemand) {
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!\n\nSP: ${product.display_name}`);
                    // MỞ KHÓA
                    this.isProcessing = false; toggleBusyScreen(false);
                    return;
                }

                // 🌍 CHECK 2: SERVER
                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n\n${result.message || "Không có hàng ở đây!"}`);
                        // MỞ KHÓA
                        this.isProcessing = false; toggleBusyScreen(false);
                        return;
                    }
                } catch (e) {
                    alert("Lỗi kết nối Server!");
                    this.isProcessing = false; toggleBusyScreen(false);
                    return;
                }

                // 🚀 CHECK 3: SMART MOVE & SAVE
                if (candidateLine && currentLocId) {
                    const lineLocId = extractId(candidateLine.location_id);
                    if (lineLocId !== currentLocId) {
                        console.log(`✅ [HLV] Smart Move: ${lineLocId} -> ${currentLocId}`);
                        
                        // Update RAM
                        candidateLine.location_id = currentLoc; 
                        candidateLine.qty_done = (candidateLine.qty_done || 0) + 1;
                        this.trigger('update');

                        // Update DB (Await kỹ càng)
                        await this.save();
                        
                        console.log("✅ Save Complete");
                        // MỞ KHÓA
                        this.isProcessing = false; toggleBusyScreen(false);
                        return; // CHẶN SUPER
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
            // LUÔN LUÔN MỞ KHÓA DÙ CÓ LỖI HAY KHÔNG
            // Để tránh treo máy
            this.isProcessing = false;
            toggleBusyScreen(false);
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