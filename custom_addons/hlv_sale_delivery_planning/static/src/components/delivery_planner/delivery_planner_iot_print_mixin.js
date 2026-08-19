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
        // Danh sách drawer (nếu đang mở hoặc đã từng tải) luôn được làm mới sau mỗi lần xử lý
        // hàng chờ, để trạng thái (chờ in/đã in/lỗi) hiển thị đúng thời gian thực.
        this.loadIotPrintQueueDrawer();
    }

    async loadIotPrintQueueDrawer() {
        this.state.iotPrintQueueLoading = true;
        try {
            this.state.iotPrintQueueItems = await this.orm.call(
                'hlv.iot.print.queue', 'get_recent_for_dashboard', [], { limit: 100 }
            );
        } catch (e) {
            console.error('loadIotPrintQueueDrawer failed', e);
        } finally {
            this.state.iotPrintQueueLoading = false;
        }
    }

    openIotPrintQueueDrawer() {
        this.state.isIotPrintQueueDrawerOpen = true;
        this.loadIotPrintQueueDrawer();
    }

    closeIotPrintQueueDrawer() {
        this.state.isIotPrintQueueDrawerOpen = false;
    }

    async retryIotPrintQueueItem(item) {
        try {
            await this.orm.call('hlv.iot.print.queue', 'action_retry', [[item.id]]);
            await this.processIotPrintQueue();
        } catch (e) {
            console.error('retryIotPrintQueueItem failed', e);
            this.notification.add('Không thử lại được, vui lòng tải lại trang.', { type: 'danger' });
        }
    }

    /** "Máy không ra giấy, gửi lại" — dùng khi state='printed' (đã gửi lệnh in) nhưng máy in vật
     * lý thực tế không in ra (VD IoT Box mất kết nối máy in sau khi lệnh đã gửi). */
    async requeueIotPrintQueueItem(item) {
        try {
            await this.orm.call('hlv.iot.print.queue', 'action_requeue', [[item.id]]);
            await this.processIotPrintQueue();
        } catch (e) {
            console.error('requeueIotPrintQueueItem failed', e);
            this.notification.add('Không gửi lại được, vui lòng tải lại trang.', { type: 'danger' });
        }
    }

    /** Định dạng ISO datetime (UTC, không có 'Z') từ hlv.iot.print.queue._to_summary_dict() sang
     * giờ VN (UTC+7) — dùng để đối soát thời gian yêu cầu/gửi in trong drawer. */
    _formatIotQueueTime(isoStr) {
        if (!isoStr) return '';
        try {
            const utc = new Date(isoStr.endsWith('Z') ? isoStr : isoStr + 'Z');
            if (isNaN(utc.getTime())) return '';
            const vn = new Date(utc.getTime() + 7 * 60 * 60 * 1000);
            const pad = (n) => String(n).padStart(2, '0');
            return `${pad(vn.getUTCDate())}/${pad(vn.getUTCMonth() + 1)} ${pad(vn.getUTCHours())}:${pad(vn.getUTCMinutes())}`;
        } catch (e) {
            return '';
        }
    }

    get iotPrintQueuePendingCount() {
        return (this.state.iotPrintQueueItems || []).filter(
            (i) => i.state === 'pending' || i.state === 'printing'
        ).length;
    }

    get iotPrintQueueErrorCount() {
        return (this.state.iotPrintQueueItems || []).filter((i) => i.state === 'error').length;
    }
}
