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
                'hlv.iot.print.queue', 'get_recent_for_dashboard', [], {
                    limit: 100,
                    warehouse_id: this.state.iotQueueFilterWarehouseId || false,
                    date_from: this.state.iotQueueFilterDateFrom || false,
                    date_to: this.state.iotQueueFilterDateTo || false,
                    picking_state: this.state.iotQueueFilterPickingState || false,
                }
            );
            // Trạng thái ONLINE/OFFLINE máy in theo kho — để kho/dispatcher thấy ngay lý do 1
            // yêu cầu có thể bị kẹt/lỗi, không cần đợi bấm in rồi mới biết máy in mất kết nối.
            this.state.iotPrinterStatus = await this.orm.call(
                'hlv.iot.print.queue', 'get_printer_status_by_warehouse', [], {}
            );
        } catch (e) {
            console.error('loadIotPrintQueueDrawer failed', e);
        } finally {
            this.state.iotPrintQueueLoading = false;
        }
    }

    /** Đổi 1 filter của drawer "Yêu cầu in (IoT)" rồi tải lại danh sách ngay — lọc theo kho,
     * theo ngày yêu cầu, theo trạng thái PHIẾU LẤY HÀNG (không phải trạng thái hàng chờ in). */
    async setIotQueueFilter(key, value) {
        this.state[key] = value;
        await this.loadIotPrintQueueDrawer();
    }

    async clearIotQueueFilters() {
        this.state.iotQueueFilterWarehouseId = '';
        this.state.iotQueueFilterDateFrom = '';
        this.state.iotQueueFilterDateTo = '';
        this.state.iotQueueFilterPickingState = '';
        await this.loadIotPrintQueueDrawer();
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

    /** Kho đánh dấu "Xử lý sau" — vẫn giữ trong hàng chờ để xem lại, nhưng KHÔNG tính vào số đơn
     * đang xử lý của kho (nhường chỗ cho sale gửi yêu cầu khác nếu kho có cấu hình giới hạn). */
    async deferIotPrintQueueItem(item) {
        try {
            await this.orm.call('hlv.iot.print.queue', 'action_defer', [[item.id]]);
            await this.loadIotPrintQueueDrawer();
        } catch (e) {
            console.error('deferIotPrintQueueItem failed', e);
            this.notification.add('Không đánh dấu được, vui lòng tải lại trang.', { type: 'danger' });
        }
    }

    /** Kho từ chối xử lý — đưa yêu cầu ra khỏi hàng chờ đang hoạt động (vẫn giữ lại record để
     * đối soát, không xóa). */
    async rejectIotPrintQueueItem(item) {
        try {
            await this.orm.call('hlv.iot.print.queue', 'action_reject', [[item.id]]);
            await this.loadIotPrintQueueDrawer();
        } catch (e) {
            console.error('rejectIotPrintQueueItem failed', e);
            this.notification.add('Không từ chối được, vui lòng tải lại trang.', { type: 'danger' });
        }
    }

    /** Đưa đơn đang "Xử lý sau"/"Từ chối" trở lại xử lý bình thường (tính vào hàng chờ lại). */
    async resumeIotPrintQueueItem(item) {
        try {
            await this.orm.call('hlv.iot.print.queue', 'action_resume', [[item.id]]);
            await this.loadIotPrintQueueDrawer();
        } catch (e) {
            console.error('resumeIotPrintQueueItem failed', e);
            this.notification.add('Không đưa lại được, vui lòng tải lại trang.', { type: 'danger' });
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

    /** Tab/section "Nhật ký" trong drawer đơn — lazy-load giống toggleFlowSection(), gộp log của
     * MỌI phiếu thuộc đơn (không chỉ 1 phiếu), để đối soát khi sale nói đã gửi in mà kho không
     * thấy giấy: xem lại đúng ai gửi lúc nào, có báo lỗi/gửi lại lần nào không.
     * LUÔN tải lại mỗi lần mở (không cache theo so._printLog như flows) — vì yêu cầu in có thể
     * vừa được sale gửi từ /sale_plan trong lúc drawer này đang mở sẵn ở tab khác, cache cũ sẽ
     * làm mất đúng yêu cầu mới nhất (đây là nguyên nhân từng thấy "chưa có yêu cầu in nào" dù
     * thực ra đã có — do mở section 1 lần, tải xong rồi không refetch nữa dù có dữ liệu mới). */
    async toggleDrawerPrintLogSection() {
        this.toggleSection('drawer_print_log');
        const expanded = !this.isSectionCollapsed('drawer_print_log');
        if (!expanded) return;
        await this.refreshDrawerPrintLog();
    }

    async refreshDrawerPrintLog() {
        const so = this.state.selectedOrder;
        if (!so) return;
        if (so._printLogLoading) return;
        so._printLogLoading = true;
        try {
            so._printLog = await this.orm.call(
                'hlv.iot.print.queue', 'get_log_for_sale_order', [], { sale_order_id: so.id }
            );
        } catch (e) {
            console.error('refreshDrawerPrintLog failed', e);
            so._printLog = [];
        } finally {
            so._printLogLoading = false;
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
