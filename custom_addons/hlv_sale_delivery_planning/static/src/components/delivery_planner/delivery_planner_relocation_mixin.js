/** @odoo-module **/

export class DeliveryPlannerRelocationMixin {
    async openRelocationModal() {
        if (this.selectedCount === 0) {
            alert('Vui lòng chọn ít nhất 1 đơn hàng.');
            return;
        }
        this.state.isRelocationModalOpen = true;
        this.state.relocationModalLoading = true;
        this.state.relocationModalData = null;
        this.state.relocationOrderSelections = {};
        this.state.relocationSaveDefault = false;

        try {
            const selectedIds = Array.from(this.state.selectedSOIds);

            // Giữ hàng (reserve) trước khi lấy dữ liệu chuyển vị trí — giống luồng in phiếu
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
                    console.log('Giữ hàng trước chuyển vị trí:', reserveResult.result.message);
                }
            } catch (reserveErr) {
                console.warn('Giữ hàng thất bại, tiếp tục:', reserveErr);
            }
            const data = await this.orm.call(
                'sale.order',
                'prepare_relocation_data',
                [],
                { sale_order_ids: selectedIds }
            );
            this.state.relocationModalData = data;
            this.state.relocationDestLocationId = data.default_dest_location_id || null;

            // Init selections cho mỗi đơn
            const selections = {};
            for (const order of (data.orders || [])) {
                const prodSel = {};
                for (const prod of (order.products || [])) {
                    prodSel[prod.product_id] = { include: true, qty: prod.pending_qty };
                }
                selections[order.sale_order_id] = {
                    selected: true,
                    products: prodSel,
                };
            }
            this.state.relocationOrderSelections = selections;
        } catch (err) {
            console.error('Lỗi khi tải dữ liệu chuyển vị trí:', err);
            alert('Lỗi: ' + (err.message || ''));
            this.state.isRelocationModalOpen = false;
        } finally {
            this.state.relocationModalLoading = false;
        }
    }

    closeRelocationModal() {
        this.state.isRelocationModalOpen = false;
        this.state.relocationModalData = null;
        this.state.relocationOrderSelections = {};
    }

    toggleRelocationOrder(soId, checked) {
        if (!this.state.relocationOrderSelections[soId]) return;
        this.state.relocationOrderSelections[soId].selected = checked;
        this.state.relocationOrderSelections = { ...this.state.relocationOrderSelections };
    }

    getRelocationProductSel(soId, productId) {
        const oSel = this.state.relocationOrderSelections[soId];
        if (!oSel || !oSel.products) return null;
        return oSel.products[productId] || null;
    }

    toggleRelocationProduct(soId, productId, checked) {
        const oSel = this.state.relocationOrderSelections[soId];
        if (!oSel || !oSel.products[productId]) return;
        oSel.products[productId].include = checked;
        this.state.relocationOrderSelections = { ...this.state.relocationOrderSelections };
    }

    setRelocationProductQty(soId, productId, qty) {
        const oSel = this.state.relocationOrderSelections[soId];
        if (!oSel || !oSel.products[productId]) return;
        oSel.products[productId].qty = parseFloat(qty) || 0;
    }

    async confirmCreateRelocationPickings() {
        const destLocId = parseInt(this.state.relocationDestLocationId);
        if (!destLocId) {
            alert('Vui lòng chọn vị trí đích.');
            return;
        }

        const orders = [];
        for (const order of (this.state.relocationModalData?.orders || [])) {
            const oSel = this.state.relocationOrderSelections[order.sale_order_id];
            if (!oSel || !oSel.selected) continue;

            const products = (order.products || [])
                .filter(p => {
                    const ps = oSel.products[p.product_id];
                    return ps && ps.include && ps.qty > 0;
                })
                .map(p => ({
                    product_id: p.product_id,
                    qty: oSel.products[p.product_id].qty,
                }));

            if (!products.length) continue;
            orders.push({
                sale_order_id: order.sale_order_id,
                products,
            });
        }

        if (!orders.length) {
            alert('Vui lòng chọn ít nhất 1 đơn hàng và sản phẩm.');
            return;
        }

        this.state.isCreatingRelocation = true;
        try {
            const result = await this.orm.call(
                'sale.order',
                'create_relocation_pickings',
                [],
                {
                    relocation_data: {
                        dest_location_id: destLocId,
                        save_as_default: this.state.relocationSaveDefault,
                        orders,
                    },
                }
            );

            const created = result.created || [];
            const errors = result.errors || [];

            if (created.length) {
                const names = created.map(c => `${c.sale_order_name}: ${c.picking_name}`).join('\n');
                alert(`Đã tạo ${created.length} phiếu chuyển vị trí:\n${names}`);
                // Mở PDF phiếu chuyển vị trí (nếu có)
                if (result.pdf_url) {
                    window.open(result.pdf_url, '_blank');
                }
                this.closeRelocationModal();
                await this.fetchData();
            }

            if (errors.length) {
                const errMsg = errors.map(e => e.error).join('\n');
                alert('Lỗi:\n' + errMsg);
            }
        } catch (err) {
            console.error('Lỗi tạo phiếu chuyển vị trí:', err);
            alert('Lỗi: ' + (err.message || ''));
        } finally {
            this.state.isCreatingRelocation = false;
        }
    }
}
