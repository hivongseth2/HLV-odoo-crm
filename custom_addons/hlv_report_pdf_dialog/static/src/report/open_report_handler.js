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
    "hlv_direct_print_iframe_fast",
    async (action, options, env) => {
        if (action.type !== "ir.actions.report" || action.report_type !== "qweb-pdf") return false;

        if (!wkhtmltopdfStateProm) wkhtmltopdfStateProm = rpc("/report/check_wkhtmltopdf");
        const state = await wkhtmltopdfStateProm;
        if (!["ok", "upgrade"].includes(state)) return false;

        const url = buildReportUrl(action);

        const iframe = document.createElement("iframe");
        Object.assign(iframe.style, {
            position: "fixed", right: "0", bottom: "0", width: "0", height: "0", border: "0",
        });

        const cleanup = () => iframe.remove();

        iframe.onload = () => {
            try {
                const w = iframe.contentWindow;
                const after = () => { w.removeEventListener("afterprint", after); cleanup(); };
                w.addEventListener("afterprint", after);
                w.focus();
                w.print();
                setTimeout(cleanup, 5000); // fallback dọn rác
            } catch { cleanup(); }
        };

        iframe.src = url;              // ⚡ tải thẳng PDF (không fetch + blob)
        document.body.appendChild(iframe);
        return true;
    },
    { sequence: 4 }
);
