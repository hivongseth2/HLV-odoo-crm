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
    const codeText = lineEl.querySelector(".o_product_code")?.textContent?.trim();
    return codeText || lineEl.getAttribute("data-barcode") || "";
}

// ---- main ----
async function annotateLine(lineEl) {
    try {
        const defaultCode = getDefaultCode(lineEl);
        if (!defaultCode || lineEl.__hlv_done__) return;
        lineEl.__hlv_done__ = true;

        const whPrefix = detectWarehousePrefix(lineEl); // 'TSN' / 'KBC' / 'KHD' (có thể null)
        const result = await callKw(RPC_MODEL, RPC_METHOD, [defaultCode, whPrefix], {});
        const labelPrefix = whPrefix || (result.base_location?.split("/")?.[0]) || "tổng";
        insertInline(lineEl, `tồn (${labelPrefix}): ${result.qty} ${result.uom}`);
    } catch (e) {
        // im lặng
    }
}

function scanExisting() {
    document.querySelectorAll(".o_barcode_line[data-barcode]").forEach(annotateLine);
}

function setupObserver() {
    if (window.__hlv_stock_inline_observer__) return;
    const obs = new MutationObserver((mutations) => {
        for (const m of mutations) {
            m.addedNodes.forEach((node) => {
                if (!(node instanceof HTMLElement)) return;
                if (node.matches(".o_barcode_line[data-barcode]")) annotateLine(node);
                node.querySelectorAll?.(".o_barcode_line[data-barcode]").forEach(annotateLine);
            });
        }
    });
    const waitBody = () => {
        if (document.body) {
            obs.observe(document.body, { childList: true, subtree: true });
            window.__hlv_stock_inline_observer__ = obs;
            scanExisting();
        } else {
            requestAnimationFrame(waitBody);
        }
    };
    waitBody();
}

if (location.pathname.includes("/odoo/barcode/")) {
    setupObserver();
}
