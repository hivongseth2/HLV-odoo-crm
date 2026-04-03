/** @odoo-module **/

/**
 * Analysis chart getters: Treemap, Scatter Plot, SVG Heatmap.
 */
export const analysisChartMixins = {

    /** Filter products based on chartFreqOnly: only items with ≥3 transactions */
    _chartFilteredProducts(minQty = 0) {
        let products = this.state.products.filter(p => (p.incoming_qty + p.outgoing_qty) > minQty);
        if (this.state.chartFreqOnly) {
            products = products.filter(p => (p.incoming_count + p.outgoing_count) >= 3);
        }
        return products;
    },

    // ========== Treemap: Product proportion by total quantity ==========
    get treemapData() {
        const n = this.state.topN || 10;
        const products = [...this._chartFilteredProducts()]
            .sort((a, b) => (b.incoming_qty + b.outgoing_qty) - (a.incoming_qty + a.outgoing_qty))
            .slice(0, n);

        if (!products.length) return { rects: [] };

        const W = 400;
        // Scale height: more items need more vertical space
        const H = n <= 15 ? 250 : n <= 30 ? 350 : 450;
        const total = products.reduce((s, p) => s + p.incoming_qty + p.outgoing_qty, 0) || 1;

        const items = products.map(p => {
            const qty = p.incoming_qty + p.outgoing_qty;
            const freq = p.outgoing_count + p.incoming_count;
            const color = freq >= 10 ? '#e03131' : freq >= 5 ? '#ff922b' : freq >= 2 ? '#fcc419' : '#adb5bd';
            return {
                id: p.product_id,
                value: qty,
                label: p.default_code || p.product_name.substring(0, 10),
                name: p.product_name,
                qty,
                freq,
                color,
            };
        });

        const rects = this._layoutTreemap(items, 0, 0, W, H);
        return { rects, width: W, height: H, viewBox: `0 0 ${W} ${H}` };
    },

    _layoutTreemap(items, x, y, w, h) {
        if (!items.length) return [];
        if (items.length === 1) {
            return [{ ...items[0], x, y, w, h }];
        }

        const total = items.reduce((s, i) => s + i.value, 0);
        if (total <= 0) return [];

        let halfSum = 0;
        let splitIdx = 1;
        for (let i = 0; i < items.length - 1; i++) {
            halfSum += items[i].value;
            if (halfSum >= total / 2) {
                splitIdx = i + 1;
                break;
            }
        }

        const left = items.slice(0, splitIdx);
        const right = items.slice(splitIdx);
        const leftSum = left.reduce((s, i) => s + i.value, 0);
        const ratio = leftSum / total;

        if (w >= h) {
            const leftW = w * ratio;
            return [
                ...this._layoutTreemap(left, x, y, leftW, h),
                ...this._layoutTreemap(right, x + leftW, y, w - leftW, h),
            ];
        } else {
            const leftH = h * ratio;
            return [
                ...this._layoutTreemap(left, x, y, w, leftH),
                ...this._layoutTreemap(right, x, y + leftH, w, h - leftH),
            ];
        }
    },

    // ========== Scatter Plot helpers ==========
    _logScale(val, maxVal) {
        if (val <= 0 || maxVal <= 0) return 0;
        return Math.log(val + 1) / Math.log(maxVal + 1);
    },

    _buildScatterData(products, getX, getY, getSizeVal) {
        if (!products.length) return { points: [], show: false };

        const W = 380, H = 280;
        const pad = { l: 42, r: 10, t: 10, b: 30 };
        const plotW = W - pad.l - pad.r;
        const plotH = H - pad.t - pad.b;

        const maxBuy = Math.max(...products.map(p => getX(p))) || 1;
        const maxSell = Math.max(...products.map(p => getY(p))) || 1;

        const buyVals = products.map(p => getX(p)).filter(v => v > 0).sort((a, b) => a - b);
        const sellVals = products.map(p => getY(p)).filter(v => v > 0).sort((a, b) => a - b);
        const medianBuy = buyVals.length ? buyVals[Math.floor(buyVals.length / 2)] : 1;
        const medianSell = sellVals.length ? sellVals[Math.floor(sellVals.length / 2)] : 1;
        const useLog = (maxBuy > medianBuy * 5) || (maxSell > medianSell * 5);

        const scaleX = (v) => useLog ? this._logScale(v, maxBuy) : v / maxBuy;
        const scaleY = (v) => useLog ? this._logScale(v, maxSell) : v / maxSell;

        const points = products.map(p => {
            const xVal = getX(p);
            const yVal = getY(p);
            const x = pad.l + scaleX(xVal) * plotW;
            const y = pad.t + plotH - scaleY(yVal) * plotH;
            const sizeVal = getSizeVal(p);
            const r = Math.min(Math.max(Math.sqrt(sizeVal) * 0.35 + 2, 2.5), 13);

            const ratio = xVal > 0 ? yVal / xVal : (yVal > 0 ? 2 : 0);
            const color = ratio > 1.5 ? '#e03131' : ratio > 0.8 ? '#2b8a3e' : ratio > 0.3 ? '#339af0' : '#868e96';

            return {
                id: p.product_id,
                x: Math.round(x * 10) / 10,
                y: Math.round(y * 10) / 10,
                r: Math.round(r * 10) / 10,
                color,
                label: p.default_code || p.product_name.substring(0, 8),
                name: p.product_name,
                buyVal: xVal,
                sellVal: yVal,
            };
        });

        const tickPositions = [0, 0.25, 0.5, 0.75, 1];
        const xTicks = tickPositions.map(p => {
            const realVal = useLog ? Math.round(Math.pow(maxBuy + 1, p) - 1) : Math.round(maxBuy * p);
            return { x: Math.round(pad.l + p * plotW), label: this.formatNumber(realVal) };
        });
        const yTicks = tickPositions.map(p => {
            const realVal = useLog ? Math.round(Math.pow(maxSell + 1, p) - 1) : Math.round(maxSell * p);
            return { y: Math.round(pad.t + plotH - p * plotH), label: this.formatNumber(realVal) };
        });

        const scale = Math.min(maxBuy, maxSell);
        const diagEndX = pad.l + scaleX(scale) * plotW;
        const diagEndY = pad.t + plotH - scaleY(scale) * plotH;

        return {
            points, show: true,
            W, H, pad, plotW, plotH,
            xTicks, yTicks, useLog,
            axisBottom: pad.t + plotH,
            diagX1: pad.l, diagY1: pad.t + plotH,
            diagX2: diagEndX, diagY2: diagEndY,
        };
    },

    // ========== Scatter Plot: Buy qty (X) vs Sell qty (Y) ==========
    get scatterPlotData() {
        const products = this._chartFilteredProducts();
        return this._buildScatterData(
            products,
            p => p.incoming_qty,
            p => p.outgoing_qty,
            p => p.incoming_qty + p.outgoing_qty
        );
    },

    // ========== Scatter Plot: Buy freq (X) vs Sell freq (Y) ==========
    get scatterFreqData() {
        const products = this._chartFilteredProducts().filter(
            p => (p.incoming_count + p.outgoing_count) > 0
        );
        return this._buildScatterData(
            products,
            p => p.incoming_count,
            p => p.outgoing_count,
            p => p.incoming_count + p.outgoing_count
        );
    },

    // ========== SVG Heatmap: Product × Metrics with color intensity ==========
    get svgHeatmapData() {
        const n = Math.min(this.state.topN || 10, 12);
        const products = [...this._chartFilteredProducts()]
            .sort((a, b) => (b.incoming_qty + b.outgoing_qty) - (a.incoming_qty + a.outgoing_qty))
            .slice(0, n);

        if (!products.length) return { cells: [], show: false };

        const metrics = [
            { key: 'incoming_qty', label: 'Lượng Mua', baseColor: [51, 154, 240] },
            { key: 'incoming_count', label: 'Lần Mua', baseColor: [116, 143, 252] },
            { key: 'outgoing_qty', label: 'Lượng Bán', baseColor: [240, 101, 149] },
            { key: 'outgoing_count', label: 'Lần Bán', baseColor: [255, 107, 107] },
            { key: 'qty_available', label: 'Tồn kho', baseColor: [81, 207, 102] },
        ];

        // Max per metric for normalization
        const maxVals = {};
        for (const m of metrics) {
            maxVals[m.key] = Math.max(...products.map(p => Math.abs(p[m.key] || 0)), 1);
        }

        const labelW = 58, cellW = 44, cellH = 18, headerH = 28, gap = 2;
        const W = labelW + metrics.length * (cellW + gap);
        const H = headerH + products.length * (cellH + gap) + 5;

        const mLabels = metrics.map((m, j) => ({
            x: labelW + j * (cellW + gap) + cellW / 2,
            y: 14,
            text: m.label,
        }));

        const rowLabels = products.map((p, i) => ({
            x: 2,
            y: headerH + i * (cellH + gap) + cellH / 2 + 4,
            text: p.default_code || p.product_name.substring(0, 8),
            title: p.product_name,
        }));

        const cells = [];
        products.forEach((p, i) => {
            metrics.forEach((m, j) => {
                const val = Math.abs(p[m.key] || 0);
                const intensity = val / maxVals[m.key];
                const alpha = Math.max(intensity * 0.85 + 0.12, 0.12);
                const [r, g, b] = m.baseColor;

                cells.push({
                    key: `${p.product_id}_${m.key}`,
                    x: labelW + j * (cellW + gap),
                    y: headerH + i * (cellH + gap),
                    w: cellW,
                    h: cellH,
                    fill: `rgba(${r},${g},${b},${alpha.toFixed(2)})`,
                    val: this.formatNumber(val),
                    title: `${m.label}: ${this.formatNumber(val)}`,
                });
            });
        });

        return { cells, mLabels, rowLabels, W, H, show: true };
    },
};
