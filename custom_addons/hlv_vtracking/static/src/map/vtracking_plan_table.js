/** @odoo-module **/

/* Bảng kế hoạch của một xe, mở từ popup trên bản đồ.

   Vì sao là hộp thoại chứ không phải nhảy thẳng sang form kế hoạch: người điều phối đang
   nhìn bản đồ để trả lời "xe này còn phải giao những gì" — rời màn hình là mất khung
   nhìn, quay lại phải dò tìm lại xe. Hộp thoại đọc thẳng dữ liệu bản đồ đã tải nên không
   tốn thêm vòng gọi server; ai cần SỬA thì bấm nút mở form.

   Popup vẫn giữ danh sách rút gọn: nó trả lời "còn bao nhiêu điểm", còn bảng này trả lời
   "cụ thể là những điểm nào, ở đâu, bao nhiêu tiền". */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { formatMoney, planLineFlags } from "./vtracking_map_utils";

export class VtrackingPlanTable extends Component {
    static template = "hlv_vtracking.PlanTable";
    static components = { Dialog };
    static props = {
        plan: Object,
        vehicleName: { type: String, optional: true },
        close: Function,
    };

    setup() {
        this.action = useService("action");
    }

    get lines() {
        return this.props.plan.lines || [];
    }

    get title() {
        const plan = this.props.plan;
        const parts = [this.props.vehicleName, plan.session_label].filter(Boolean);
        return `Kế hoạch giao — ${parts.join(" · ")}`;
    }

    /** Tổng tiền tính lại từ chính các dòng đang hiện, không lấy amount_total của kế
        hoạch: người xem cộng nhẩm cột tiền phải ra đúng con số ở chân bảng. */
    get amountTotal() {
        return this.lines.reduce((sum, line) => sum + (line.amount || 0), 0);
    }

    get deliveredCount() {
        return this.lines.filter((line) => line.delivered).length;
    }

    money(value) {
        return formatMoney(value);
    }

    flags(line) {
        return planLineFlags(line);
    }

    openPlanRecord() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hlv.vtracking.plan",
            res_id: this.props.plan.id,
            views: [[false, "form"]],
            target: "current",
        });
        this.props.close();
    }
}
