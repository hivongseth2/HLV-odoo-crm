/** @odoo-module **/

/**
 * Drilldown mixin: click any chart element → show filtered product list.
 * Supports: ABC Pareto, Flow Matrix, Balance Distribution, Density Heatmap,
 * Frequency Distribution, Stock Distribution.
 */
export const drilldownMixins = {
    // ========== State helpers ==========
    _initDrilldown() {
        Object.assign(this.state, {
            showDrilldown: false,
            drilldownTitle: "",
            drilldownProducts: [],
        });
    },

    closeDrilldown() {
        this.state.showDrilldown = false;
        this.state.drilldownProducts = [];
    },

    _showDrilldown(title, products) {
        this.state.drilldownTitle = title;
        this.state.drilldownProducts = products.map(p => ({
            product_id: p.product_id,
            product_name: p.product_name,
            default_code: p.default_code || "",
            incoming_qty: p.incoming_qty || 0,
            outgoing_qty: p.outgoing_qty || 0,
            qty_available: p.qty_available || 0,
            incoming_count: p.incoming_count || 0,
            outgoing_count: p.outgoing_count || 0,
        }));
        this.state.showDrilldown = true;
    },

    // ========== ABC Pareto ==========
    drilldownABC(cls) {
        const products = [...this.state.products]
            .filter(p => p.outgoing_qty > 0 || p.incoming_qty > 0)
            .sort((a, b) => b.outgoing_qty - a.outgoing_qty);
        if (!products.length) return;

        const totalOut = products.reduce((s, p) => s + p.outgoing_qty, 0) || 1;
        let cumulative = 0;
        const filtered = [];
        for (const p of products) {
            cumulative += p.outgoing_qty;
            const cumPct = cumulative / totalOut;
            let pClass;
            if (cumPct <= 0.8) pClass = "A";
            else if (cumPct <= 0.95) pClass = "B";
            else pClass = "C";
            if (pClass === cls) filtered.push(p);
        }
        const labels = { A: "Nhóm A (80% SL bán)", B: "Nhóm B (15% SL bán)", C: "Nhóm C (5% SL bán)" };
        this._showDrilldown(`ABC: ${labels[cls]} — ${filtered.length} SP`, filtered);
    },

    // ========== Flow Matrix 3x3 ==========
    drilldownMatrix(rowIdx, colIdx) {
        const products = this.state.products.filter(p => p.incoming_qty > 0 || p.outgoing_qty > 0);
        if (!products.length) return;

        const buyQties = products.map(p => p.incoming_qty).sort((a, b) => a - b);
        const sellQties = products.map(p => p.outgoing_qty).sort((a, b) => a - b);
        const pct = (arr, p) => arr[Math.floor(arr.length * p)] || 0;
        const buyT1 = pct(buyQties, 0.33) || 1;
        const buyT2 = pct(buyQties, 0.67) || buyT1 + 1;
        const sellT1 = pct(sellQties, 0.33) || 1;
        const sellT2 = pct(sellQties, 0.67) || sellT1 + 1;

        const filtered = products.filter(p => {
            const bLvl = p.incoming_qty <= buyT1 ? 0 : p.incoming_qty <= buyT2 ? 1 : 2;
            const sLvl = p.outgoing_qty <= sellT1 ? 0 : p.outgoing_qty <= sellT2 ? 1 : 2;
            return (2 - sLvl) === rowIdx && bLvl === colIdx;
        });

        const buyLabels = ["Thấp", "TB", "Cao"];
        const sellLabels = ["Cao", "TB", "Thấp"];
        const title = `Ma trận: Mua ${buyLabels[colIdx]} × Bán ${sellLabels[rowIdx]} — ${filtered.length} SP`;
        this._showDrilldown(title, filtered);
    },

    // ========== Balance Distribution ==========
    drilldownBalance(bucketIdx) {
        const buckets = [
            { label: "< 0.25", min: 0, max: 0.25 },
            { label: "0.25–0.5", min: 0.25, max: 0.5 },
            { label: "0.5–0.8", min: 0.5, max: 0.8 },
            { label: "0.8–1.2", min: 0.8, max: 1.2 },
            { label: "1.2–2.0", min: 1.2, max: 2.0 },
            { label: "2.0–4.0", min: 2.0, max: 4.0 },
            { label: "> 4.0", min: 4.0, max: Infinity },
        ];
        const bk = buckets[bucketIdx];
        if (!bk) return;

        const filtered = this.state.products.filter(p => {
            if (p.incoming_qty <= 0) return false;
            if (p.outgoing_qty <= 0 && p.incoming_qty > 0) return false;
            const ratio = p.outgoing_qty / p.incoming_qty;
            return ratio >= bk.min && (ratio < bk.max || (bk.max === Infinity && ratio >= bk.min));
        });
        this._showDrilldown(`Tỷ lệ Bán/Mua ${bk.label} — ${filtered.length} SP`, filtered);
    },

    // ========== Balance: Sell-only / Buy-only ==========
    drilldownBalanceSpecial(type) {
        let filtered, title;
        if (type === "sellOnly") {
            filtered = this.state.products.filter(p => p.incoming_qty <= 0 && p.outgoing_qty > 0);
            title = `Chỉ bán (không mua) — ${filtered.length} SP`;
        } else {
            filtered = this.state.products.filter(p => p.incoming_qty > 0 && p.outgoing_qty <= 0);
            title = `Chỉ mua (không bán) — ${filtered.length} SP`;
        }
        this._showDrilldown(title, filtered);
    },

    // ========== Density Heatmap ==========
    drilldownDensity(rowIdx, colIdx) {
        const products = this.state.products.filter(p => p.incoming_qty > 0 || p.outgoing_qty > 0);
        if (!products.length) return;

        const GS = 7;
        const logBuys = products.map(p => Math.log10(1 + p.incoming_qty));
        const logSells = products.map(p => Math.log10(1 + p.outgoing_qty));
        const maxLB = Math.max(...logBuys, 0.01);
        const maxLS = Math.max(...logSells, 0.01);

        const filtered = products.filter(p => {
            let col = Math.floor((Math.log10(1 + p.incoming_qty) / maxLB) * (GS - 1));
            let row = Math.floor((Math.log10(1 + p.outgoing_qty) / maxLS) * (GS - 1));
            col = Math.min(Math.max(col, 0), GS - 1);
            row = Math.min(Math.max(row, 0), GS - 1);
            return (GS - 1 - row) === rowIdx && col === colIdx;
        });

        this._showDrilldown(`Mật độ [${rowIdx + 1}, ${colIdx + 1}] — ${filtered.length} SP`, filtered);
    },

    // ========== Frequency Distribution ==========
    drilldownFrequency(level) {
        const ranges = {
            rare: { min: 0, max: 2, label: "1-2 lần" },
            low: { min: 3, max: 5, label: "3-5 lần" },
            medium: { min: 6, max: 10, label: "6-10 lần" },
            high: { min: 11, max: Infinity, label: ">10 lần" },
        };
        const r = ranges[level];
        if (!r) return;

        const filtered = this.state.products.filter(p => {
            const freq = (p.incoming_count || 0) + (p.outgoing_count || 0);
            return freq >= r.min && freq <= r.max;
        });
        this._showDrilldown(`Tần suất ${r.label} — ${filtered.length} SP`, filtered);
    },

    // ========== Stock Distribution ==========
    drilldownStock(category) {
        const labels = {
            outOfStock: "Hết hàng",
            low: "Sắp hết",
            healthy: "Bình thường",
            overstock: "Tồn nhiều",
        };
        const filtered = this.state.products.filter(p => {
            if (category === "outOfStock") return p.qty_available <= 0;
            if (category === "low") return p.qty_available > 0 && p.outgoing_qty > 0 && p.qty_available < p.outgoing_qty * 0.3;
            if (category === "overstock") return p.qty_available > 0 && p.outgoing_qty > 0 && p.qty_available > p.outgoing_qty * 3;
            // healthy = everything else with qty > 0
            return p.qty_available > 0
                && !(p.outgoing_qty > 0 && p.qty_available < p.outgoing_qty * 0.3)
                && !(p.outgoing_qty > 0 && p.qty_available > p.outgoing_qty * 3);
        });
        this._showDrilldown(`Phân bổ tồn kho: ${labels[category]} — ${filtered.length} SP`, filtered);
    },
};
