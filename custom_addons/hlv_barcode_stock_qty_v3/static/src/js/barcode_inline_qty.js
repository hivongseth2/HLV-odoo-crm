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

// BLOCKING UI
function toggleBlockingScreen(show) {
    let el = document.getElementById('hlv-blocking-screen');
    if (!el) {
        el = document.createElement('div');
        el.id = 'hlv-blocking-screen';
        el.style.cssText = "position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.6); z-index: 99999999; display: none; justify-content: center; align-items: center; flex-direction: column; color: white; font-family: system-ui;";
        el.innerHTML = `
            <div style="font-size: 40px; margin-bottom: 20px;">⏳</div>
            <div style="font-size: 24px; font-weight: bold;">ĐANG LƯU...</div>
            <div style="font-size: 16px; margin-top: 10px; color: yellow;">Vui lòng đợi thông báo này tắt hẳn!</div>
        `;
        document.body.appendChild(el);
    }
    el.style.display = show ? 'flex' : 'none';
}

async function renderInlineStock(lineEl, orm) {
    // (Giữ nguyên logic vẽ inline stock để không làm rối log)
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
// MAIN LOGIC (V20 - DEBUGGER)
// =============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);
        console.log("🚀 [HLV] V20: DEBUG MODE ENABLED");
        this.isLocked = false;

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
            console.warn("🚫 [HLV] SKIPPED: System is locked saving previous item.");
            safePlaySound(this.env, 'error'); 
            return; 
        }

        if (!barcode || barcode.startsWith("O-CMD")) return super.processBarcode(...arguments);

        console.group(`⚡ [HLV] SCAN START: ${barcode}`);
        this.isLocked = true;
        toggleBlockingScreen(true);

        try {
            // 1. LOG STATE BEFORE
            console.log("📊 State Before Scan:", {
                lines_count: this.currentState.lines.length,
                location: this.location
            });

            const product = await this._identifyProductSafe(barcode);
            console.log("📦 Identified Product:", product ? product.display_name : "NULL");

            // Info Vị trí
            let currentLoc = this.location;
            let currentLocId = currentLoc ? currentLoc.id : null;
            let checkLocId = currentLocId || (this.record.location_id ? extractId(this.record.location_id) : null);
            let locName = (currentLoc?.display_name || this.record?.display_name || "");
            let whPrefix = (locName.match(/\b(TSN|KBC|KHD)\b/i) || [])[1]?.toUpperCase();

            console.log("📍 Location Info:", { currentLocId, checkLocId, whPrefix });

            if (product && this.currentState.lines) {
                const productLines = this.currentState.lines.filter(l => extractId(l.product_id) === product.id);
                console.log("🔎 Found Lines for Product:", JSON.parse(JSON.stringify(productLines))); // Deep copy log

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
                
                // Fallback line cuối
                if (!candidateLine && productLines.length > 0) candidateLine = productLines[productLines.length - 1];

                console.log("🧮 Stats:", { totalDone, totalDemand });
                console.log("🎯 Candidate Line:", candidateLine ? JSON.parse(JSON.stringify(candidateLine)) : "NONE");

                // --- CHECKS ---
                if (totalDemand === 0) {
                    console.error("⛔ BLOCK: Unplanned");
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ CHẶN NGOÀI KẾ HOẠCH!`);
                    return;
                }
                if (totalDone >= totalDemand) {
                    console.error("⛔ BLOCK: Over Limit");
                    safePlaySound(this.env, 'error');
                    alert(`⚠️ ĐÃ ĐỦ SỐ LƯỢNG!`);
                    return;
                }

                // Check Server
                console.log("📡 Calling check_barcode_availability...");
                try {
                    const result = await this.orm.call("stock.quant", "check_barcode_availability", [barcode, whPrefix, checkLocId]);
                    console.log("📩 Server Result:", result);
                    if (result && result.allow === false) {
                        safePlaySound(this.env, 'error');
                        alert(`⛔ SAI VỊ TRÍ!\n${result.message}`);
                        return;
                    }
                } catch (e) {
                    console.error("❌ Network Error:", e);
                    alert("Lỗi mạng!");
                    return;
                }

                // --- ACTION ---
                if (candidateLine && currentLocId) {
                    const lineLocId = extractId(candidateLine.location_id);
                    if (lineLocId !== currentLocId) {
                        console.log(`✅ [HLV] SMART MOVE DETECTED`);
                        console.log(`   From: ${lineLocId} -> To: ${currentLocId}`);
                        console.log(`   Old Qty: ${candidateLine.qty_done}`);

                        // MUTATE RAM
                        candidateLine.location_id = currentLoc;
                        candidateLine.qty_done = (candidateLine.qty_done || 0) + 1;
                        
                        console.log(`   New Qty (RAM): ${candidateLine.qty_done}`);
                        
                        this.trigger('update');

                        console.log("💾 Calling SAVE()...");
                        await this.save();
                        console.log("✅ SAVE FINISHED.");
                        
                        // LOG STATE AFTER SAVE
                        const lineAfter = this.currentState.lines.find(l => l.id === candidateLine.id);
                        console.log("📊 Line State After Save:", JSON.parse(JSON.stringify(lineAfter)));

                        return;
                    }
                }
            }

            // FALLBACK
            console.log("⚠️ Fallback to super.processBarcode");
            await super.processBarcode(...arguments);
            console.log("💾 Auto Saving (Fallback)...");
            await this.save();
            console.log("✅ Auto Save Finished");

        } catch (err) {
            console.error("❌ CRASH:", err);
            alert("Lỗi: " + err.message);
        } finally {
            console.log("🔓 Unlocking UI");
            console.groupEnd();
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