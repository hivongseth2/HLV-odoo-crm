/** @odoo-module **/
// Purpose: Auto-processor cho hàng chờ in IoT (hlv.iot.print.queue) — sale gửi yêu cầu in từ
// /sale_plan, dashboard backend đang mở (bất kỳ phiên nào có quyền) tự động claim + dispatch report
// action để thực sự in ra máy IoT của kho, không cần ai bấm tay. Lỗi (thiếu máy in/report/phiếu)
// được báo ngay bằng notification thay vì im lặng.

export class DeliveryPlannerIotPrintMixin {
    async processIotPrintQueue() {
        if (this._iotPrintProcessing) {
            return; // tránh chạy chồng nếu bus event dồn dập trong lúc đang xử lý
        }
        this._iotPrintProcessing = true;
        try {
            const results = await this.orm.call('hlv.iot.print.queue', 'auto_claim_and_print', [], { limit: 20 });
            for (const r of (results || [])) {
                if (r.action) {
                    try {
                        await this.actionService.doAction(r.action);
                    } catch (e) {
                        console.error('IoT print dispatch failed for queue #' + r.queue_id, e);
                        this.notification.add(
                            `Lỗi khi in phiếu đơn (hàng chờ #${r.queue_id}): ${(e && e.message) || 'không xác định'}`,
                            { type: 'danger', sticky: true }
                        );
                    }
                } else if (r.error) {
                    this.notification.add(
                        `Không in được phiếu lấy hàng: ${r.error}`,
                        { type: 'danger', sticky: true }
                    );
                }
            }
        } catch (e) {
            console.error('processIotPrintQueue failed', e);
        } finally {
            this._iotPrintProcessing = false;
        }
    }
}
