/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";
import { sendToPrinter, parseContentDisposition, removeExtension } from "../network/download";
import { _t } from "@web/core/l10n/translation";

const regex = /\/account\/download_invoice_documents\/(\d+(,\d+)*)\/pdf/;

patch(browser, {
    /**
     * @param {String} url
     */
    set location(url) {
        const match = url.match(regex);
        if (!match) {
            super.location = url
            return
        }
        fetch(url).then(response => {
            const contentDisposition = response.headers.get("Content-Disposition");
            const filename = parseContentDisposition(contentDisposition);
            return Promise.all([response.blob(), filename]);
        }).then(([blob, filename]) => {
            const printData = {
                file: blob,
                filename,
                reportName: "account.report_invoice_with_payments",
                reportTitle: _t("Invoices with Payment"),
                docNames: removeExtension(filename) || ""
            };

            const format = filename.endsWith(".pdf") ? "pdf" : "zip"
            const proxyUrl = `http://127.0.0.1:32276/print/${format}`
            return sendToPrinter(printData, proxyUrl)
        }).then(async (response) => {
            if (response && !response.ok) {
                return response.text().then((text) => Promise.reject(new Error(text)));
            }
            return Promise.resolve()
        }).catch(error => {
            console.error('Download of invoice failed:', error)
        })
    },
});
