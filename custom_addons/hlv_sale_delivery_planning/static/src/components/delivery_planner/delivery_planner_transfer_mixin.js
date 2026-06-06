/** @odoo-module **/

export class DeliveryPlannerTransferMixin {
    async openTransferModal() {
        if (this.selectedCount === 0) {
            alert('Vui lòng chọn ít nhất 1 đơn hàng.');
            return;
        }
        this.state.isTransferModalOpen = true;
        this.state.transferModalLoading = true;
        this.state.transferModalData = null;
        this.state.transferSelections = {};

        try {
            const selectedIds = Array.from(this.state.selectedSOIds);
            const data = await this.orm.call(
                'sale.order',
                'prepare_transfer_modal_data',
                [],
                { sale_order_ids: selectedIds }
            );
            this.state.transferModalData = data;

            // Init selections for each warehouse (partner auto-applied from wh.partner_id)
            const selections = {};
            for (const wh of (data.warehouses || [])) {
                const prodSel = {};
                for (const prod of (wh.products || [])) {
                    prodSel[prod.product_id] = { include: true, qty: prod.total_qty };
                }
                selections[wh.warehouse_id] = {
                    selected: true,
                    partner_id: wh.partner_id || false,
                    products: prodSel,
                };
            }
            this.state.transferSelections = selections;
        } catch (err) {
            console.error('Lỗi khi tải dữ liệu luân chuyển:', err);
            alert('Lỗi khi phân tích dữ liệu luân chuyển: ' + (err.message || ''));
            this.state.isTransferModalOpen = false;
        } finally {
            this.state.transferModalLoading = false;
        }
    }

    closeTransferModal() {
        this.state.isTransferModalOpen = false;
        this.state.transferModalData = null;
        this.state.transferSelections = {};
    }

    toggleWarehouseSelection(whId, checked) {
        if (!this.state.transferSelections[whId]) return;
        this.state.transferSelections[whId].selected = checked;
        // Force OWL reactivity
        this.state.transferSelections = { ...this.state.transferSelections };
    }

    setTransferPartner(whId, partnerId) {
        if (!this.state.transferSelections[whId]) return;
        this.state.transferSelections[whId].partner_id = partnerId ? parseInt(partnerId) : '';
    }

    getProductSelection(whId, productId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel || !whSel.products) return null;
        return whSel.products[productId] || null;
    }

    toggleProductSelection(whId, productId, checked) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return;
        if (!whSel.products[productId]) return;
        whSel.products[productId].include = checked;
        this.state.transferSelections = { ...this.state.transferSelections };
    }

    toggleAllProducts(whId, checked) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return;
        for (const pid of Object.keys(whSel.products)) {
            whSel.products[pid].include = checked;
        }
        this.state.transferSelections = { ...this.state.transferSelections };
    }

    areAllProductsSelected(whId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel || !whSel.products) return false;
        return Object.values(whSel.products).every(p => p.include);
    }

    setProductQty(whId, productId, qty) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel || !whSel.products[productId]) return;
        whSel.products[productId].qty = qty;
    }

    countSelectedProducts(whId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return 0;
        return Object.values(whSel.products || {}).filter(p => p.include).length;
    }

    sumSelectedQty(whId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return 0;
        return Object.values(whSel.products || {})
            .filter(p => p.include)
            .reduce((s, p) => s + (p.qty || 0), 0);
    }

    exportTransferExcel() {
        const selectedIds = Array.from(this.state.selectedSOIds);
        if (!selectedIds.length) return;
        const params = new URLSearchParams();
        params.set('sale_order_ids', JSON.stringify(selectedIds));
        window.open(`/hlv_sale_delivery_planning/export_transfer_excel?${params.toString()}`, '_blank');
    }

    async confirmCreateTransferPickings() {
        const data = this.state.transferModalData;
        if (!data || !data.warehouses) return;

        const warehouseSelections = [];
        for (const wh of data.warehouses) {
            const sel = this.state.transferSelections[wh.warehouse_id];
            if (!sel || !sel.selected) continue;

            const products = (wh.products || [])
                .filter(prod => {
                    const ps = sel.products[prod.product_id];
                    return ps && ps.include && ps.qty > 0;
                })
                .map(prod => ({
                    product_id: prod.product_id,
                    total_qty: sel.products[prod.product_id].qty,
                }));

            if (!products.length) continue;

            warehouseSelections.push({
                warehouse_id: wh.warehouse_id,
                picking_type_id: wh.picking_type_id,
                lot_stock_id: wh.lot_stock_id,
                transit_location_id: wh.transit_location_id,
                partner_id: sel.partner_id || false,
                products,
            });
        }

        if (!warehouseSelections.length) {
            alert('Vui lòng chọn ít nhất 1 kho và 1 sản phẩm.');
            return;
        }

        this.state.isCreatingTransfer = true;
        try {
            const result = await this.orm.call(
                'sale.order',
                'create_transfer_pickings',
                [],
                { warehouse_selections: warehouseSelections }
            );

            const created = result.created || [];
            const errors = result.errors || [];

            if (created.length) {
                const names = created.map(c => c.picking_name).join(', ');
                const msg = `Đã tạo ${created.length} phiếu luân chuyển: ${names}`;
                alert(msg);
                this.closeTransferModal();
                await this.fetchData();
            }

            if (errors.length) {
                const errMsg = errors.map(e => `Kho ${e.warehouse_id}: ${e.error}`).join('\n');
                alert('Lỗi khi tạo phiếu:\n' + errMsg);
            }
        } catch (err) {
            console.error('Lỗi tạo phiếu luân chuyển:', err);
            alert('Lỗi: ' + (err.message || ''));
        } finally {
            this.state.isCreatingTransfer = false;
        }
    }

    async printPackageLabel(pack) {
        if (!pack || !pack.picking_id) return;

        await this.actionService.doAction("hlv_pack_sequence.action_report_package_labels", {
            additionalContext: {
                active_ids: [pack.picking_id],
                active_model: 'stock.picking'
            },
        });
    }

    formatPackageLocation(locationName) {
        if (!locationName) {
            return "khu vực đóng gói";
        }
        if (locationName.includes("Partners/Customers")) {
            return "đã giao khách";
        }
        if (locationName.includes("/OUT") || locationName.includes("Đầu ra")) {
            return "chờ xuất kho";
        }
        return locationName;
    }

    // --- Filter Helpers ---
    get hasActiveFilters() {
        return this.state.searchQuery ||
            this.state.filterWarehouseId !== "all" ||
            this.state.filterDeliveryStatus !== "all" ||
            this.state.filterStockStatus !== "all" ||
            this.state.filterDateFrom ||
            this.state.filterDateTo ||
            this.state.filterDoneDateFrom ||
            this.state.filterDoneDateTo ||
            this.state.filterPODateFrom ||
            this.state.filterPODateTo ||
            this.state.filterPOStatus !== "all" ||
            this.state.filterPackingStatus !== "all" ||
            this.state.filterSalerCode ||
            this.state.filterHtgh ||
            this.state.filterDeliveryType !== "all" ||
            this.state.filterTagIds.length > 0 ||
            this.state.showCompleted;
    }

    saveHtghPreset() {
        const val = this.state.filterHtgh.trim();
        if (!val) return;
        const label = prompt('Tên gợi ý:', val.slice(0, 30));
        if (!label) return;
        this.state.htghPresets = [...this.state.htghPresets, { label, value: val }];
        localStorage.setItem('hlv_htgh_presets', JSON.stringify(this.state.htghPresets));
    }

    removeHtghPreset(idx) {
        this.state.htghPresets = this.state.htghPresets.filter((_, i) => i !== idx);
        localStorage.setItem('hlv_htgh_presets', JSON.stringify(this.state.htghPresets));
    }

    countTransferWarehouses(so) {
        if (!so.transfer_suggestions) return 0;
        const whIds = {};
        so.transfer_suggestions.forEach(s => (s.sources || []).forEach(src => { whIds[src.from_warehouse_id] = 1; }));
        return Object.keys(whIds).length;
    }

    resetFilters() {
        this.state.searchQuery = "";
        this.state.filterWarehouseId = "all";
        this.state.filterDeliveryStatus = "all";
        this.state.filterStockStatus = "all";
        this.state.filterDateFrom = "";
        this.state.filterDateTo = null;
        this.state.filterDoneDateFrom = "";
        this.state.filterDoneDateTo = "";
        this.state.filterPODateFrom = null;
        this.state.filterPODateTo = null;
        this.state.filterPOStatus = "all";
        this.state.filterPackingStatus = "all";
        this.state.filterSalerCode = "";
        this.state.filterHtgh = "";
        this.state.filterDeliveryType = "all";
        this.state.filterTagIds = [];
        this.state.filterNeedTransfer = false;
        this.state.filterNewOrders = false;
        this.state.showCompleted = false;
        this.state.currentPage = 1;
        this.fetchData();
    }

    exportExcel() {
        const params = new URLSearchParams({
            search_query: this.state.searchQuery.trim(),
            filter_warehouse_id: this.state.filterWarehouseId,
            filter_delivery_status: this.state.filterDeliveryStatus,
            filter_stock_status: this.state.filterStockStatus,
            filter_packing_status: this.state.filterPackingStatus,
            filter_date_from: this.state.filterDateFrom || '',
            filter_date_to: this.state.filterDateTo || '',
            filter_done_date_from: this.state.filterDoneDateFrom || '',
            filter_done_date_to: this.state.filterDoneDateTo || '',
            filter_po_date_from: this.state.filterPODateFrom || '',
            filter_po_date_to: this.state.filterPODateTo || '',
            filter_po_status: this.state.filterPOStatus,
            filter_saler_code: this.state.filterSalerCode.trim(),
            filter_htgh: this.state.filterHtgh.trim(),
            filter_delivery_type: this.state.filterDeliveryType,
            filter_tag_ids: this.state.filterTagIds.join(','),
            show_completed: this.state.showCompleted ? '1' : '',
        });

        const selectedIds = Array.from(this.state.selectedSOIds);
        if (selectedIds.length > 0) {
            params.set('selected_ids', selectedIds.join(','));
        }

        window.open(`/hlv_sale_delivery_planning/export_excel?${params.toString()}`, '_blank');
    }

    // ── Relocation Modal (Chuyển vị trí) ────────────────────────────────
}
