/** @odoo-module **/

// ==== CẤU HÌNH NHẸ ====
// Đổi sang "available_quantity" nếu muốn tồn khả dụng thay vì tổng quantity
const RPC_MODEL = "stock.quant";
const RPC_METHOD = "get_qty_by_barcode"; // bạn đang có sẵn ở backend
const MAX_RETRY = 5;

// Gọi JSON-RPC trực tiếp (không phụ thuộc env/services) => chạy chắc chắn trên /odoo/barcode/...
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

// Chèn/ cập nhật "| tồn: X UoM" ngay sau số lượng (0/1 …)
function insertInline(lineEl, text) {
    // lineEl = .o_barcode_line[data-barcode=...]
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
    badge.textContent = `| tồn: ${text}`;
}

// Annotate 1 dòng theo barcode
async function annotateLine(lineEl, tries = 0) {
    try {
        const barcode = lineEl.getAttribute("data-barcode");
        if (!barcode || lineEl.__hlv_done__) return;
        lineEl.__hlv_done__ = true; // tránh gọi lặp vô hạn

        const result = await callKw(RPC_MODEL, RPC_METHOD, [barcode], {});
        if (result && !result.error) {
            insertInline(lineEl, `${result.qty} ${result.uom}`);
        } else {
            // Nếu muốn hiển thị không tìm thấy, bỏ comment dòng dưới
            // insertInline(lineEl, "không tìm thấy");
        }
    } catch (e) {
        // DOM chưa sẵn sàng? chờ thêm chút rồi thử lại tối đa MAX_RETRY lần
        if (tries < MAX_RETRY) {
            setTimeout(() => annotateLine(lineEl, tries + 1), 150);
        } else {
            // console.debug("HLV annotate error:", e);
        }
    }
}

// Quét các dòng đang có sẵn khi vừa mở màn hình
function scanExisting() {
    document
        .querySelectorAll(".o_barcode_line[data-barcode]")
        .forEach((el) => annotateLine(el));
}

// Theo dõi DOM: khi có dòng mới (vừa quét) thì annotate ngay
function setupObserver() {
    if (window.__hlv_stock_inline_observer__) return;
    const obs = new MutationObserver((mutations) => {
        for (const m of mutations) {
            if (m.type === "childList") {
                m.addedNodes.forEach((node) => {
                    if (node.nodeType !== 1) return;
                    if (node.matches?.(".o_barcode_line[data-barcode]")) {
                        annotateLine(node);
                    } else {
                        node
                            .querySelectorAll?.(".o_barcode_line[data-barcode]")
                            .forEach((el) => annotateLine(el));
                    }
                });
            }
        }
    });
    obs.observe(document.body, { childList: true, subtree: true });
    window.__hlv_stock_inline_observer__ = obs;
}

// Chỉ chạy trên trang Barcode
if (location.pathname.includes("/odoo/barcode/")) {
    console.log("[HLV] barcode_inline_qty.js LOADED", location.pathname);
    // Khởi động
    setupObserver();
    // Quét các dòng có sẵn sau khi trang dựng xong
    window.requestAnimationFrame(() => setTimeout(scanExisting, 300));
}
