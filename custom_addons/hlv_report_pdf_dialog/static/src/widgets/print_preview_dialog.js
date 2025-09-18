
/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { Component, onWillUnmount, useRef } from "@odoo/owl";

export class PrintPreviewDialog extends Component {
    static template = "hlv_report_pdf_dialog.PrintPreviewDialog";
    static components = { Dialog };

    setup() {
        this.iframeRef = useRef("pdfFrame");
        onWillUnmount(() => {
            try { this.props.url && URL.revokeObjectURL(this.props.url); } catch {}
        });
    }

    onPrint() {
        const iframe = this.iframeRef.el;
        if (iframe && iframe.contentWindow) {
            iframe.contentWindow.focus();
            iframe.contentWindow.print();
        }
    }
}
