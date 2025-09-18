
/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { PrintPreviewDialog } from "../widgets/print_preview_dialog";
import { browser } from "@web/core/browser/browser";

let wkhtmltopdfStateProm = null;

// Minimal helpers (avoid depending on web/reports/tools.esm)
const WARNING_MESSAGE = _t(
    "A popup window with your report was blocked. You " +
    "may need to change your browser settings to allow " +
    "popup windows for this page."
);
const WKHTMLTOPDF_MESSAGES = {
    broken: _t("Your installation of Wkhtmltopdf seems to be broken. The report will be shown in html.") ,
    install: _t("Unable to find Wkhtmltopdf on this system. The report will be shown in html."),
    upgrade: _t("You should upgrade your version of Wkhtmltopdf to at least 0.12.0 to print PDF correctly."),
    workers: _t("You need to start Odoo with at least two workers to print a PDF version of the reports."),
};

function getReportUrl(action, type, env) {
    const baseUrl = browser.location.origin;
    const URLCls = window.URL || window.webkitURL;
    const url = new URLCls(`/report/${type}/${action.report_name}`, baseUrl);

    const actionContext = action.context || {};
    if (actionContext.active_ids) {
        url.pathname += `/${actionContext.active_ids.join(",")}`;
    }
    if (action.data && JSON.stringify(action.data) !== "{}") {
        url.searchParams.set("options", encodeURIComponent(JSON.stringify(action.data)));
        url.searchParams.set("context", encodeURIComponent(JSON.stringify(actionContext)));
    } else {
        if (actionContext.allowed_company_ids) {
            const cid = actionContext.allowed_company_ids.join();
            url.searchParams.set("cid", cid);
        }
        if (type === "html") {
            url.searchParams.set("context", encodeURIComponent(JSON.stringify(env.services.user.context)));
        }
    }
    return url.toString();
}

// Open qweb-pdf reports inside a Dialog (no new tab)
registry.category("ir.actions.report handlers").add(
    "hlv_open_report_handler_dialog",
    async function (action, options, env) {
        if (action.type === "ir.actions.report" && action.report_type === "qweb-pdf") {
            if (!wkhtmltopdfStateProm) {
                wkhtmltopdfStateProm = rpc("/report/check_wkhtmltopdf");
            }
            const state = await wkhtmltopdfStateProm;
            if (state in WKHTMLTOPDF_MESSAGES) {
                env.services.notification.add(WKHTMLTOPDF_MESSAGES[state], {
                    sticky: true, title: _t("Report"),
                });
            }
            if (state !== "upgrade" && state !== "ok") {
                return false; // fallback elsewhere
            }

            const url = getReportUrl(action, "pdf", env);
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
