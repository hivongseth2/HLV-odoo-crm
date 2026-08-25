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

        // Skip for POS orders to avoid dialog/iframe issues with IoT box
        if (action.model === "pos.order" || action.context?.active_model === "pos.order") {
            return false;
        }

        // Skip for specific label reports to use default printing (IoT)
        const IGNORED_REPORTS = [
            "custom_picking_label.report_label_35x22_template",
            "custom_picking_label.report_label_template",
            "product.report_producttemplatelabel_dymo",
            "product_label_3x3.report_product_label_3x3_template",
            "hlv_pack_sequence.report_package_label_document_copy_1",
        ];
        if (IGNORED_REPORTS.includes(action.report_name)) {
            return false;
        }

        const { ui, notification } = env.services;
        ui.block(); // show spinner

        try {
            if (!wkhtmltopdfStateProm) wkhtmltopdfStateProm = rpc("/report/check_wkhtmltopdf");
            const state = await wkhtmltopdfStateProm;
            if (!["ok", "upgrade"].includes(state)) {
                ui.unblock();
                return false;
            }

            const url = buildReportUrl(action);

            // --- create hidden iframe ---
            const iframe = document.createElement("iframe");
            Object.assign(iframe.style, {
                position: "fixed", right: "0", bottom: "0",
                width: "0", height: "0", border: "0"
            });

            // cleanup chỉ lo gỡ iframe + listeners
            let cleanupTimer;
            let safetyTimeout;
            let cleaned = false;
            const MAX_WAIT_MS = 120000; // 2 phút - rộng rãi
            const SAFETY_TIMEOUT_MS = 30000; // 30 giây safety timeout
            const listeners = [];

            const cleanupFrameOnly = () => {
                if (cleaned) return;
                cleaned = true;
                clearTimeout(cleanupTimer);
                clearTimeout(safetyTimeout);
                listeners.forEach(({ target, type, fn }) => target.removeEventListener(type, fn));
                iframe.remove();
            };

            // Safety timeout: đảm bảo unblock UI sau 30 giây nếu có lỗi
            safetyTimeout = setTimeout(() => {
                console.warn("PDF loading safety timeout reached");
                ui.unblock();
                cleanupFrameOnly();
            }, SAFETY_TIMEOUT_MS);

            iframe.onload = () => {
                try {
                    const w = iframe.contentWindow;
                    if (!w) throw new Error("no iframe contentWindow");

                    // Sau khi gọi print, bỏ overlay để user thao tác, NHƯNG giữ iframe tới afterprint/timeout
                    const doAfterPrint = () => cleanupFrameOnly();

                    const winAfterPrint = () => cleanupFrameOnly();
                    const iframeAfterPrint = () => cleanupFrameOnly();

                    window.addEventListener("afterprint", winAfterPrint);
                    listeners.push({ target: window, type: "afterprint", fn: winAfterPrint });

                    w.addEventListener("afterprint", iframeAfterPrint);
                    listeners.push({ target: w, type: "afterprint", fn: iframeAfterPrint });

                    // Fallback: khi tab lấy lại focus/visibility sau khi in xong
                    const visHandler = () => {
                        if (!document.hidden && document.hasFocus()) {
                            cleanupFrameOnly();
                            window.removeEventListener("visibilitychange", visHandler);
                        }
                    };
                    window.addEventListener("visibilitychange", visHandler);
                    listeners.push({ target: window, type: "visibilitychange", fn: visHandler });

                    // Gọi print
                    w.focus();
                    w.print();

                    // BỎ overlay NGAY SAU KHI GỌI print để user kịp bấm
                    ui.unblock();

                    // Fallback cuối: dù không bắt được afterprint, sau MAX_WAIT cũng dọn iframe
                    cleanupTimer = setTimeout(() => cleanupFrameOnly(), MAX_WAIT_MS);
                } catch (e) {
                    ui.unblock();
                    cleanupFrameOnly();
                    notification.add("Không thể tự động in: " + (e.message || e), { type: "warning" });
                }
            };

            // Thêm onerror handler để bắt lỗi load
            iframe.onerror = (e) => {
                ui.unblock();
                cleanupFrameOnly();
                notification.add("Không thể tải PDF: " + (e.message || e), { type: "danger" });
            };

            iframe.src = url; // tải trực tiếp PDF (không fetch + blob)
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
