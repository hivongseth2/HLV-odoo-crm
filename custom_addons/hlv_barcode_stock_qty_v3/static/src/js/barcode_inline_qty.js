/** @odoo-module **/

// GỌI THEO DEFAULT_CODE (không dùng barcode)
const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_default_code_at_warehouse";
// Method mới để check tồn kho real-time
const RPC_CHECK_METHOD = "check_barcode_availability"; 

// ---- utils ----
async function callKw(model, method, args = [], kwargs = {}) {
    const res = await fetch("/web/dataset/call_kw", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            jsonrpc: "2.0",
            method: "call",
            params: { model, method, args, kwargs },
            id: Date.now(),
        }),
    });
    const json = await res.json();
    if (json.error) throw json.error;
    return json.result;
}

function playErrorSound() {
    try {
        // Ưu tiên đường dẫn custom của bạn
        let audio = new Audio('/custom_barcode_scan_redirect/static/src/sound/error.mp3');
        audio.play().catch(() => {
            // Fallback sang âm thanh mặc định của Odoo
            new Audio('/web/static/src/sounds/error.mp3').play().catch(()=>{});
        });
    } catch (e) { }
}

function insertInline(lineEl, text) {
    const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
    if (!qtyEl) return;
    let badge = qtyEl.parentElement.querySelector(".hlv-inline-stock");
    if (!badge) {
        badge = document.createElement("small");
        badge.className = "hlv-inline-stock";
        badge.style.marginLeft = "8px";
        badge.style.fontSize = "12px";
        badge.style.color = "#0a7";
        qtyEl.parentElement.appendChild(badge);
    }
    badge.textContent = `| ${text}`;
}

function checkAndHighlightOverflow(lineEl) {
    try {
        const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
        if (!qtyEl) return;

        const qtyText = qtyEl.textContent || "";
        const match = qtyText.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);

        if (!match) return;

        const qtyDone = parseFloat(match[1]) || 0;
        const demand = parseFloat(match[2]) || 0;

        if (qtyDone >= demand && demand > 0) {
            qtyEl.style.color = "#d9534f";
            qtyEl.style.fontWeight = "bold";

            let warningIcon = qtyEl.parentElement.querySelector(".hlv-warning-icon");
            if (!warningIcon) {
                warningIcon = document.createElement("span");
                warningIcon.className = "hlv-warning-icon";
                warningIcon.textContent = " ⚠️";
                warningIcon.style.color = "#d9534f";
                warningIcon.title = "Đã đủ số lượng! Không được quét thêm.";
                qtyEl.parentElement.insertBefore(warningIcon, qtyEl.nextSibling);
            }
        } else {
            qtyEl.style.color = "";
            qtyEl.style.fontWeight = "";
            const warningIcon = qtyEl.parentElement.querySelector(".hlv-warning-icon");
            if (warningIcon) warningIcon.remove();
        }
    } catch (e) { }
}

// Bắt prefix kho: TSN, KBC, KHD
function detectWarehousePrefix(el = document.body) {
    // 1. Tìm trong dòng cụ thể (nếu có truyền lineEl)
    if (el.matches && el.matches('.o_barcode_line')) {
        const destText = el.querySelector(".o_line_destination_location")?.innerText || "";
        let prefix = (destText.split("/")[0] || "").trim();
        if (["TSN", "KBC", "KHD"].includes(prefix)) return prefix;
    }

    // 2. Tìm toàn trang (Header/Breadcrumb)
    const candidates = [
        document.querySelector(".o_barcode_container"),
        document.querySelector(".o-breadcrumb"),
        document.querySelector(".o_action_manager"),
        document.body,
    ];
    for (const c of candidates) {
        if (!c) continue;
        const txt = c.innerText || "";
        const m = txt.match(/\b(TSN|KBC|KHD)\s*\/\s*(Stock|Tồn kho)\b/i);
        if (m) return m[1].toUpperCase();
    }
    return null;
}

function getDefaultCode(lineEl) {
    let txt = lineEl.querySelector(".o_product_ref .o_product_code")?.textContent?.trim()
        || lineEl.querySelector(".o_product_code")?.textContent?.trim()
        || "";

    if (!txt) {
        const refText = lineEl.querySelector(".o_product_ref")?.textContent?.trim() || "";
        const m = refText.match(/^[A-Z0-9._-]+/i);
        if (m) txt = m[0];
    }
    return txt;
}

// ---- Observer & Annotate Lines ----
async function annotateLine(lineEl) {
    try {
        const defaultCode = getDefaultCode(lineEl);
        if (!defaultCode || lineEl.__hlv_done__) return;
        lineEl.__hlv_done__ = true;

        const whPrefix = detectWarehousePrefix(lineEl);
        const result = await callKw(
            RPC_MODEL,
            RPC_METHOD,
            [defaultCode, whPrefix],
            {}
        );

        const labelPrefix = whPrefix || (result.base_location?.split("/")?.[0]) || "tổng";
        insertInline(lineEl, `tồn (${labelPrefix}): ${result.qty} ${result.uom}`);

        checkAndHighlightOverflow(lineEl);
    } catch (e) { }
}

function scanExisting() {
    document.querySelectorAll(".o_barcode_line").forEach(annotateLine);
}

function setupObserver() {
    if (window.__hlv_stock_inline_observer__) return;
    const obs = new MutationObserver((mutations) => {
        for (const m of mutations) {
            m.addedNodes.forEach((node) => {
                if (!(node instanceof HTMLElement)) return;
                if (node.matches(".o_barcode_line")) annotateLine(node);
                node.querySelectorAll?.(".o_barcode_line").forEach(annotateLine);
            });

            if (m.type === 'characterData' || m.type === 'childList') {
                const target = m.target instanceof HTMLElement ? m.target : m.target.parentElement;
                if (target && target.closest('.o_barcode_line')) {
                    const lineEl = target.closest('.o_barcode_line');
                    checkAndHighlightOverflow(lineEl);
                }
            }
        }
    });
    
    const waitBody = () => {
        if (document.body) {
            obs.observe(document.body, { childList: true, subtree: true, characterData: true });
            window.__hlv_stock_inline_observer__ = obs;
            scanExisting();
        } else {
            requestAnimationFrame(waitBody);
        }
    };
    waitBody();
}

// ---- Intercept Barcode Scan ----
function interceptBarcodeInput() {
    const findBarcodeInput = () => {
        const selectors = [
            'input.o_barcode_input',
            'input[placeholder*="barcode"]',
            'input[placeholder*="Barcode"]',
            '.o_barcode_client_action input[type="text"]',
        ];
        for (const selector of selectors) {
            const input = document.querySelector(selector);
            if (input) return input;
        }
        return null;
    };

    // Check 1: Đã quét đủ số lượng chưa? (Client-side)
    const checkIfProductFull = (barcode) => {
        if (!barcode) return false;
        const lines = document.querySelectorAll('.o_barcode_line');

        for (const lineEl of lines) {
            const lineDefaultCode = getDefaultCode(lineEl);
            const lineBarcode = lineEl.dataset.barcode || lineEl.querySelector('[data-barcode]')?.dataset.barcode;

            if (lineDefaultCode !== barcode && lineBarcode !== barcode) continue;

            const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
            if (!qtyEl) continue;

            const qtyText = qtyEl.textContent || "";
            const match = qtyText.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);

            if (!match) continue;

            const qtyDone = parseFloat(match[1]) || 0;
            const demand = parseFloat(match[2]) || 0;

            if (demand > 0 && qtyDone >= demand) {
                return true; // Đã đủ -> Chặn
            }
        }
        return false;
    };

    const setupInterceptor = () => {
        const input = findBarcodeInput();
        if (!input) {
            setTimeout(setupInterceptor, 500);
            return;
        }

        if (input.__hlv_interceptor_setup__) return;
        input.__hlv_interceptor_setup__ = true;
        console.log('[HLV] Barcode interceptor setup on:', input);

        // Intercept Keydown
        input.addEventListener('keydown', async function (e) {
            if (e.key !== 'Enter') return;

            // Nếu cờ bypass được bật -> Đây là sự kiện do ta dispatch lại -> Cho qua
            if (input.dataset.hlvBypass === "true") {
                input.dataset.hlvBypass = ""; 
                return;
            }

            const barcode = input.value.trim();
            if (!barcode) return;

            // --- BƯỚC 1: CHẶN NGAY LẬP TỨC ---
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();

            // --- BƯỚC 2: CHECK CLIENT (Đủ số lượng chưa?) ---
            if (checkIfProductFull(barcode)) {
                input.value = '';
                showWarningNotification('⚠️ Sản phẩm này đã được quét đủ số lượng!');
                playErrorSound();
                return; 
            }

            // --- BƯỚC 3: CHECK SERVER (Có hàng không?) ---
            try {
                // Hiển thị hiệu ứng loading (mờ đi chút)
                input.style.opacity = "0.5";
                
                const whPrefix = detectWarehousePrefix(document.body);
                
                // Gọi RPC check availability
                const result = await callKw(
                    "stock.quant", 
                    RPC_CHECK_METHOD, 
                    [barcode, whPrefix]
                );
                
                input.style.opacity = "1";

                if (result.allow) {
                    // ==> CÓ HÀNG: Cho phép đi tiếp
                    input.dataset.hlvBypass = "true"; // Bật cờ bypass
                    
                    // Dispatch lại sự kiện Enter y hệt
                    const newEvent = new KeyboardEvent('keydown', {
                        key: 'Enter',
                        code: 'Enter',
                        keyCode: 13,
                        which: 13,
                        bubbles: true,
                        cancelable: true,
                        view: window
                    });
                    input.dispatchEvent(newEvent);

                } else {
                    // ==> HẾT HÀNG: Chặn và báo lỗi
                    input.value = '';
                    // Alert native của trình duyệt sẽ chặn đứng flow, buộc user phải đọc
                    alert(result.message); 
                    playErrorSound();
                }

            } catch (err) {
                console.error("[HLV] RPC Error:", err);
                // Nếu lỗi mạng, an toàn nhất là cho qua để không làm gián đoạn việc
                input.style.opacity = "1";
                input.dataset.hlvBypass = "true";
                const newEvent = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true });
                input.dispatchEvent(newEvent);
            }

        }, true); // Capture phase = true để bắt trước Odoo
    };

    setupInterceptor();
}

function showWarningNotification(message) {
    try {
        if (window.odoo && window.odoo.services && window.odoo.services.notification) {
            window.odoo.services.notification.notify({
                type: 'warning',
                title: 'Cảnh báo',
                message: message,
                sticky: false,
            });
            return;
        }

        const toast = document.createElement('div');
        toast.className = 'hlv-barcode-toast';
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #f0ad4e;
            color: white;
            padding: 15px 20px;
            border-radius: 5px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            z-index: 9999;
            font-size: 14px;
            font-weight: bold;
            animation: slideIn 0.3s ease-out;
        `;
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => toast.remove(), 300);
        }, 3000);

    } catch (e) {
        alert(message);
    }
}

// Add CSS animation
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);

if (location.pathname.includes("/odoo/barcode/")) {
    setupObserver();
    interceptBarcodeInput();
}