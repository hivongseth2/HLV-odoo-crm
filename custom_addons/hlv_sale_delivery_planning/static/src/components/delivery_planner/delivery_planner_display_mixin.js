/** @odoo-module **/
// Purpose: Delivery planner mixin for drag/drop, filters, inline notes, tags, and action openers.

import {
    translateDeliveryStatus, translatePickingState, translatePickingStatus,
    translateStockStatus, translatePackingStatus, translateSOStatus, translatePOStatus,
    getPickingStateBadgeClass, getPickingStatusBadgeClass, getDeliveryStatusBadgeClass,
    getStockStatusBadgeClass, getPackingStatusBadgeClass, getPOStatusBadgeClass,
    getSOCardColorClass, formatCurrency, formatQty, getDatesComparisonClass,
} from "./delivery_planner_utils";

export class DeliveryPlannerDisplayMixin {
    onDragStart(ev, soId) {
        this.state.draggedSoId = soId;
        ev.dataTransfer.effectAllowed = 'move';
        ev.dataTransfer.setData('text/plain', String(soId));
    }

    onDragOver(ev, colValue) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';
        if (this.state.dragOverColumn !== colValue) {
            this.state.dragOverColumn = colValue;
        }
    }

    onDragLeave(ev) {
        // Chỉ xóa highlight khi thực sự rời khỏi column (không phải trượt qua child)
        if (!ev.currentTarget.contains(ev.relatedTarget)) {
            this.state.dragOverColumn = null;
        }
    }

    onDrop(ev, colValue) {
        ev.preventDefault();
        const soId = parseInt(ev.dataTransfer.getData('text/plain'), 10);
        if (!soId) return;

        const dim = this.state.kanbanGroupBy;
        const fieldMap = {
            delivery_status: 'real_delivery_status',
            stock_status: 'stock_status',
            packing_status: 'packing_status',
        };
        const field = fieldMap[dim];

        // Cập nhật state cục bộ (optimistic update)
        const so = this.state.saleOrders.find(s => s.id === soId);
        if (so) {
            so[field] = colValue;
        }

        // Đưa card lên đầu cột đích
        const existingOrder = (this.state.kanbanColumnOrder[colValue] || []).filter(id => id !== soId);
        this.state.kanbanColumnOrder[colValue] = [soId, ...existingOrder];

        this.state.draggedSoId = null;
        this.state.dragOverColumn = null;
    }

    onDragEnd() {
        this.state.draggedSoId = null;
        this.state.dragOverColumn = null;
    }

    async setStockFilter(status) {
        if (this.state.filterStockStatus === status) {
            // Nếu click lại chính Tab đó thì bỏ lọc (Về Tất Cả)
            this.state.filterStockStatus = 'all';
        } else {
            this.state.filterStockStatus = status;
        }
        this.state.currentPage = 1;
        await this.fetchData();
    }

    async setPackingFilter(status) {
        if (this.state.filterPackingStatus === status) {
            this.state.filterPackingStatus = 'all';
        } else {
            this.state.filterPackingStatus = status;
        }
        this.state.currentPage = 1;
        await this.fetchData();
    }

    _normalizeTextFilters() {
        this.state.searchQuery = (this.state.searchQuery || "").trim();
        this.state.filterSalerCode = (this.state.filterSalerCode || "").trim();
        this.state.filterHtgh = (this.state.filterHtgh || "").trim();
    }

    async onSearchKeyup(ev) {
        if (ev.key === "Enter") {
            if (this._searchDebounceTimer) {
                clearTimeout(this._searchDebounceTimer);
                this._searchDebounceTimer = null;
            }
            this._normalizeTextFilters();
            this.state.currentPage = 1;
            this.state.selectedSOIds = new Set();
            await this.fetchData();
            return;
        }
        if (this._searchDebounceTimer) {
            clearTimeout(this._searchDebounceTimer);
        }
        this._searchDebounceTimer = setTimeout(async () => {
            this._searchDebounceTimer = null;
            this._normalizeTextFilters();
            this.state.currentPage = 1;
            this.state.selectedSOIds = new Set();
            await this.fetchData();
        }, 350);
    }

    /** Nút "x" xóa search — hủy debounce timer đang chờ (nếu có) rồi fetch ngay, tránh 1 lần
     * gọi thừa sau đó khi timer cũ vẫn còn treo. Tách thành method riêng (thay vì inline
     * nhiều dòng trong t-on-click) vì QWeb compiler không parse được arrow function có
     * if(){...} lồng trong {...} ngay trong giá trị thuộc tính. */
    async clearSearchAndFetch() {
        if (this._searchDebounceTimer) {
            clearTimeout(this._searchDebounceTimer);
            this._searchDebounceTimer = null;
        }
        this.state.searchQuery = '';
        await this.fetchData();
    }

    async onTagFilterChange(ev) {
        this.state.filterTagIds = Array.from(ev.target.selectedOptions)
            .map(o => parseInt(o.value))
            .filter(v => !isNaN(v));
        this.state.currentPage = 1;
        this.state.selectedSOIds = new Set();
        await this.fetchData();
    }

    // ── Inline edit: Ghi Chú Odoo ──────────────────────────────────────
    startGhiChuEdit(ev, so) {
        ev.stopPropagation();
        this.state.inlineEditSOId = so.id;
        this.state.inlineEditGhiChu = so.x_studio_ghi_ch_odoo || '';
    }

    cancelGhiChuEdit() {
        this.state.inlineEditSOId = null;
        this.state.inlineEditGhiChu = '';
    }

    async saveGhiChu(so) {
        // Guard against double-save: Enter triggers keydown→save→cancelGhiChuEdit,
        // then the resulting blur fires save again with inlineEditGhiChu already ''.
        if (this.state.inlineEditSOId !== so.id) return;
        const val = (this.state.inlineEditGhiChu || '').trim();
        if (val === (so.x_studio_ghi_ch_odoo || '')) {
            this.cancelGhiChuEdit();
            return;
        }
        try {
            await this.orm.write('sale.order', [so.id], { x_studio_ghi_ch_odoo: val });
            so.x_studio_ghi_ch_odoo = val;
            // sync drawer if open
            if (this.state.selectedOrder && this.state.selectedOrder.id === so.id) {
                this.state.selectedOrder.x_studio_ghi_ch_odoo = val;
            }
            this.notification.add('Đã lưu Ghi Chú Odoo', { type: 'success', sticky: false });
        } catch (e) {
            this.notification.add('Lỗi khi lưu: ' + e.message, { type: 'danger' });
        }
        this.cancelGhiChuEdit();
    }

    onGhiChuKeydown(ev, so) {
        if (ev.key === 'Enter' && !ev.shiftKey) {
            ev.preventDefault();
            this.saveGhiChu(so);
        } else if (ev.key === 'Escape') {
            this.cancelGhiChuEdit();
        }
    }

    // ── Inline edit: Tag picker ────────────────────────────────────────
    openTagPicker(ev, so) {
        ev.stopPropagation();
        if (this.state.tagPickerSOId === so.id) {
            this.state.tagPickerSOId = null;
            this.state.tagPickerPos = null;
            return;
        }
        const rect = ev.currentTarget.getBoundingClientRect();
        this.state.tagPickerSOId = so.id;
        this.state.tagPickerPos = {
            top: rect.bottom + window.scrollY + 4,
            left: rect.left + window.scrollX,
        };
    }

    closeTagPicker() {
        this.state.tagPickerSOId = null;
        this.state.tagPickerPos = null;
    }

    isTagOnSO(so, tagId) {
        return (so.tag_ids || []).some(t => t[0] === tagId);
    }

    async toggleTagOnSO(ev, so, tagId) {
        ev.stopPropagation();
        const has = this.isTagOnSO(so, tagId);
        const tag = this.state.tags.find(t => t.id === tagId);
        if (!tag) return;
        let newTagIds;
        if (has) {
            newTagIds = (so.tag_ids || []).filter(t => t[0] !== tagId);
        } else {
            newTagIds = [...(so.tag_ids || []), [tagId, tag.name, tag.color || 0]];
        }
        try {
            const ids = newTagIds.map(t => t[0]);
            await this.orm.write('sale.order', [so.id], { tag_ids: [[6, 0, ids]] });
            so.tag_ids = newTagIds;
            if (this.state.selectedOrder && this.state.selectedOrder.id === so.id) {
                this.state.selectedOrder.tag_ids = newTagIds;
            }
        } catch (e) {
            this.notification.add('Lỗi khi cập nhật tag: ' + e.message, { type: 'danger' });
        }
    }

    async removeTagFromSO(ev, so, tagId) {
        ev.stopPropagation();
        const newTagIds = (so.tag_ids || []).filter(t => t[0] !== tagId);
        try {
            await this.orm.write('sale.order', [so.id], { tag_ids: [[6, 0, newTagIds.map(t => t[0])]] });
            so.tag_ids = newTagIds;
            if (this.state.selectedOrder && this.state.selectedOrder.id === so.id) {
                this.state.selectedOrder.tag_ids = newTagIds;
            }
        } catch (e) {
            this.notification.add('Lỗi khi xóa tag: ' + e.message, { type: 'danger' });
        }
    }

    // Odoo crm.tag color integer → background color
    getTagColor(colorInt) {
        const COLORS = [
            '#adb5bd', // 0 grey
            '#dc3545', // 1 red
            '#fd7e14', // 2 orange
            '#ffc107', // 3 yellow
            '#20c997', // 4 teal
            '#6610f2', // 5 indigo
            '#d63384', // 6 pink
            '#0d6efd', // 7 blue
            '#6f42c1', // 8 purple
            '#e91e63', // 9 fuchsia
            '#198754', // 10 green
            '#0dcaf0', // 11 cyan
        ];
        return COLORS[colorInt] || COLORS[0];
    }

    getTagTextColor(colorInt) {
        // Dark text for light backgrounds (yellow, teal, cyan), white for others
        return [3, 4, 11].includes(colorInt) ? '#000' : '#fff';
    }

    openSaleOrder(soId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: soId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    openPurchaseOrder(poId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "purchase.order",
            res_id: poId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    openPicking(pickingId) {
        this.state.printMenuPickingId = null;
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: pickingId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    async togglePickingPrintMenu(ev, pickingId) {
        ev.stopPropagation();
        if (this.state.printMenuPickingId === pickingId) {
            this.state.printMenuPickingId = null;
            this.state.printMenuPos = null;
            return;
        }
        const rect = ev.currentTarget.getBoundingClientRect();
        this.state.printMenuPickingId = pickingId;
        this.state.printMenuPos = {
            top: rect.bottom + window.scrollY,
            right: window.innerWidth - rect.right,
        };

        const allowedIds = await this.orm.call(
            'ir.actions.actions',
            'get_allowed_picking_reports',
            [],
            {
                context: {
                    active_ids: [pickingId],
                    active_id: pickingId,
                    active_model: 'stock.picking',
                }
            }
        );
        const allowedSet = new Set(allowedIds);
        this.state.printMenuReports = this.state.pickingReports.filter((r) =>
            allowedSet.has(r.id)
        );
    }

    _isPickingSlipReport(reportId) {
        const report = (this.state.pickingReports || []).find((r) => r.id === reportId);
        const name = ((report && report.name) || '').toLowerCase();
        const reportName = ((report && report.report_name) || '').toLowerCase();
        return name.includes('lấy hàng') || name.includes('hoạt động lấy hàng') || reportName.startsWith('stock.report_picking');
    }

    _isPickPickingId(pickingId) {
        for (const so of this.state.saleOrders || []) {
            const picking = (so.pickings || []).find((p) => p.id === pickingId);
            if (picking) {
                return (picking.sequence_code || '').toUpperCase().includes('PICK') && !picking.return_of_id && picking.state !== 'cancel';
            }
        }
        return false;
    }

    async doPrintPickingReport(ev, pickingId, reportId, packerUserId = null, skipPackerModal = false) {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        this.state.printMenuPickingId = null;
        if (!skipPackerModal && this._isPickPickingId(pickingId) && this._isPickingSlipReport(reportId)) {
            await this.openPackerAssignModal(reportId, 'qweb-pdf', pickingId);
            return;
        }
        if (packerUserId && this._isPickPickingId(pickingId) && this._isPickingSlipReport(reportId)) {
            const result = await this.orm.call('stock.picking', 'assign_picking_print_packer', [], {
                picking_ids: [pickingId],
                packer_user_id: packerUserId,
            });
            if (!result.success) {
                this.notification.add(result.message || 'Không assign được người đóng', { type: 'danger' });
                return;
            }
        }
        await this.actionService.doAction(reportId, {
            additionalContext: {
                active_ids: [pickingId],
                active_id: pickingId,
                active_model: 'stock.picking',
                hlv_skip_packer_assignment_dialog: true,
            }
        });
    }

    openVideo(url) {
        window.open(url, '_blank');
    }

    // --- PO Status Formatting (Receipt Based) ---

}
