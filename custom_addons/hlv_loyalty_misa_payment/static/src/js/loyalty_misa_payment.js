/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

// Màu badge theo trạng thái thu tiền. Dùng chung cho cả kết luận tổng, từng chứng từ và từng
// dòng hàng để người dùng không phải học 2 bảng màu khác nhau trên cùng 1 màn hình.
const STATE_CLASSES = {
    paid: "text-bg-success",
    unpaid: "text-bg-danger",
    partial: "text-bg-warning",
    not_found: "text-bg-secondary",
    no_invoice: "text-bg-secondary",
    no_line: "text-bg-secondary",
    unknown: "text-bg-info",
};

const LINE_STATE_LABELS = {
    paid: "Đã thu tiền",
    unpaid: "Chưa thu tiền",
    partial: "Thu một phần",
    unknown: "Không rõ",
    not_found: "Không có trên hóa đơn",
};

function formatNumber(value, decimals = 0) {
    return (value || 0).toLocaleString("vi-VN", {
        minimumFractionDigits: 0,
        maximumFractionDigits: decimals,
    });
}

/** Hộp thoại xem DỮ LIỆU THÔ đúng như MISA trả về, để người dùng tự đối chiếu khi nghi ngờ
 *  kết luận của bảng (VD hóa đơn có field lạ, hoặc paid_type mang giá trị chưa biết). */
export class MisaPaymentRawDialog extends Component {
    static template = "hlv_loyalty_misa_payment.RawDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        raw: { type: Object, optional: true },
    };

    setup() {
        this.notification = useService("notification");
    }

    get rawText() {
        return JSON.stringify(this.props.raw || {}, null, 2);
    }

    async onCopy() {
        try {
            await navigator.clipboard.writeText(this.rawText);
            this.notification.add("Đã copy dữ liệu thô.", { type: "success" });
        } catch {
            // Trình duyệt chặn clipboard khi trang không chạy HTTPS — người dùng vẫn bôi đen
            // copy tay được, không cần chặn thao tác.
            this.notification.add("Trình duyệt không cho copy tự động, vui lòng bôi đen và copy tay.", {
                type: "warning",
            });
        }
    }
}

/** Bảng "Hóa đơn MISA đã thu tiền chưa" trên form Lịch sử điểm.
 *
 *  Tự gọi khi mở form (không chờ người dùng bấm) vì đây chính là thông tin cần có TRƯỚC khi
 *  quyết định xác nhận điểm. Cố tình KHÔNG await trong onWillStart: form phải hiện ra ngay,
 *  phần này tự hiện "đang kiểm tra" rồi cập nhật sau — MISA có lúc trả chậm vài giây. */
export class LoyaltyMisaPaymentPanel extends Component {
    static template = "hlv_loyalty_misa_payment.Panel";
    // Cố tình KHÔNG khai static props: thẻ <widget> của Odoo truyền vào những props gì là
    // chuyện nội bộ của form renderer và đổi theo phiên bản — khai thiếu 1 cái là OWL chặn
    // render cả form ở chế độ debug. Ở đây chỉ đọc record.resId nên không cần ràng buộc.

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.state = useState({ loading: false, data: null, error: null });
        onWillStart(() => this.load());
        onWillUpdateProps((nextProps) => {
            // Bấm mũi tên qua bản ghi kế tiếp không dựng lại component — phải tự nhận ra bản
            // ghi đã đổi, không thì bảng vẫn hiện hóa đơn của giao dịch điểm trước đó.
            if (nextProps.record?.resId !== this.loadedResId) {
                this.load(false, nextProps.record?.resId);
            }
        });
    }

    async load(forceRefresh = false, resId = undefined) {
        const recordId = resId === undefined ? this.props.record?.resId : resId;
        this.loadedResId = recordId;
        if (!recordId) {
            return;
        }
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call(
                "hlv.loyalty.history",
                "get_misa_payment_status",
                [recordId],
                { force_refresh: forceRefresh }
            );
            if (this.loadedResId !== recordId) {
                return; // Đã chuyển sang bản ghi khác trong lúc chờ — bỏ kết quả cũ.
            }
            this.state.data = data;
        } catch (error) {
            this.state.error = error.data?.message || error.message || String(error);
        } finally {
            this.state.loading = false;
        }
    }

    get data() {
        return this.state.data || {};
    }

    stateClass(state) {
        return STATE_CLASSES[state] || "text-bg-secondary";
    }

    lineStateLabel(state) {
        return LINE_STATE_LABELS[state] || state;
    }

    get invoiceSourceLabel() {
        if (this.data.invoice_source === "picking") {
            return "số hóa đơn lấy từ phiếu kho (đã đối soát trước đó)";
        }
        if (this.data.invoice_source === "live") {
            return "số hóa đơn tra sống từ MISA";
        }
        return "";
    }

    formatQty(value) {
        return formatNumber(value, 3);
    }

    formatMoney(value) {
        return formatNumber(value, 0);
    }

    /** MISA trả ngày dạng ISO đầy đủ ("2026-09-08T00:00:00.000+07:00") — chỉ lấy phần ngày,
     *  và trả chuỗi rỗng khi thiếu (t-esc của false sẽ in ra chữ "false"). */
    formatDate(value) {
        return value ? String(value).slice(0, 10) : "";
    }

    invoiceNosOf(line) {
        return (line.invoice_nos || []).join(", ") || "—";
    }

    onRefresh() {
        this.load(true);
    }

    onShowRaw() {
        this.dialog.add(MisaPaymentRawDialog, { raw: this.data.raw || {} });
    }
}

registry.category("view_widgets").add("hlv_loyalty_misa_payment", {
    component: LoyaltyMisaPaymentPanel,
});
