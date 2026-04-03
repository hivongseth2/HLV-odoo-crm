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

    /** Month-over-month change percentages for each data point */
    get trendChanges() {
        const data = this.trendMonthlyData;
        return data.map((d, i) => {
            if (i === 0) return { buyQtyChg: null, sellQtyChg: null, buyCountChg: null, sellCountChg: null, buyProdChg: null, sellProdChg: null };
            const prev = data[i - 1];
            const pct = (cur, prv) => prv > 0 ? Math.round((cur - prv) / prv * 100) : (cur > 0 ? 100 : 0);
            return {
                buyQtyChg: pct(d.buy_qty, prev.buy_qty),
                sellQtyChg: pct(d.sell_qty, prev.sell_qty),
                buyCountChg: pct(d.buy_count, prev.buy_count),
                sellCountChg: pct(d.sell_count, prev.sell_count),
                buyProdChg: pct(d.buy_products, prev.buy_products),
                sellProdChg: pct(d.sell_products, prev.sell_products),
            };
        });
    },

    /** Quarterly aggregation from monthly data */
    get trendQuarterlyData() {
        const data = this.trendMonthlyData;
        if (!data.length) return [];
        const qMap = {};
        for (const d of data) {
            const [mm, yy] = d.month.split('/');
            const q = 'Q' + Math.ceil(parseInt(mm) / 3) + '/' + yy;
            if (!qMap[q]) qMap[q] = { quarter: q, buy_qty: 0, sell_qty: 0, buy_count: 0, sell_count: 0, buy_products: new Set(), sell_products: 0, months: 0 };
            qMap[q].buy_qty += d.buy_qty;
            qMap[q].sell_qty += d.sell_qty;
            qMap[q].buy_count += d.buy_count;
            qMap[q].sell_count += d.sell_count;
            qMap[q].buy_products += d.buy_products;
            qMap[q].sell_products += d.sell_products;
            qMap[q].months++;
        }
        return Object.values(qMap);
    },

    get trendMaxQtyQ() {
        const data = this.trendQuarterlyData;
        if (!data.length) return 1;
        return Math.max(...data.map(d => Math.max(d.buy_qty, d.sell_qty)), 1);
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

    getTrendChangeClass(val) {
        if (val === null || val === undefined) return '';
        return val > 0 ? 'pf-chg-up' : (val < 0 ? 'pf-chg-down' : 'pf-chg-flat');
    },

    getTrendChangeIcon(val) {
        if (val === null || val === undefined) return '';
        return val > 0 ? 'fa fa-arrow-up' : (val < 0 ? 'fa fa-arrow-down' : 'fa fa-minus');
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
