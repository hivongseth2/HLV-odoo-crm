/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

let wkhtmltopdfStateProm = null;

registry.category("ir.actions.report handlers").add(
    "hlv_direct_print_handler",
    async function (action, options, env) {
        if (action.type === "ir.actions.report" && action.report_type === "qweb-pdf") {
            if (!wkhtmltopdfStateProm) {
                wkhtmltopdfStateProm = rpc("/report/check_wkhtmltopdf");
            }
            const state = await wkhtmltopdfStateProm;
            if (state !== "upgrade" && state !== "ok") return false;

            const url = `/report/pdf/${action.report_name}${action.context?.active_ids ? '/' + action.context.active_ids.join(",") : ''}`;
            try {
                const resp = await fetch(url, { credentials: "same-origin" });
                const blob = await resp.blob();
                const blobUrl = URL.createObjectURL(blob);

                // mở cửa sổ mới chứa PDF và auto in
                const win = window.open(blobUrl);
                if (win) {
                    win.onload = () => {
                        win.focus();
                        win.print();
                    };
                } else {
                    env.services.notification.add(_t("Trình duyệt đã chặn popup in."), { type: "warning" });
                }
            } catch (e) {
                env.services.notification.add(_t("Không thể in PDF: ") + e.message, { type: "danger" });
            }
            return true;
        }
        return false;
    },
    { sequence: 5 }
);
