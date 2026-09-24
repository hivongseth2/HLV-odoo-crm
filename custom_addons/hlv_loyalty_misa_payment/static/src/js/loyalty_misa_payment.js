/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

// Mỗi trạng thái thu tiền chỉ khai MỘT lần ở đây (tông màu + icon + tiêu đề ngắn), rồi card
// tổng, thẻ hóa đơn và pill trên từng dòng hàng đều lấy từ đó — không thì 3 chỗ tự chọn màu
// riêng, sửa một chỗ là lệch nhau ngay.
const STATE_STYLE = {
    paid: { tone: "paid", icon: "fa-check-circle", title: "Đã thu tiền" },
    unpaid: { tone: "unpaid", icon: "fa-exclamation-circle", title: "Chưa thu tiền" },
    partial: { tone: "partial", icon: "fa-adjust", title: "Thu tiền một phần" },
    not_found: { tone: "neutral", icon: "fa-question-circle", title: "Không khớp được hóa đơn" },
    no_invoice: { tone: "neutral", icon: "fa-file-o", title: "Chưa có hóa đơn MISA" },
    no_line: { tone: "neutral", icon: "fa-question-circle", title: "Không có dòng hàng" },
    unknown: { tone: "info", icon: "fa-question-circle", title: "Không rõ tình trạng" },
};

const NEUTRAL_STYLE = { tone: "neutral", icon: "fa-question-circle", title: "Không rõ" };

// Nhãn ngắn cho pill trên từng dòng hàng — cột hẹp nên không dùng lại title dài ở trên.
const LINE_LABELS = {
    paid: "Đã thu",
    unpaid: "Chưa thu",
    partial: "Một phần",
    unknown: "Không rõ",
    not_found: "Không có trên HĐ",
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

/** Card "Thu tiền hóa đơn MISA" trên form Lịch sử điểm.
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
        this.state = useState({ loading: false, data: null, error: null, fetchedAt: "" });
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
            this.state.fetchedAt = new Date().toLocaleTimeString("vi-VN");
        } catch (error) {
            this.state.error = error.data?.message || error.message || String(error);
        } finally {
            this.state.loading = false;
        }
    }

    get data() {
        return this.state.data || {};
    }

    /** Tông màu + icon + tiêu đề của cả card. Đang tải/lỗi thắng kết luận từ MISA. */
    get cardStyle() {
        if (this.state.loading) {
            return { tone: "neutral", icon: "fa-spinner fa-spin", title: "Đang kiểm tra MISA…" };
        }
        if (this.state.error || this.data.error) {
            return { tone: "unpaid", icon: "fa-times-circle", title: "Không tra được MISA" };
        }
        if (!this.state.data || !this.data.available) {
            return { tone: "neutral", icon: "fa-info-circle", title: "Không có dữ liệu để tra" };
        }
        return STATE_STYLE[this.data.summary_state] || NEUTRAL_STYLE;
    }

    get subline() {
        if (this.state.loading) {
            return "Đang gọi MISA lấy số hóa đơn và tình trạng thu tiền…";
        }
        if (this.state.error || this.data.error) {
            return this.state.error || this.data.error;
        }
        if (!this.data.available) {
            return this.data.message || "";
        }
        return this.data.summary_label || "";
    }

    /** Chú thích nguồn số hóa đơn + thời điểm tra, để người dùng biết đang xem số liệu lúc nào. */
    get footnote() {
        if (!this.data.invoice_no) {
            return "";
        }
        const source =
            this.data.invoice_source === "picking"
                ? "số hóa đơn lấy từ phiếu kho (đã đối soát trước đó)"
                : "số hóa đơn tra sống từ MISA";
        return `Tra lúc ${this.state.fetchedAt} — ${source}. Kết quả đã được lưu lại vào bản ghi điểm.`;
    }

    /** Class tông màu cho 1 trạng thái, dùng chung cho card (o_lmp) và pill (o_lmp__pill). */
    toneClass(state, prefix) {
        return `${prefix}--${(STATE_STYLE[state] || NEUTRAL_STYLE).tone}`;
    }

    stateIcon(state) {
        return (STATE_STYLE[state] || NEUTRAL_STYLE).icon;
    }

    lineLabel(state) {
        return LINE_LABELS[state] || state;
    }

    /** Ẩn cột "Số hóa đơn" của bảng dòng hàng khi cả phiếu chỉ có 1 hóa đơn — khi đó cột này
     *  chỉ lặp lại đúng con số đã in to ở thẻ hóa đơn ngay phía trên. */
    get showLineInvoiceColumn() {
        return (this.data.vouchers || []).length > 1;
    }

    get lineColspan() {
        return this.showLineInvoiceColumn ? 7 : 6;
    }

    formatQty(value) {
        return formatNumber(value, 3);
    }

    formatMoney(value) {
        return formatNumber(value, 0);
    }

    /** MISA trả ngày dạng ISO đầy đủ ("2026-09-08T00:00:00.000+07:00") — đổi sang dd/mm/yyyy
     *  cho quen mắt, và trả chuỗi rỗng khi thiếu (t-esc của false sẽ in ra chữ "false"). */
    formatDate(value) {
        if (!value) {
            return "";
        }
        const [year, month, day] = String(value).slice(0, 10).split("-");
        return day && month && year ? `${day}/${month}/${year}` : String(value).slice(0, 10);
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
