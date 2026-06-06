/** @odoo-module **/
// Purpose: Delivery planner mixin for display formatting, badges, flows, grouping, and hover helpers.

import {
    translateDeliveryStatus, translatePickingState, translatePickingStatus,
    translateStockStatus, translatePackingStatus, translateSOStatus, translatePOStatus,
    getPickingStateBadgeClass, getPickingStatusBadgeClass, getDeliveryStatusBadgeClass,
    getStockStatusBadgeClass, getPackingStatusBadgeClass, getPOStatusBadgeClass,
    getSOCardColorClass, formatCurrency, formatQty, getDatesComparisonClass,
} from "./delivery_planner_utils";

export class DeliveryPlannerDisplayHelpersMixin {
    getPOStatusClass(receiptStatus) {
        switch (receiptStatus) {
            case "pending": return "bg-secondary";
            case "partial": return "bg-warning text-dark";
            case "full": return "bg-success";
            default: return "bg-light text-muted border";
        }
    }

    // --- Translations (delegate to utils) ---
    translatePOStatus(s) { return translatePOStatus(s); }
    translateDeliveryStatus(s) { return translateDeliveryStatus(s); }
    translatePickingState(s) { return translatePickingState(s); }
    translatePickingStatus(s) { return translatePickingStatus(s); }
    translateStockStatus(s) { return translateStockStatus(s); }
    translatePackingStatus(s) { return translatePackingStatus(s); }
    translateSOStatus(s) { return translateSOStatus(s); }

    formatPackageGroupStatus(so, group) {
        if (group.picking_state !== 'done') {
            return this.translatePickingState(group.picking_state);
        }

        // Logic: Nếu có bất kỳ kiện nào trong group đã đến 'Partners/Customers' -> "Đã giao khách"
        const hasDeliveredPack = (group.packages || []).some(p =>
            (p.location_name || "").includes("Partners/Customers")
        );

        if (hasDeliveredPack) {
            return "Đã giao khách";
        }

        // Nếu là phiếu đóng gói xong or phiếu OUT xong mà chưa giao đến khách -> "Đã đóng gói" 
        const lowerName = (group.picking_name || "").toLowerCase();
        if (lowerName.includes("pack") || lowerName.includes("đóng gói") || lowerName.includes("đầu ra")) {
            return "Đã đóng gói";
        }

        return "Hoàn thành";
    }

    getPackageGroupBadgeClass(so, group) {
        if (group.picking_state !== 'done') {
            return this.getPickingStateBadgeClass(group.picking_state);
        }

        const status = this.formatPackageGroupStatus(so, group);
        if (status === "Đã giao khách") {
            return "bg-success text-bg-success"; // Green
        }
        if (status === "Đã đóng gói") {
            return "bg-info text-bg-info"; // Blue
        }
        return "bg-primary text-bg-primary"; // Hoàn thành default
    }

    toggleSection(sectionKey) {
        if (this.state.collapsedSections.has(sectionKey)) {
            this.state.collapsedSections.delete(sectionKey);
        } else {
            this.state.collapsedSections.add(sectionKey);
        }
    }

    isSectionCollapsed(sectionKey) {
        return this.state.collapsedSections.has(sectionKey);
    }

    /**
     * Lazy-load flows for a given SO when the user expands the
     * "Luồng Xử Lý Kho" section. The default dashboard payload no longer
     * contains flows (heavy recursive picking-graph walk → ~40-60% CPU per
     * page). We fetch them on demand and cache on so.flows.
     */
    async toggleFlowSection(so) {
        // Mirror the global section toggle (used by other so cards too)
        this.toggleSection('flows');
        const expanded = !this.isSectionCollapsed('flows');
        if (!expanded) return;
        if (!so || !so.has_flow) return;
        if (Array.isArray(so.flows) && so.flows.length > 0) return; // already loaded
        if (so.flows_loading) return;
        so.flows_loading = true;
        try {
            const res = await this.orm.call(
                "sale.order", "get_delivery_so_flow", [], { so_id: so.id }
            );
            const flows = (res && res.flows) || [];
            so.flows = flows;
            this._applyFlowColors(so);
        } catch (e) {
            console.error("get_delivery_so_flow failed:", e);
            so.flows = [];
        } finally {
            so.flows_loading = false;
        }
    }

    // --- Badge Classes (delegate to utils) ---
    getPickingStateBadgeClass(s) { return getPickingStateBadgeClass(s); }
    getPickingStatusBadgeClass(s) { return getPickingStatusBadgeClass(s); }
    getDeliveryStatusBadgeClass(s) { return getDeliveryStatusBadgeClass(s); }
    getStockStatusBadgeClass(s) { return getStockStatusBadgeClass(s); }
    getPackingStatusBadgeClass(s) { return getPackingStatusBadgeClass(s); }
    getPOStatusBadgeClass(state, receipt) { return getPOStatusBadgeClass(state, receipt); }
    getSOCardColorClass(so) { return getSOCardColorClass(so); }

    // --- Formatting (delegate to utils) ---
    formatCurrency(v) { return formatCurrency(v); }
    formatQty(v) { return formatQty(v); }
    getDatesComparisonClass(soDate, poDate) { return getDatesComparisonClass(soDate, poDate); }

    // --- Group duplicate product lines ---
    groupedLines(lines) {
        if (!lines || !lines.length) return [];
        const map = {};
        const order = [];
        for (const l of lines) {
            const pid = l.product_id ? l.product_id[0] : 0;
            if (map[pid]) {
                map[pid].product_uom_qty += (l.product_uom_qty || 0);
                map[pid].qty_delivered += (l.qty_delivered || 0);
                map[pid].qty_packed += (l.qty_packed || 0);
                map[pid].qty_reserved_here += (l.qty_reserved_here || 0); // sum across lines
                // qty_warehouse_free: keep first (product-level, same for all lines of same product/wh)
                map[pid].delivered_subtotal += (l.delivered_subtotal || 0);
                map[pid].delivered_tax += (l.delivered_tax || 0);
                map[pid].delivered_total += (l.delivered_total || 0);
            } else {
                map[pid] = {
                    ...l, product_uom_qty: l.product_uom_qty || 0,
                    qty_delivered: l.qty_delivered || 0, qty_packed: l.qty_packed || 0,
                    qty_available: l.qty_available || 0, qty_warehouse_free: l.qty_warehouse_free || 0,
                    qty_reserved_here: l.qty_reserved_here || 0,
                    delivered_subtotal: l.delivered_subtotal || 0,
                    delivered_tax: l.delivered_tax || 0,
                    delivered_total: l.delivered_total || 0
                };
                order.push(pid);
            }
        }
        return order.map(pid => map[pid]);
    }

    // --- Hover Interactions cho Liên kết Return/Backorder ---
    onPickingHover(pickingName) {
        const safeName = pickingName.split('/').join('-');

        // Highlight chính nó và các node con (Các phiếu return từ nó)
        const childNodes = document.querySelectorAll(`.linked-return-${safeName}`);
        childNodes.forEach(node => {
            node.classList.add('shadow', 'border-warning', 'bg-warning', 'bg-opacity-10');
            node.style.transform = 'scale(1.05)';
        });

        // Nếu nó bè Phiếu Con (return_of / backorder_of) -> Highlight Thẻ Cha 
        const pickingElement = document.querySelector(`[data-picking-name="${safeName}"]`);
        if (pickingElement) {
            // Check nếu chính thẻ này là thẻ con (có return_of)
            const parentClassMatches = Array.from(pickingElement.classList).find(cls => cls.startsWith('linked-return-'));
            if (parentClassMatches) {
                const parentName = parentClassMatches.replace('linked-return-', '');
                const parentNode = document.querySelector(`.original-picking-${parentName}`);
                if (parentNode) {
                    parentNode.classList.add('shadow', 'border-warning', 'bg-warning', 'bg-opacity-10');
                    parentNode.style.transform = 'scale(1.05)';
                }
            }
        }
    }

    onPickingLeave() {
        // Gỡ bỏ toàn bộ hiệu ứng Highlight
        const allHighlighted = document.querySelectorAll('.picking-node');
        allHighlighted.forEach(node => {
            node.classList.remove('shadow', 'border-warning', 'bg-warning', 'bg-opacity-10');
            node.style.transform = 'scale(1)';
        });
    }

    // --- Drawer Actions ---
}
