/** @odoo-module **/

const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_barcode_at_warehouse";

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

// LẤY PREFIX KHO từ dòng: 'TSN/Khu vực đóng gói' -> 'TSN'
function detectWarehousePrefix(lineEl) {
    const destText = lineEl.querySelector(".o_line_destination_location")?.innerText?.trim() || "";
    const prefix = destText.split("/")[0]?.trim();
    if (prefix) return prefix;

    // Fallback: tìm chuỗi đầu tiên chứa dấu '/' ở header
    const anySlashNode = Array.from(document.querySelectorAll("body *"))
        .find(n => n.childNodes?.length === 1 && typeof n.innerText === "string" && n.innerText.includes("/"));
    return anySlashNode ? anySlashNode.innerText.split("/")[0].trim() : null;
}

async function annotateLine(lineEl) {
    try {
        const barcode = lineEl.getAttribute("data-barcode");
        if (!barcode || lineEl.__hlv_done__) return;
        lineEl.__hlv_done__ = true;

        const whPrefix = detectWarehousePrefix(lineEl); // TSN/KBC/KHD
        const result = await callKw(RPC_MODEL, RPC_METHOD, [barcode, whPrefix], {});
        if (result && !result.error) {
            const labelPrefix = result.warehouse_prefix || (result.base_location?.split("/")?.[0]) || "tổng";
            insertInline(lineEl, `tồn (${labelPrefix}): ${result.qty} ${result.uom}`);
        }
    } catch (e) {
        // console.debug("HLV annotate error:", e);
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
