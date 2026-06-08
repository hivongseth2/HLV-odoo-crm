/** @odoo-module **/
// Purpose: Delivery planner mixin for packer assignment, print menus, and picking slip printing.

export class DeliveryPlannerPrintingMixin {
    async _ensurePackerUsers() {
        if (this.state.packerUsers.length || this.state.packerUsersLoading) return;
        this.state.packerUsersLoading = true;
        try {
            const users = await this.orm.call('stock.picking', 'get_packer_users_for_assignment', [], {});
            this.state.packerUsers = (users || []).map((u) => ({
                id: u.id,
                name: u.name,
                packer_name: u.packer_name || u.name,
            }));
            if (!this.state.selectedPackerUserId && this.state.packerUsers.length) {
                this.state.selectedPackerUserId = this.state.packerUsers[0].id;
            }
        } catch (e) {
            console.error('Load packer users failed:', e);
            this.notification.add('Không tải được danh sách người đóng', { type: 'danger' });
        } finally {
            this.state.packerUsersLoading = false;
        }
    }

    formatPackDuration(seconds) {
        seconds = Math.round(seconds || 0);
        if (!seconds) return '-';
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        if (hours) return `${hours}h ${minutes}m`;
        return `${minutes}m`;
    }

    async loadPackingProgress() {
        if (this.state.packingProgressLoading) return;
        this.state.packingProgressLoading = true;
        try {
            const result = await this.orm.call('stock.picking', 'get_packing_kpi_dashboard', [], {
                date_from: this.state.packingProgressDateFrom,
                date_to: this.state.packingProgressDateTo,
                packer_user_id: 'all',
                packing_state: this.state.packingProgressState,
            });
            this.state.packingProgress = result || { summary: {}, groups: [] };
        } catch (e) {
            console.warn('Load packing progress failed:', e);
        } finally {
            this.state.packingProgressLoading = false;
        }
    }

    onPackingProgressDateFromChange(ev) {
        this.state.packingProgressDateFrom = ev.target.value;
    }

    onPackingProgressDateToChange(ev) {
        this.state.packingProgressDateTo = ev.target.value;
    }

    onPackingProgressStateChange(ev) {
        this.state.packingProgressState = ev.target.value;
    }

    async togglePackingProgressDrawer() {
        this.state.isPackingProgressDrawerOpen = !this.state.isPackingProgressDrawerOpen;
        if (this.state.isPackingProgressDrawerOpen) {
            await this._ensurePackerUsers();
            await this.loadPackingProgress();
        }
    }

    async reassignDrawerPacker(pickId, newPackerUserId) {
        const uid = parseInt(newPackerUserId, 10);
        if (!uid || !pickId) return;
        try {
            await this.orm.call('stock.picking', 'action_assign_packer', [[pickId]], {
                packer_user_id: uid,
            });
            await this.loadPackingProgress();
        } catch (e) {
            this.notification.add(e.message || 'Đổi packer thất bại', { type: 'danger' });
        }
    }

    async openPackerAssignModal(reportId = null, reportType = 'qweb-pdf', pickingId = null) {
        this.state.pendingPrintReportId = reportId;
        this.state.pendingPrintReportType = reportType || 'qweb-pdf';
        this.state.pendingSinglePrintPickingId = pickingId || null;
        this.state.selectedPrintMenuPos = null;
        await this._ensurePackerUsers();
        this.state.isPackerAssignModalOpen = true;
    }

    onPackerSelectChange(ev) {
        this.state.selectedPackerUserId = parseInt(ev.target.value || '0', 10) || null;
    }

    closePackerAssignModal() {
        if (this.state.isPrintingPickingSlips) return;
        this.state.isPackerAssignModalOpen = false;
        this.state.pendingPrintReportId = null;
        this.state.pendingPrintReportType = 'qweb-pdf';
        this.state.pendingSinglePrintPickingId = null;
        this.state.changePackerPickingId = null;
    }

    async openChangePackerModal(pickingId) {
        this.state.changePackerPickingId = pickingId;
        this.state.pendingPrintReportId = null;
        this.state.pendingSinglePrintPickingId = null;
        // Pre-select current packer if known
        const allPickings = this.state.saleOrders.flatMap(so => so.pickings || []);
        const picking = allPickings.find(p => p.id === pickingId);
        if (picking && picking.packer_user && picking.packer_user[0]) {
            this.state.selectedPackerUserId = picking.packer_user[0];
        } else {
            this.state.selectedPackerUserId = null;
        }
        await this._ensurePackerUsers();
        this.state.isPackerAssignModalOpen = true;
    }

    async confirmPackerAssignAndPrint() {
        if (!this.state.selectedPackerUserId) {
            this.notification.add('Vui lòng chọn người đóng', { type: 'warning' });
            return;
        }
        const packerUserId = this.state.selectedPackerUserId;
        const changePickingId = this.state.changePackerPickingId;
        const reportId = this.state.pendingPrintReportId;
        const reportType = this.state.pendingPrintReportType || 'qweb-pdf';
        const pickingId = this.state.pendingSinglePrintPickingId;
        this.state.isPackerAssignModalOpen = false;

        if (changePickingId) {
            // Change packer only mode (no print)
            this.state.changePackerPickingId = null;
            try {
                await this.orm.call('stock.picking', 'action_assign_packer', [[changePickingId]], { packer_user_id: packerUserId });
                const packer = this.state.packerUsers.find(u => u.id === packerUserId);
                const packerLabel = packer ? (packer.packer_name || packer.name || '') : '';
                for (const so of this.state.saleOrders) {
                    const pk = (so.pickings || []).find(p => p.id === changePickingId);
                    if (pk) { pk.packer_user = [packerUserId, packerLabel]; break; }
                }
                if (this.state.selectedOrder) {
                    const pk = (this.state.selectedOrder.pickings || []).find(p => p.id === changePickingId);
                    if (pk) pk.packer_user = [packerUserId, packerLabel];
                }
                this.notification.add('Đã đổi người đóng thành công', { type: 'success' });
            } catch (e) {
                console.error('Change packer failed:', e);
                this.notification.add('Không thể đổi người đóng', { type: 'danger' });
            }
            return;
        }

        if (pickingId) {
            await this.doPrintPickingReport(null, pickingId, reportId, packerUserId, true);
        } else {
            await this.printSelectedPickingSlips(reportId, reportType, packerUserId, true);
        }
    }

    async printSelectedPickingSlips(reportId = null, reportType = 'qweb-pdf', packerUserId = null, skipPackerModal = false) {
        if (this.selectedCount === 0) return;
        if (this.state.isPrintingPickingSlips) return;

        const selectedIds = Array.from(this.state.selectedSOIds);
        const pickingIds = this.getSelectedPickingIds().filter((id) => {
            const picking = this.state.saleOrders
                .flatMap((so) => so.pickings || [])
                .find((p) => p.id === id);
            return picking && picking.state === 'assigned';
        });

        if (!pickingIds.length) {
            alert('Không có phiếu lấy hàng nào ở trạng thái sẵn sàng để in');
            return;
        }
        if (!skipPackerModal) {
            await this.openPackerAssignModal(reportId, reportType);
            return;
        }
        if (!packerUserId) {
            this.notification.add('Vui lòng chọn người đóng trước khi in', { type: 'warning' });
            await this.openPackerAssignModal(reportId, reportType);
            return;
        }
        this.state.selectedPrintMenuPos = null;

        try {
            // Local flag — KHÔNG dùng state.isLoading để tránh triệu hồi full-screen overlay
            // / re-render kanban. Bus event sẽ tự động triệu hồi subset refresh.
            this.state.isPrintingPickingSlips = true;

            // Luôn gọi giữ hàng (check availability) trước khi in
            // Backend sẽ tự xác định picking nào chưa assigned để reserve
            try {
                const reserveResponse = await fetch('/hlv_sale_delivery_planning/reserve_stock', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        method: 'call',
                        params: { sale_order_ids: selectedIds },
                    }),
                });
                const reserveResult = await reserveResponse.json();
                if (reserveResult.result) {
                    console.log('Giữ hàng:', reserveResult.result.message);
                }
            } catch (reserveErr) {
                console.warn('Giữ hàng thất bại, tiếp tục in:', reserveErr);
            }

            if (reportId && reportType !== 'qweb-pdf') {
                if (!pickingIds.length) {
                    alert('Không có phiếu lấy hàng hợp lệ để in');
                    return;
                }
                await this.actionService.doAction(reportId, {
                    additionalContext: {
                        active_ids: pickingIds,
                        active_id: pickingIds[0],
                        active_model: 'stock.picking',
                    },
                });
                this.clearAllSelections();
            } else {
                const url = `/hlv_sale_delivery_planning/print_picking_slips`;
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        method: 'call',
                        params: {
                            sale_order_ids: selectedIds,
                            report_id: reportId,
                            packer_user_id: packerUserId,
                        },
                    }),
                });

                const result = await response.json();
                if (result.error) {
                    console.error('Error printing picking slips:', result.error);
                    alert('Lỗi khi in phiếu lấy hàng: ' + (result.error.data?.message || result.error.message));
                    return;
                }

                if (result.result && result.result.success === false) {
                    alert(result.result.message || 'Không thể in phiếu lấy hàng');
                    return;
                }

                if (result.result && result.result.url) {
                    window.open(result.result.url, '_blank');
                    for (const so of this.state.saleOrders) {
                        if (selectedIds.includes(so.id)) {
                            so.has_active_pick_printed = true;
                            for (const pk of (so.pickings || [])) {
                                if (pickingIds.includes(pk.id)) {
                                    pk.printed = true;
                                    pk.packer_user = [result.result.packer_user_id, result.result.packer_name];
                                }
                            }
                        }
                    }
                    this.clearAllSelections();
                }
            }
        } catch (error) {
            console.error('Error printing picking slips:', error);
            alert('Lỗi khi in phiếu lấy hàng');
        } finally {
            this.state.isPrintingPickingSlips = false;
        }
    }

    // --- Drag & Drop Handlers ---
}
