/** @odoo-module **/
import { registry } from "@web/core/registry";

function printJtLabel(env, action) {
    const attachmentId = action.params.attachment_id;
    const url = `/web/content/${attachmentId}`;

    // Create a hidden iframe
    const iframe = document.createElement('iframe');
    iframe.style.position = 'fixed';
    iframe.style.right = '0';
    iframe.style.bottom = '0';
    iframe.style.width = '0';
    iframe.style.height = '0';
    iframe.style.border = '0';
    iframe.src = url;

    document.body.appendChild(iframe);

    iframe.onload = function () {
        try {
            // Give a tiny bit of time for the PDF engine inside the iframe to ready up
            setTimeout(() => {
                iframe.contentWindow.focus();
                iframe.contentWindow.print();
            }, 500);
        } catch (e) {
            console.error("Silent print failed, opening in new tab instead", e);
            window.open(url, '_blank');
        }

        // Remove the iframe after some time (allowing print to finish/cancel)
        setTimeout(() => {
            if (iframe && iframe.parentNode) {
                document.body.removeChild(iframe);
            }
        }, 60000);
    };
}

registry.category("actions").add("jt_print_label", printJtLabel);
