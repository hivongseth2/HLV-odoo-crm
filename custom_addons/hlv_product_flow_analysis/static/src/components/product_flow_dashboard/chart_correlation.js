/** @odoo-module **/

/**
 * Correlation deep analytics: ABC Pareto, flow matrix, balance distribution,
 * density heatmap, top imbalanced products, auto insights.
 */
export const correlationChartMixins = {
    // ========== ABC Analysis (Pareto) ==========
    get abcAnalysis() {
        const products = [...this.state.products]
            .filter(p => p.outgoing_qty > 0 || p.incoming_qty > 0)
            .sort((a, b) => b.outgoing_qty - a.outgoing_qty);
        if (!products.length) return null;

        const totalOut = products.reduce((s, p) => s + p.outgoing_qty, 0) || 1;
        let cumulative = 0;
        let aCount = 0, bCount = 0, cCount = 0;
        let aQty = 0, bQty = 0, cQty = 0;

        for (const p of products) {
            cumulative += p.outgoing_qty;
            const cumPct = cumulative / totalOut;
            if (cumPct <= 0.8) { aCount++; aQty += p.outgoing_qty; }
            else if (cumPct <= 0.95) { bCount++; bQty += p.outgoing_qty; }
            else { cCount++; cQty += p.outgoing_qty; }
        }
        const total = products.length;
        return {
            a: { count: aCount, pct: Math.round(aCount / total * 100), qtyPct: Math.round(aQty / totalOut * 100) },
            b: { count: bCount, pct: Math.round(bCount / total * 100), qtyPct: Math.round(bQty / totalOut * 100) },
            c: { count: cCount, pct: Math.round(cCount / total * 100), qtyPct: Math.round(cQty / totalOut * 100) },
            total, totalOut,
        };
    },

    // ========== Flow Matrix 3x3 ==========
    get flowMatrix() {
        const products = this.state.products.filter(p => p.incoming_qty > 0 || p.outgoing_qty > 0);
        if (!products.length) return null;

        const buyQties = products.map(p => p.incoming_qty).sort((a, b) => a - b);
        const sellQties = products.map(p => p.outgoing_qty).sort((a, b) => a - b);
        const percentile = (arr, p) => arr[Math.floor(arr.length * p)] || 0;
        const buyT1 = percentile(buyQties, 0.33) || 1;
        const buyT2 = percentile(buyQties, 0.67) || buyT1 + 1;
        const sellT1 = percentile(sellQties, 0.33) || 1;
        const sellT2 = percentile(sellQties, 0.67) || sellT1 + 1;

        const grid = Array.from({length: 3}, () => Array.from({length: 3}, () => 0));
        for (const p of products) {
            const bLvl = p.incoming_qty <= buyT1 ? 0 : p.incoming_qty <= buyT2 ? 1 : 2;
            const sLvl = p.outgoing_qty <= sellT1 ? 0 : p.outgoing_qty <= sellT2 ? 1 : 2;
            grid[2 - sLvl][bLvl]++;
        }
        const maxCount = Math.max(...grid.flat(), 1);
        return { grid, maxCount, total: products.length };
    },

    getMatrixHeat(count, max) {
        if (!count) return 0;
        const r = count / max;
        if (r >= 0.75) return 4;
        if (r >= 0.5) return 3;
        if (r >= 0.25) return 2;
        return 1;
    },

    // ========== Balance Distribution ==========
    get balanceDistribution() {
        const allProducts = this.state.products;
        if (!allProducts.length) return null;

        const buckets = [
            { label: '< 0.25', min: 0, max: 0.25, count: 0, type: 'heavy-buy' },
            { label: '0.25–0.5', min: 0.25, max: 0.5, count: 0, type: 'over-buy' },
            { label: '0.5–0.8', min: 0.5, max: 0.8, count: 0, type: 'slight-buy' },
            { label: '0.8–1.2', min: 0.8, max: 1.2, count: 0, type: 'balanced' },
            { label: '1.2–2.0', min: 1.2, max: 2.0, count: 0, type: 'slight-sell' },
            { label: '2.0–4.0', min: 2.0, max: 4.0, count: 0, type: 'over-sell' },
            { label: '> 4.0', min: 4.0, max: Infinity, count: 0, type: 'heavy-sell' },
        ];
        let sellOnly = 0, buyOnly = 0;
        for (const p of allProducts) {
            if (p.incoming_qty <= 0 && p.outgoing_qty > 0) { sellOnly++; continue; }
            if (p.incoming_qty > 0 && p.outgoing_qty <= 0) { buyOnly++; continue; }
            if (p.incoming_qty <= 0) continue;
            const ratio = p.outgoing_qty / p.incoming_qty;
            for (const b of buckets) {
                if (ratio >= b.min && (ratio < b.max || (b.max === Infinity && ratio >= b.min))) {
                    b.count++; break;
                }
            }
        }
        const maxCount = Math.max(...buckets.map(b => b.count), 1);
        return { buckets, maxCount, sellOnly, buyOnly };
    },

    // ========== Density Heatmap (log-scale 2D) ==========
    get densityMap() {
        const products = this.state.products.filter(p => p.incoming_qty > 0 || p.outgoing_qty > 0);
        if (!products.length) return null;

        const GS = 7;
        const logBuys = products.map(p => Math.log10(1 + p.incoming_qty));
        const logSells = products.map(p => Math.log10(1 + p.outgoing_qty));
        const maxLB = Math.max(...logBuys, 0.01);
        const maxLS = Math.max(...logSells, 0.01);

        const grid = Array.from({length: GS}, () => Array.from({length: GS}, () => 0));
        for (const p of products) {
            let col = Math.floor((Math.log10(1 + p.incoming_qty) / maxLB) * (GS - 1));
            let row = Math.floor((Math.log10(1 + p.outgoing_qty) / maxLS) * (GS - 1));
            col = Math.min(Math.max(col, 0), GS - 1);
            row = Math.min(Math.max(row, 0), GS - 1);
            grid[GS - 1 - row][col]++;
        }
        const maxCount = Math.max(...grid.flat(), 1);
        const buyLabels = Array.from({length: GS}, (_, i) => Math.round(Math.pow(10, (i / (GS - 1)) * maxLB) - 1));
        const sellLabels = Array.from({length: GS}, (_, i) => Math.round(Math.pow(10, (i / (GS - 1)) * maxLS) - 1));
        return { grid, maxCount, total: products.length, gridSize: GS, buyLabels, sellLabels };
    },

    getDensityLevel(count, max) {
        if (!count) return 0;
        const r = count / max;
        if (r >= 0.7) return 4;
        if (r >= 0.4) return 3;
        if (r >= 0.15) return 2;
        return 1;
    },

    // ========== Top Imbalanced Products ==========
    get topImbalanced() {
        const products = this.state.products
            .filter(p => p.incoming_qty > 0 && p.outgoing_qty > 0)
            .map(p => ({
                ...p,
                ratio: p.outgoing_qty / p.incoming_qty,
                name: p.default_code || p.product_name.substring(0, 20),
            }));
        const highSell = [...products].sort((a, b) => b.ratio - a.ratio).slice(0, 5);
        const highBuy = [...products].sort((a, b) => a.ratio - b.ratio).slice(0, 5);
        return { highSell, highBuy };
    },

    // ========== Correlation Insights ==========
    get correlationInsights() {
        const products = this.state.products.filter(p => p.incoming_qty > 0 || p.outgoing_qty > 0);
        if (!products.length) return [];
        const insights = [];
        const totalBuy = products.reduce((s, p) => s + p.incoming_qty, 0);
        const totalSell = products.reduce((s, p) => s + p.outgoing_qty, 0);

        const ratio = totalBuy > 0 ? totalSell / totalBuy : 0;
        if (ratio > 1.5) insights.push({ type: 'danger', icon: 'fa-exclamation-triangle', text: `Bán gấp ${ratio.toFixed(1)}x mua — rủi ro hết hàng` });
        else if (ratio < 0.5) insights.push({ type: 'warning', icon: 'fa-archive', text: `Mua gấp ${(1/ratio).toFixed(1)}x bán — tồn kho tăng` });
        else insights.push({ type: 'success', icon: 'fa-check-circle', text: `Bán/Mua = ${ratio.toFixed(2)} — cân đối` });

        const sellOnly = this.state.products.filter(p => p.incoming_qty === 0 && p.outgoing_qty > 0).length;
        if (sellOnly > 0) insights.push({ type: 'danger', icon: 'fa-exclamation-circle', text: `${sellOnly} SP bán mà không mua trong kỳ` });

        const buyOnly = this.state.products.filter(p => p.incoming_qty > 0 && p.outgoing_qty === 0).length;
        if (buyOnly > 0) insights.push({ type: 'warning', icon: 'fa-shopping-cart', text: `${buyOnly} SP mua mà chưa bán` });

        const sorted = [...products].sort((a, b) => b.outgoing_qty - a.outgoing_qty);
        const top10n = Math.max(Math.ceil(products.length * 0.1), 1);
        const top10Sell = sorted.slice(0, top10n).reduce((s, p) => s + p.outgoing_qty, 0);
        const top10Pct = totalSell > 0 ? Math.round(top10Sell / totalSell * 100) : 0;
        if (top10Pct > 60) insights.push({ type: 'info', icon: 'fa-bullseye', text: `Top 10% SP chiếm ${top10Pct}% SL bán` });

        return insights;
    },
};
