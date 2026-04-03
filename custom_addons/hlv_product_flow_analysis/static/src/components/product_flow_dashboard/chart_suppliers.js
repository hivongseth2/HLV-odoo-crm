/** @odoo-module **/

/**
 * Supplier chart getters: heatmap, top suppliers, concentration.
 */
export const supplierChartMixins = {
    get supplierProductHeatmap() {
        const suppliers = [...this.state.suppliers]
            .sort((a, b) => b.total_qty - a.total_qty)
            .slice(0, 10);
        const productMap = new Map();
        for (const s of suppliers) {
            for (const p of (s.products || []).slice(0, 8)) {
                if (!productMap.has(p.product_id)) {
                    productMap.set(p.product_id, { id: p.product_id, name: p.default_code || p.product_name.substring(0, 12) });
                }
            }
        }
        const products = [...productMap.values()].slice(0, 12);
        let maxQty = 1;
        const rows = suppliers.map(s => {
            const prodQtyMap = {};
            for (const p of s.products || []) {
                prodQtyMap[p.product_id] = p.qty;
                if (p.qty > maxQty) maxQty = p.qty;
            }
            return {
                supplierName: s.partner_name,
                cells: products.map(pr => ({ productId: pr.id, qty: prodQtyMap[pr.id] || 0 })),
            };
        });
        return { products, rows, maxQty };
    },

    getHeatmapCellClass(qty, maxQty) {
        if (!qty || qty <= 0) return 'pf-hm-0';
        const ratio = qty / maxQty;
        if (ratio >= 0.75) return 'pf-hm-4';
        if (ratio >= 0.5) return 'pf-hm-3';
        if (ratio >= 0.25) return 'pf-hm-2';
        return 'pf-hm-1';
    },

    get topSuppliersByQty() {
        return [...this.state.suppliers]
            .filter(s => s.total_qty > 0)
            .sort((a, b) => b.total_qty - a.total_qty)
            .slice(0, 8);
    },

    get topSuppliersByQtyMax() {
        const items = this.topSuppliersByQty;
        return items.length ? items[0].total_qty : 1;
    },

    get topSuppliersByAmount() {
        return [...this.state.suppliers]
            .filter(s => s.total_amount > 0)
            .sort((a, b) => b.total_amount - a.total_amount)
            .slice(0, 8);
    },

    get topSuppliersByAmountMax() {
        const items = this.topSuppliersByAmount;
        return items.length ? items[0].total_amount : 1;
    },

    get topSuppliersByFrequency() {
        return [...this.state.suppliers]
            .filter(s => s.move_count > 0)
            .sort((a, b) => b.move_count - a.move_count)
            .slice(0, 8);
    },

    get topSuppliersByFrequencyMax() {
        const items = this.topSuppliersByFrequency;
        return items.length ? items[0].move_count : 1;
    },

    get supplierConcentration() {
        const suppliers = [...this.state.suppliers].sort((a, b) => b.total_amount - a.total_amount);
        const totalAmount = suppliers.reduce((sum, s) => sum + s.total_amount, 0);
        if (!totalAmount || !suppliers.length) return { top1: 0, top3: 0, top5: 0, total: 0, count: 0 };
        const top1 = suppliers.length >= 1 ? Math.round(suppliers[0].total_amount / totalAmount * 100) : 0;
        const top3 = Math.round(suppliers.slice(0, 3).reduce((s, x) => s + x.total_amount, 0) / totalAmount * 100);
        const top5 = Math.round(suppliers.slice(0, 5).reduce((s, x) => s + x.total_amount, 0) / totalAmount * 100);
        return {
            top1, top3, top5,
            total: totalAmount,
            count: suppliers.length,
            top1Name: suppliers.length >= 1 ? suppliers[0].partner_name : '',
            top3Names: suppliers.slice(0, 3).map(s => s.partner_name),
            top5Names: suppliers.slice(0, 5).map(s => s.partner_name),
        };
    },
};
