
/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { WARNING_MESSAGE, WKHTMLTOPDF_MESSAGES, _getReportUrl } from "@web/../addons/web/static/src/reports/tools.esm.js";
import { PrintPreviewDialog } from "../widgets/print_preview_dialog";

let wkhtmltopdfStateProm = null;

registry.category("ir.actions.report handlers").add(
    "hlv_open_report_handler_dialog",
    async function (action, options, env) {
        if (action.type === "ir.actions.report" && action.report_type === "qweb-pdf") {
            if (!wkhtmltopdfStateProm) {
                wkhtmltopdfStateProm = rpc("/report/check_wkhtmltopdf");
            }
            const state = await wkhtmltopdfStateProm;
            if (state in WKHTMLTOPDF_MESSAGES) {
                env.services.notification.add(WKHTMLTOPDF_MESSAGES[state], { sticky: true, title: _t("Report") });
            }
            if (state !== "upgrade" && state !== "ok") {
                return false;
            }

            const url = _getReportUrl(action, "pdf", env);
            try {
                const resp = await fetch(url, { credentials: "same-origin" });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const blob = await resp.blob();
                const blobUrl = URL.createObjectURL(blob);
                env.services.dialog.add(PrintPreviewDialog, {
                    title: action.name || _t("Print Preview"),
                    url: blobUrl,
                    filename: (action.report_name || "report") + ".pdf",
                });
            } catch (e) {
                env.services.notification.add(WARNING_MESSAGE + " (" + (e.message || e) + ")", { type: "warning" });
            }
            return true;
        }
        return false;
    },
    { sequence: 5 }
);
