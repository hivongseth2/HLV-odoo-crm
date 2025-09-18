/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

let wkhtmltopdfStateProm = null;

function buildReportUrl(action) {
    const name = action.report_name;
    const ids = action.context?.active_ids;
    let url = `/report/pdf/${name}`;
    if (ids?.length) url += `/${ids.join(",")}`;
    if (action.data && Object.keys(action.data).length) {
        url += `?options=${encodeURIComponent(JSON.stringify(action.data))}`;
        url += `&context=${encodeURIComponent(JSON.stringify(action.context || {}))}`;
    } else if (action.context?.allowed_company_ids) {
        url += `?cid=${action.context.allowed_company_ids.join()}`;
    }
    return url;
}

registry.category("ir.actions.report handlers").add(
    "hlv_direct_print_iframe_fast_with_loading",
    async (action, options, env) => {
        if (action.type !== "ir.actions.report" || action.report_type !== "qweb-pdf") return false;

        // 1) show loading overlay
        const { ui, notification } = env.services;
        ui.block(); // spinner overlay

        try {
            // 2) wkhtmltopdf state
            if (!wkhtmltopdfStateProm) wkhtmltopdfStateProm = rpc("/report/check_wkhtmltopdf");
            const state = await wkhtmltopdfStateProm;
            if (!["ok", "upgrade"].includes(state)) {
                ui.unblock();
                return false;
            }

            // 3) create hidden iframe & print when loaded
            const url = buildReportUrl(action);
            const iframe = document.createElement("iframe");
            Object.assign(iframe.style, {
                position: "fixed", right: "0", bottom: "0",
                width: "0", height: "0", border: "0"
            });

            let cleanupTimer;
            const cleanup = () => {
                clearTimeout(cleanupTimer);
                iframe.remove();
                ui.unblock(); // hide spinner
            };

            iframe.onload = () => {
                try {
                    const w = iframe.contentWindow;
                    const after = () => { w.removeEventListener("afterprint", after); cleanup(); };
                    w.addEventListener("afterprint", after);
                    w.focus();
                    w.print();
                    // fallback if afterprint không bắn
                    cleanupTimer = setTimeout(cleanup, 10000);
                } catch (e) {
                    cleanup();
                    notification.add("Không thể tự động in: " + (e.message || e), { type: "warning" });
                }
            };

            iframe.src = url;        // ⚡ tải trực tiếp PDF (không fetch + blob)
            document.body.appendChild(iframe);
            return true;
        } catch (e) {
            ui.unblock();
            env.services.notification.add("Lỗi khi in PDF: " + (e.message || e), { type: "danger" });
            return true;
        }
    },
    { sequence: 4 }
);
