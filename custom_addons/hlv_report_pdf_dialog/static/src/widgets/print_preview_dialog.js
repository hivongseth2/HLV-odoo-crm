/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { Component, onMounted, onWillUnmount, useRef } from "@odoo/owl";

export class PrintPreviewDialog extends Component {
    static template = "hlv_report_pdf_dialog.PrintPreviewDialog";
    static components = { Dialog };

    setup() {
        this.iframeRef = useRef("pdfFrame");

        onMounted(() => {
            const iframe = this.iframeRef.el;
            if (!iframe) return;

            const triggerPrint = () => {
                // đợi 1 nhịp cho PDF render xong trong iframe rồi mới print
                setTimeout(() => this.onPrint(), 150);
            };

            // Nếu iframe đã load thì in luôn, còn không thì đợi 'load'
            if (iframe.contentDocument?.readyState === "complete") {
                triggerPrint();
            } else {
                const onLoad = () => {
                    iframe.removeEventListener("load", onLoad);
                    triggerPrint();
                };
                iframe.addEventListener("load", onLoad);
            }
        });

        onWillUnmount(() => {
            try { this.props.url && URL.revokeObjectURL(this.props.url); } catch { }
        });
    }

    onPrint() {
        const iframe = this.iframeRef.el;
        if (iframe && iframe.contentWindow) {
            try {
                iframe.contentWindow.focus();
                iframe.contentWindow.print();
            } catch (e) {
                // fallback: mở tab mới nếu trình duyệt chặn
                window.open(this.props.url, "_blank");
            }
        }
    }
}
