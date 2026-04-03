/** @odoo-module **/

/**
 * Trend chart getters: monthly buy/sell volume, order counts, MoM comparison.
 */
export const trendChartMixins = {
    get trendMonthlyData() {
        return this.state.trendMonthly || [];
    },

    get trendMaxQty() {
        const data = this.trendMonthlyData;
        if (!data.length) return 1;
        return Math.max(...data.map(d => Math.max(d.buy_qty, d.sell_qty)), 1);
    },

    get trendMaxCount() {
        const data = this.trendMonthlyData;
        if (!data.length) return 1;
        return Math.max(...data.map(d => Math.max(d.buy_count, d.sell_count)), 1);
    },

    get trendMaxProducts() {
        const data = this.trendMonthlyData;
        if (!data.length) return 1;
        return Math.max(...data.map(d => Math.max(d.buy_products, d.sell_products)), 1);
    },

    get trendSummary() {
        const data = this.trendMonthlyData;
        if (data.length < 2) return { lastMonth: null, prevMonth: null, buyChange: 0, sellChange: 0 };
        const last = data[data.length - 1];
        const prev = data[data.length - 2];
        const buyChange = prev.buy_qty > 0
            ? Math.round((last.buy_qty - prev.buy_qty) / prev.buy_qty * 100) : 0;
        const sellChange = prev.sell_qty > 0
            ? Math.round((last.sell_qty - prev.sell_qty) / prev.sell_qty * 100) : 0;
        return { buyChange, sellChange, lastMonth: last, prevMonth: prev };
    },

    async loadTrendData() {
        try {
            const result = await this.orm.call(
                'product.flow.analysis', 'get_aggregate_trend_data', [],
                { warehouse_id: this.state.warehouseId || false },
            );
            this.state.trendMonthly = result.trends || [];
        } catch (e) {
            this.state.trendMonthly = [];
        }
    },
};
