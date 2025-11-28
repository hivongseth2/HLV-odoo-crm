/** @odoo-module **/

// GỌI THEO DEFAULT_CODE (không dùng barcode)
const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_default_code_at_warehouse";

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
    /**
     * Kiểm tra xem qty_done có vượt quá demand không và highlight cảnh báo
     */
    try {
        const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
        if (!qtyEl) return;

        // Tìm phần tử hiển thị qty_done và demand
        const qtyText = qtyEl.textContent || "";
        const match = qtyText.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);

        if (!match) return;

        const qtyDone = parseFloat(match[1]) || 0;
        const demand = parseFloat(match[2]) || 0;

        // Nếu qty_done >= demand, highlight đỏ để cảnh báo
        if (qtyDone >= demand && demand > 0) {
            qtyEl.style.color = "#d9534f"; // Màu đỏ cảnh báo
            qtyEl.style.fontWeight = "bold";

            // Thêm icon warning nếu chưa có
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
            // Reset về màu bình thường
            qtyEl.style.color = "";
            qtyEl.style.fontWeight = "";
            const warningIcon = qtyEl.parentElement.querySelector(".hlv-warning-icon");
            if (warningIcon) warningIcon.remove();
        }
    } catch (e) {
        // Silent fail
    }
}

// Bắt prefix kho từ dòng hoặc header: TSN/Stock, KBC/Tồn kho, KHD/Tồn kho, kể cả có phần con
function detectWarehousePrefix(lineEl) {
    // 1) trong dòng (nếu layout có)
    const destText = lineEl.querySelector(".o_line_destination_location")?.innerText || "";
    let prefix = (destText.split("/")[0] || "").trim();
    if (["TSN", "KBC", "KHD"].includes(prefix)) return prefix;

    // 2) header/toàn trang
    const candidates = [
        document.querySelector(".o_barcode_container"),
        document.querySelector(".o-breadcrumb"),
        document.querySelector(".o_action_manager"),
        document.body,
    ];
    for (const el of candidates) {
        if (!el) continue;
        const txt = el.innerText || "";
        const m = txt.match(/\b(TSN|KBC|KHD)\s*\/\s*(Stock|Tồn kho)\b/i);
        if (m) return m[1].toUpperCase();
    }
    return null;
}

// Lấy default_code hiển thị trên dòng (span .o_product_code). Fallback: data-barcode (nếu cùng là mã tham chiếu).
function getDefaultCode(lineEl) {
    // trường hợp chuẩn
    let txt = lineEl.querySelector(".o_product_ref .o_product_code")?.textContent?.trim()
        || lineEl.querySelector(".o_product_code")?.textContent?.trim()
        || "";

    // fallback: nếu code dính chung text
    if (!txt) {
        const refText = lineEl.querySelector(".o_product_ref")?.textContent?.trim() || "";
        const m = refText.match(/^[A-Z0-9._-]+/i);
        if (m) txt = m[0];
    }
    return txt;                 // KHÔNG fallback sang data-barcode nữa
}

// ---- main ----
async function annotateLine(lineEl) {
    try {
        const defaultCode = getDefaultCode(lineEl);
        if (!defaultCode || lineEl.__hlv_done__) return;
        lineEl.__hlv_done__ = true;

        const whPrefix = detectWarehousePrefix(lineEl);          // TSN/KBC/KHD
        const result = await callKw(
            "stock.quant",
            "get_qty_by_default_code_at_warehouse",
            [defaultCode, whPrefix],
            {}
        );

        const labelPrefix = whPrefix || (result.base_location?.split("/")?.[0]) || "tổng";
        insertInline(lineEl, `tồn (${labelPrefix}): ${result.qty} ${result.uom}`);

        // Kiểm tra và highlight nếu qty_done >= demand
        checkAndHighlightOverflow(lineEl);
    } catch (e) {/* no-op */ }
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

            // Theo dõi thay đổi qty để update highlight real-time
            if (m.type === 'characterData' || m.type === 'childList') {
                const target = m.target instanceof HTMLElement ? m.target : m.target.parentElement;
                if (target && target.closest('.o_barcode_line')) {
                    const lineEl = target.closest('.o_barcode_line');
                    // Chỉ check highlight, không re-fetch stock qty
                    checkAndHighlightOverflow(lineEl);
                }
            }
        }
    });
    const waitBody = () => {
        if (document.body) {
            obs.observe(document.body, {
                childList: true,
                subtree: true,
                characterData: true  // Theo dõi thay đổi text trong qty element
            });
            window.__hlv_stock_inline_observer__ = obs;
            scanExisting();
        } else {
            requestAnimationFrame(waitBody);
        }
    };
    waitBody();
}

// ---- Intercept barcode scan để chặn khi qty đủ ----
function interceptBarcodeInput() {
    /**
     * Hook vào input barcode của Odoo để chặn quét khi qty_done >= demand
     */

    // Tìm barcode input element
    const findBarcodeInput = () => {
        // Odoo barcode app có thể dùng nhiều selector khác nhau
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

    // Kiểm tra xem sản phẩm có barcode này đã đủ qty chưa
    const checkIfProductFull = (barcode) => {
        if (!barcode) return false;

        // Tìm tất cả dòng có barcode này
        const lines = document.querySelectorAll('.o_barcode_line');

        for (const lineEl of lines) {
            // Kiểm tra barcode match (có thể cần normalize)
            const lineBarcode = lineEl.dataset.barcode ||
                                lineEl.querySelector('[data-barcode]')?.dataset.barcode;

            if (!lineBarcode || lineBarcode !== barcode) continue;

            // Lấy qty_done và demand
            const qtyEl = lineEl.querySelector(".o_barcode_scanner_qty");
            if (!qtyEl) continue;

            const qtyText = qtyEl.textContent || "";
            const match = qtyText.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);

            if (!match) continue;

            const qtyDone = parseFloat(match[1]) || 0;
            const demand = parseFloat(match[2]) || 0;

            // Nếu có bất kỳ dòng nào chưa đủ, cho phép quét
            if (qtyDone < demand) {
                return false;
            }
        }

        // Tất cả dòng đều đã đủ
        return true;
    };

    // Setup event listener với capture phase
    const setupInterceptor = () => {
        const input = findBarcodeInput();
        if (!input) {
            // Retry sau 500ms
            setTimeout(setupInterceptor, 500);
            return;
        }

        // Đánh dấu đã setup để tránh duplicate
        if (input.__hlv_interceptor_setup__) return;
        input.__hlv_interceptor_setup__ = true;

        console.log('[HLV] Barcode interceptor setup on:', input);

        // Intercept keydown event (trước khi Odoo xử lý)
        input.addEventListener('keydown', function(e) {
            if (e.key !== 'Enter') return;

            const barcode = input.value.trim();
            if (!barcode) return;

            // Kiểm tra xem sản phẩm có barcode này đã đủ qty chưa
            if (checkIfProductFull(barcode)) {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();

                // Clear input
                input.value = '';

                // Hiển thị notification
                showWarningNotification('⚠️ Sản phẩm này đã được quét đủ số lượng!');

                console.warn('[HLV] Blocked barcode scan - product already full:', barcode);

                return false;
            }
        }, true); // true = capture phase (chạy trước bubble phase)
    };

    setupInterceptor();
}

function showWarningNotification(message) {
    /**
     * Hiển thị thông báo cảnh báo trên UI
     */
    try {
        // Thử dùng Odoo notification service nếu có
        if (window.odoo && window.odoo.services && window.odoo.services.notification) {
            window.odoo.services.notification.notify({
                type: 'warning',
                title: 'Cảnh báo',
                message: message,
                sticky: false,
            });
            return;
        }

        // Fallback: Tạo toast notification đơn giản
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

        // Auto remove sau 3s
        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => toast.remove(), 300);
        }, 3000);

        // Play error sound nếu có
        try {
            const audio = new Audio('/custom_barcode_scan_redirect/static/src/sound/error.mp3');
            audio.play().catch(() => {});
        } catch (e) {}

    } catch (e) {
        // Fallback cuối cùng
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
    interceptBarcodeInput();  // Thêm interceptor
}
