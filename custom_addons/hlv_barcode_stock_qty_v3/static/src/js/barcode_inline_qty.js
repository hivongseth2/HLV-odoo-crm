/** @odoo-module **/

// RPC gọi theo default_code
const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_default_code_at_warehouse";

// RPC helper
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

// Gắn badge | tồn: ...
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

// Lấy prefix kho từ dòng: "TSN/Khu vực đóng gói" -> "TSN"
function detectWarehousePrefix(lineEl) {
    const destText = lineEl.querySelector(".o_line_destination_location")?.innerText?.trim() || "";
    const prefix = destText.split("/")[0]?.trim();
    if (prefix) return prefix;

    // fallback yếu (ít khi cần): scan 1 node có dạng "<PREFIX>/..."
    const anySlashNode = Array.from(document.querySelectorAll("body *"))
        .find((n) => n.childNodes?.length === 1 && typeof n.innerText === "string" && n.innerText.includes("/"));
    return anySlashNode ? anySlashNode.innerText.split("/")[0].trim() : null;
}

// Annotate 1 dòng
async function annotateLine(lineEl) {
    try {
        // Ở màn Barcode Odoo, thuộc tính data-barcode thường chính là barcode;
        // nhưng theo yêu cầu ta coi nó là default_code (mã tham chiếu).
        const defaultCode = lineEl.getAttribute("data-barcode");
        if (!defaultCode || lineEl.__hlv_done__) return;
        lineEl.__hlv_done__ = true;

        const whPrefix = detectWarehousePrefix(lineEl); // TSN/KBC/KHD...
        const result = await callKw(RPC_MODEL, RPC_METHOD, [defaultCode, whPrefix], {});
        if (result && !result.error) {
            const labelPrefix = result.warehouse_prefix ||
                (result.base_location?.split("/")?.[0]) || "tổng";
            insertInline(lineEl, `tồn (${labelPrefix}): ${result.qty} ${result.uom}`);
        } else {
            // insertInline(lineEl, "không tìm thấy");
        }
    } catch (e) {
        // console.debug("HLV annotate error:", e);
    }
}

// Quét các dòng sẵn có
function scanExisting() {
    document.querySelectorAll(".o_barcode_line[data-barcode]").forEach(annotateLine);
}

// Theo dõi dòng mới quét
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

// Chỉ chạy ở app Barcode
if (location.pathname.includes("/odoo/barcode/")) {
    setupObserver();
}
