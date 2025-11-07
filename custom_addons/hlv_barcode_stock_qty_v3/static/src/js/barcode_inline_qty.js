/** @odoo-module **/

const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_default_code_at_warehouse";

async function callKw(model, method, args = [], kwargs = {}) {
    const res = await fetch("/web/dataset/call_kw", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            jsonrpc: "2.0", method: "call",
            params: { model, method, args, kwargs }, id: Date.now()
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

// BẮT prefix từ dòng: support 'TSN/Stock', 'KBC/Tồn kho', 'KBC/Tồn kho/D8-T4', ...
function detectWarehousePrefix(lineEl) {
    const text = lineEl.querySelector(".o_line_destination_location")?.innerText || "";
    // lấy phần trước dấu '/'
    let prefix = (text.split("/")[0] || "").trim();
    // fallback: dò trong toàn bộ text của dòng xem có chuỗi bắt đầu bằng TSN/KBC/KHD
    if (!prefix) {
        const full = lineEl.innerText || "";
        const m = full.match(/\b(TSN|KBC|KHD)\s*\//i);
        if (m) prefix = m[1].toUpperCase();
    }
    if (["TSN", "KBC", "KHD"].includes(prefix)) return prefix;
    return null; // để backend fallback 'tổng' nếu không đọc được
}

// Lấy default_code hiển thị trên dòng (span .o_product_code). Fallback: data-barcode.
function getDefaultCode(lineEl) {
    const codeText = lineEl.querySelector(".o_product_code")?.textContent?.trim();
    return codeText || lineEl.getAttribute("data-barcode") || "";
}

async function annotateLine(lineEl) {
    try {
        const code = getDefaultCode(lineEl);
        if (!code || lineEl.__hlv_done__) return;
        lineEl.__hlv_done__ = true;

        const whPrefix = detectWarehousePrefix(lineEl); // 'TSN' / 'KBC' / 'KHD'
        const result = await callKw(RPC_MODEL, RPC_METHOD, [code, whPrefix], {});

        // Hiển thị theo prefix đã bắt (ưu tiên), nếu không có thì rơi về base_location/tổng
        const labelPrefix = whPrefix || (result.base_location?.split("/")?.[0]) || "tổng";
        insertInline(lineEl, `tồn (${labelPrefix}): ${result.qty} ${result.uom}`);
    } catch (e) {
        // im lặng để không phá UI
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
