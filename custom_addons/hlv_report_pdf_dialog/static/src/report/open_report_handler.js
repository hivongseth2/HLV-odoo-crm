/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

let wkhtmltopdfStateProm = null;

function buildReportUrl(action) {
    const name = action.report_name;
    const ids = action.context?.active_ids;
    let url = `/report/pdf/${name}`;
    if (ids && ids.length) url += `/${ids.join(",")}`;
    if (action.data && Object.keys(action.data).length) {
        url += `?options=${encodeURIComponent(JSON.stringify(action.data))}`;
        url += `&context=${encodeURIComponent(JSON.stringify(action.context || {}))}`;
    } else if (action.context?.allowed_company_ids) {
        url += `?cid=${action.context.allowed_company_ids.join()}`;
    }
    return url;
}

registry.category("ir.actions.report handlers").add(
    "hlv_direct_print_no_tab",
    async (action, options, env) => {
        if (action.type !== "ir.actions.report" || action.report_type !== "qweb-pdf") {
            return false;
        }

        // 1) Kiểm tra wkhtmltopdf
        if (!wkhtmltopdfStateProm) wkhtmltopdfStateProm = rpc("/report/check_wkhtmltopdf");
        const state = await wkhtmltopdfStateProm;
        if (!["ok", "upgrade"].includes(state)) return false;

        // 2) Lấy PDF dưới dạng blob
        const url = buildReportUrl(action);
        let blobUrl;
        try {
            const resp = await fetch(url, { credentials: "same-origin" });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const blob = await resp.blob();
            blobUrl = URL.createObjectURL(blob);
        } catch (e) {
            env.services.notification.add(_t("Không thể tải PDF để in: ") + (e.message || e), { type: "danger" });
            return true;
        }

        // 3) Tạo iframe ẩn, gắn src = blobUrl rồi gọi print() khi load xong
        const iframe = document.createElement("iframe");
        iframe.style.position = "fixed";
        iframe.style.right = "0";
        iframe.style.bottom = "0";
        iframe.style.width = "0";
        iframe.style.height = "0";
        iframe.style.border = "0";
        iframe.src = blobUrl;

        const cleanup = () => {
            try { URL.revokeObjectURL(blobUrl); } catch { }
            iframe.remove();
        };

        iframe.onload = () => {
            try {
                const w = iframe.contentWindow;
                if (!w) throw new Error("no iframe contentWindow");
                // đóng gói cleanup sau khi in
                const after = () => { w.removeEventListener("afterprint", after); cleanup(); };
                w.addEventListener("afterprint", after);
                w.focus();
                w.print();
                // Một số trình duyệt không gọi afterprint → fallback cleanup
                setTimeout(() => cleanup(), 5000);
            } catch (e) {
                cleanup();
                env.services.notification.add(_t("Trình duyệt chặn lệnh in tự động. Hãy bật cho phép in hoặc dùng nút Tải PDF."), { type: "warning" });
            }
        };

        document.body.appendChild(iframe);
        return true; // đã xử lý action
    },
    { sequence: 4 } // Ưu tiên cao hơn handler mở dialog/tab
);
