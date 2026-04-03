/** @odoo-module **/

/**
 * Product chart getters: top purchased/sold, stock distribution,
 * buy/sell ratio, frequency, heatmap, optimization.
 */
export const productChartMixins = {
    get topPurchasedProducts() {
        return [...this.state.products]
            .filter(p => p.incoming_count > 0)
            .sort((a, b) => b.incoming_count - a.incoming_count)
            .slice(0, 8);
    },

    get topSoldProducts() {
        return [...this.state.products]
            .filter(p => p.outgoing_count > 0)
            .sort((a, b) => b.outgoing_count - a.outgoing_count)
            .slice(0, 8);
    },

    get topPurchasedMax() {
        const items = this.topPurchasedProducts;
        return items.length ? items[0].incoming_count : 1;
    },

    get topSoldMax() {
        const items = this.topSoldProducts;
        return items.length ? items[0].outgoing_count : 1;
    },

    get slowMovingProducts() {
        return [...this.state.products]
            .filter(p => p.qty_available > 0 && p.outgoing_qty === 0 && p.avg_storage_days > 14)
            .sort((a, b) => b.avg_storage_days - a.avg_storage_days)
            .slice(0, 5);
    },

    get fastMovingProducts() {
        return [...this.state.products]
            .filter(p => p.outgoing_count > 0)
            .sort((a, b) => b.outgoing_count - a.outgoing_count)
            .slice(0, 5);
    },

    get purchaseRecommendations() {
        return [...this.state.products]
            .filter(p => {
                if (p.outgoing_qty <= 0) return false;
                const ratio = p.qty_available > 0 ? p.outgoing_qty / p.qty_available : 999;
                return ratio > 0.5;
            })
            .map(p => {
                const ratio = p.qty_available > 0 ? p.outgoing_qty / p.qty_available : 999;
                let urgency = "ok";
                if (ratio > 3) urgency = "danger";
                else if (ratio > 1) urgency = "warning";
                const suggestQty = Math.max(0, Math.round(p.outgoing_qty * 1.2 - p.qty_available));
                return { ...p, ratio: Math.round(ratio * 100) / 100, urgency, suggestQty };
            })
            .sort((a, b) => b.ratio - a.ratio)
            .slice(0, 10);
    },

    get stockDistribution() {
        const products = this.state.products;
        let overstock = 0, healthy = 0, low = 0, outOfStock = 0;
        for (const p of products) {
            if (p.qty_available <= 0) outOfStock++;
            else if (p.outgoing_qty > 0 && p.qty_available < p.outgoing_qty * 0.3) low++;
            else if (p.outgoing_qty > 0 && p.qty_available > p.outgoing_qty * 3) overstock++;
            else healthy++;
        }
        const total = products.length || 1;
        return {
            overstock: { count: overstock, pct: Math.round(overstock / total * 100) },
            healthy: { count: healthy, pct: Math.round(healthy / total * 100) },
            low: { count: low, pct: Math.round(low / total * 100) },
            outOfStock: { count: outOfStock, pct: Math.round(outOfStock / total * 100) },
        };
    },

    // ========== Donut: Tỷ lệ Mua vs Bán (SL) ==========
    get buySellRatioPie() {
        const products = this.state.products;
        const totalBuy = products.reduce((s, p) => s + (p.incoming_qty || 0), 0);
        const totalSell = products.reduce((s, p) => s + (p.outgoing_qty || 0), 0);
        const total = totalBuy + totalSell || 1;
        return {
            buyQty: totalBuy,
            sellQty: totalSell,
            buyPct: Math.round(totalBuy / total * 100),
            sellPct: Math.round(totalSell / total * 100),
            buyDeg: Math.round(totalBuy / total * 360),
        };
    },

    // ========== Donut: Phân bổ tần suất giao dịch ==========
    get frequencyPie() {
        const products = this.state.products;
        let rare = 0, low = 0, medium = 0, high = 0;
        for (const p of products) {
            const freq = (p.incoming_count || 0) + (p.outgoing_count || 0);
            if (freq <= 2) rare++;
            else if (freq <= 5) low++;
            else if (freq <= 10) medium++;
            else high++;
        }
        const total = products.length || 1;
        return {
            rare: { count: rare, pct: Math.round(rare / total * 100) },
            low: { count: low, pct: Math.round(low / total * 100) },
            medium: { count: medium, pct: Math.round(medium / total * 100) },
            high: { count: high, pct: Math.round(high / total * 100) },
            total: products.length,
        };
    },

    // ========== Top SP So sánh Mua vs Bán ==========
    get topBuySellComparison() {
        const items = [...this.state.products]
            .filter(p => p.incoming_qty > 0 || p.outgoing_qty > 0)
            .sort((a, b) => (b.incoming_qty + b.outgoing_qty) - (a.incoming_qty + a.outgoing_qty))
            .slice(0, 10);
        const maxVal = items.length ? Math.max(...items.map(p => Math.max(p.incoming_qty, p.outgoing_qty))) : 1;
        return { items, maxVal };
    },

    // ========== Product Buy/Sell Heatmap ==========
    get productBuySellHeat() {
        const items = [...this.state.products]
            .filter(p => p.incoming_qty > 0 || p.outgoing_qty > 0)
            .sort((a, b) => (b.incoming_count + b.outgoing_count) - (a.incoming_count + a.outgoing_count))
            .slice(0, 12);
        const maxBuyQty = Math.max(...items.map(p => p.incoming_qty), 1);
        const maxSellQty = Math.max(...items.map(p => p.outgoing_qty), 1);
        const maxBuyFreq = Math.max(...items.map(p => p.incoming_count), 1);
        const maxSellFreq = Math.max(...items.map(p => p.outgoing_count), 1);
        return { items, maxBuyQty, maxSellQty, maxBuyFreq, maxSellFreq };
    },

    getHeatLevel(value, max) {
        if (!value || value <= 0) return 0;
        const ratio = value / max;
        if (ratio >= 0.75) return 4;
        if (ratio >= 0.5) return 3;
        if (ratio >= 0.25) return 2;
        return 1;
    },

    // ========== Purchase optimization ==========
    get purchaseOptimization() {
        const items = [...this.state.products]
            .filter(p => p.incoming_qty > 0 || p.outgoing_qty > 0)
            .map(p => {
                const buyFreq = p.incoming_count || 0;
                const sellFreq = p.outgoing_count || 0;
                const buyQty = p.incoming_qty || 0;
                const sellQty = p.outgoing_qty || 0;
                const qtyRatio = buyQty > 0 ? Math.round(sellQty / buyQty * 100) / 100 : (sellQty > 0 ? 999 : 0);
                const freqRatio = buyFreq > 0 ? Math.round(sellFreq / buyFreq * 100) / 100 : (sellFreq > 0 ? 999 : 0);
                let optType;
                if (sellFreq >= 3 && qtyRatio > 1.5) optType = 'underBuy';
                else if (buyFreq >= 3 && qtyRatio < 0.5) optType = 'overBuy';
                else if (sellFreq >= 3 && buyFreq >= 3) optType = 'balanced';
                else optType = 'rare';
                return { ...p, buyFreq, sellFreq, buyQty, sellQty, qtyRatio, freqRatio, optType };
            });
        const underBuy = items.filter(i => i.optType === 'underBuy').sort((a, b) => b.qtyRatio - a.qtyRatio).slice(0, 5);
        const overBuy = items.filter(i => i.optType === 'overBuy').sort((a, b) => a.qtyRatio - b.qtyRatio).slice(0, 5);
        return { underBuy, overBuy };
    },

    getPriorityClass(level) {
        return { high: 'pf-priority-high', medium: 'pf-priority-medium', low: 'pf-priority-low' }[level] || 'pf-priority-low';
    },

    getPriorityLabel(level) {
        return { high: 'Cao', medium: 'TB', low: 'Thấp' }[level] || 'Thấp';
    },
};
