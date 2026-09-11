/** @odoo-module **/
// Purpose: Delivery planner mixin for the "đã hoàn tất thủ tục sẵn sàng giao" checkbox.

export class DeliveryPlannerProcedureMixin {
    /**
     * Ô tick chỉ hiện với đơn của khách có trong hlv.delivery.procedure.partner
     * (backend trả requires_procedure trong payload của từng đơn).
     */
    showProcedureCheckbox(so) {
        return !!(so && so.requires_procedure);
    }

    procedureDoneTitle(so) {
        if (!so || !so.procedure_done) {
            return 'Tick khi đã hoàn tất thủ tục cần thiết trước khi giao';
        }
        const by = so.procedure_done_by ? ` bởi ${so.procedure_done_by}` : '';
        const at = so.procedure_done_at ? ` lúc ${so.procedure_done_at}` : '';
        return `Đã xác nhận hoàn tất thủ tục${by}${at}`;
    }

    /**
     * Bật/tắt xác nhận thủ tục. Luôn hỏi lại trước khi ghi vì sale/kho rất dễ
     * bấm nhầm vào ô tick nằm ngay trên thẻ đơn.
     */
    async toggleProcedureDone(so) {
        if (!so || !this.showProcedureCheckbox(so) || this._procedureSaving) return;
        const next = !so.procedure_done;
        const message = next
            ? `Bạn xác nhận ĐÃ HOÀN TẤT THỦ TỤC sẵn sàng giao cho đơn ${so.name}?\n\nKho sẽ căn cứ vào xác nhận này để xuất hàng.`
            : `Bỏ xác nhận hoàn tất thủ tục của đơn ${so.name}?\n\nKho sẽ hiểu là đơn CHƯA xong thủ tục và chưa được giao.`;
        if (!window.confirm(message)) return;

        this._procedureSaving = true;
        const previous = {
            procedure_done: so.procedure_done,
            procedure_done_by: so.procedure_done_by,
            procedure_done_at: so.procedure_done_at,
        };
        // Cập nhật lạc quan để ô tick phản hồi ngay; rollback nếu RPC lỗi.
        so.procedure_done = next;
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.service', 'set_order_procedure_done', [so.id, next]
            );
            if (!res || !res.success) {
                Object.assign(so, previous);
                this.notification.add(
                    (res && res.message) || 'Không cập nhật được xác nhận thủ tục.',
                    { type: 'warning' }
                );
                return;
            }
            so.procedure_done = !!res.procedure_done;
            so.procedure_done_by = res.procedure_done_by || '';
            so.procedure_done_at = res.procedure_done_at || '';
            // Drawer đang mở cùng đơn thì đồng bộ luôn (khác object với card).
            const selected = this.state.selectedOrder;
            if (selected && selected.id === so.id && selected !== so) {
                selected.procedure_done = so.procedure_done;
                selected.procedure_done_by = so.procedure_done_by;
                selected.procedure_done_at = so.procedure_done_at;
            }
            this.notification.add(
                next ? 'Đã ghi nhận hoàn tất thủ tục.' : 'Đã bỏ xác nhận hoàn tất thủ tục.',
                { type: 'success' }
            );
        } catch (e) {
            Object.assign(so, previous);
            console.error('setOrderProcedureDone error', e);
            this.notification.add('Không cập nhật được xác nhận thủ tục.', { type: 'danger' });
        } finally {
            this._procedureSaving = false;
        }
    }
}
