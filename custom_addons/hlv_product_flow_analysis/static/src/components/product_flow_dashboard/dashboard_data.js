/** @odoo-module **/

import { markup } from "@odoo/owl";

/**
 * Data management mixins: filtered/sorted/paginated data, pagination handlers,
 * export, navigation, formatting helpers.
 */
export const dashboardDataMixins = {
    // ========== Filtered + sorted + paginated data ==========
    get allFilteredProducts() {
        let items = this.state.products;
        const q = this.state.productSearch;
        if (q) {
            items = items.filter(p =>
                p.product_name.toLowerCase().includes(q) ||
                (p.default_code && p.default_code.toLowerCase().includes(q))
            );
        }
        const minCount = this.state.productMinCount;
        if (minCount > 0) {
            items = items.filter(p => p.incoming_count >= minCount);
        }
        return this._sortItems(items, this.state.productSortField, this.state.productSortAsc);
    },

    get filteredProducts() {
        const all = this.allFilteredProducts;
        const start = (this.state.productPage - 1) * this.state.productPageSize;
        return all.slice(start, start + this.state.productPageSize);
    },

    get productTotalPages() {
        return Math.max(1, Math.ceil(this.allFilteredProducts.length / this.state.productPageSize));
    },

    get productTotalFiltered() {
        return this.allFilteredProducts.length;
    },

    get allFilteredSuppliers() {
        let items = this.state.suppliers;
        const q = this.state.supplierSearch;
        if (q) {
            items = items.filter(s => s.partner_name.toLowerCase().includes(q));
        }
        return this._sortItems(items, this.state.supplierSortField, this.state.supplierSortAsc);
    },

    get filteredSuppliers() {
        const all = this.allFilteredSuppliers;
        const start = (this.state.supplierPage - 1) * this.state.supplierPageSize;
        return all.slice(start, start + this.state.supplierPageSize);
    },

    get supplierTotalPages() {
        return Math.max(1, Math.ceil(this.allFilteredSuppliers.length / this.state.supplierPageSize));
    },

    get supplierTotalFiltered() {
        return this.allFilteredSuppliers.length;
    },

    get allFilteredPlanning() {
        let items = this.state.planning;
        // Filter stock-only: default shows only products with qty_available > 0
        if (this.state.planningStockOnly) {
            items = items.filter(p => (p.qty_available || 0) > 0);
        }
        const q = this.state.planningSearch;
        if (q) {
            items = items.filter(p =>
                p.product_name.toLowerCase().includes(q) ||
                (p.default_code && p.default_code.toLowerCase().includes(q))
            );
        }
        if (!this.state.planningShowAll) {
            const minFreq = this.state.planningMinFrequency || 3;
            items = items.filter(p => (p.total_frequency || 0) >= minFreq);
        }
        return this._sortItems(items, this.state.planningSortField, this.state.planningSortAsc);
    },

    get filteredPlanning() {
        const all = this.allFilteredPlanning;
        const start = (this.state.planningPage - 1) * this.state.planningPageSize;
        return all.slice(start, start + this.state.planningPageSize);
    },

    get planningTotalPages() {
        return Math.max(1, Math.ceil(this.allFilteredPlanning.length / this.state.planningPageSize));
    },

    get planningTotalFiltered() {
        return this.allFilteredPlanning.length;
    },

    // ========== Pagination ==========
    onProductPageSizeChange(ev) {
        this.state.productPageSize = parseInt(ev.target.value);
        this.state.productPage = 1;
    },
    productPrevPage() { if (this.state.productPage > 1) this.state.productPage--; },
    productNextPage() { if (this.state.productPage < this.productTotalPages) this.state.productPage++; },

    onSupplierPageSizeChange(ev) {
        this.state.supplierPageSize = parseInt(ev.target.value);
        this.state.supplierPage = 1;
    },
    supplierPrevPage() { if (this.state.supplierPage > 1) this.state.supplierPage--; },
    supplierNextPage() { if (this.state.supplierPage < this.supplierTotalPages) this.state.supplierPage++; },

    onPlanningPageSizeChange(ev) {
        this.state.planningPageSize = parseInt(ev.target.value);
        this.state.planningPage = 1;
    },
    planningPrevPage() { if (this.state.planningPage > 1) this.state.planningPage--; },
    planningNextPage() { if (this.state.planningPage < this.planningTotalPages) this.state.planningPage++; },

    getPageStart(tab) {
        if (tab === "products") return (this.state.productPage - 1) * this.state.productPageSize;
        if (tab === "suppliers") return (this.state.supplierPage - 1) * this.state.supplierPageSize;
        return (this.state.planningPage - 1) * this.state.planningPageSize;
    },

    // ========== Export Excel ==========
    async exportProductExcel() {
        this.state.isExporting = true;
        try {
            const filteredIds = this.allFilteredProducts.map(p => p.product_id);
            const params = { ...this._getParams(), product_ids: filteredIds };
            const b64 = await this.orm.call("product.flow.analysis", "export_product_flow_excel", [], params);
            this._downloadBase64("hang_hoa_luu_thong.xlsx", b64);
            this.notification.add("Xuất Excel thành công!", { type: "success" });
        } catch (e) {
            this.notification.add("Lỗi xuất Excel: " + (e.message || e), { type: "danger" });
        }
        this.state.isExporting = false;
    },

    async exportSupplierExcel() {
        this.state.isExporting = true;
        try {
            const filteredNames = this.allFilteredSuppliers.map(s => s.partner_name);
            const params = { ...this._getParams(), partner_names: filteredNames };
            const b64 = await this.orm.call("product.flow.analysis", "export_supplier_flow_excel", [], params);
            this._downloadBase64("nha_cung_cap.xlsx", b64);
            this.notification.add("Xuất Excel thành công!", { type: "success" });
        } catch (e) {
            this.notification.add("Lỗi xuất Excel: " + (e.message || e), { type: "danger" });
        }
        this.state.isExporting = false;
    },

    _downloadBase64(filename, b64data) {
        const byteChars = atob(b64data);
        const byteNumbers = new Array(byteChars.length);
        for (let i = 0; i < byteChars.length; i++) {
            byteNumbers[i] = byteChars.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], {
            type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    },

    // ========== Supplier expand ==========
    toggleSupplier(partnerId) {
        this.state.expandedSupplier =
            this.state.expandedSupplier === partnerId ? null : partnerId;
    },

    // ========== Trend ==========
    async showProductTrend(productId, productName) {
        this.state.trendProductId = productId;
        this.state.trendProductName = productName;
        try {
            const trends = await this.orm.call("product.flow.analysis", "get_trend_data", [productId, 6]);
            this.state.trendData = trends;
            this.state.showTrend = true;
        } catch (e) {
            this.notification.add("Lỗi tải trend: " + (e.message || e), { type: "danger" });
        }
    },

    closeTrend() {
        this.state.showTrend = false;
    },

    // ========== Product Detail (PO/SO list) ==========
    async showProductDetail(productId, productName) {
        this.state.productDetailId = productId;
        this.state.productDetailName = productName;
        this.state.productDetailLoading = true;
        this.state.showProductDetail = true;
        this.state.productDetailData = { purchase_records: [], sale_records: [] };
        try {
            const params = this._getParams();
            params.product_id = productId;
            const data = await this.orm.call("product.flow.analysis", "get_product_orders", [], params);
            this.state.productDetailData = data;
        } catch (e) {
            this.notification.add("Lỗi tải chi tiết: " + (e.message || e), { type: "danger" });
        }
        this.state.productDetailLoading = false;
    },

    onScatterDotClick(ev) {
        const el = ev.target.closest('circle') || ev.target;
        const productId = parseInt(el.dataset.productId);
        const productName = el.dataset.productName || '';
        if (productId) {
            this.showProductDetail(productId, productName);
        }
    },

    onTreemapClick(ev) {
        const el = ev.target.closest('rect') || ev.target;
        const productId = parseInt(el.dataset.productId);
        const productName = el.dataset.productName || '';
        if (productId) {
            this.showProductDetail(productId, productName);
        }
    },

    closeProductDetail() {
        this.state.showProductDetail = false;
        this.state.productDetailData = { purchase_records: [], sale_records: [] };
    },

    openPurchaseOrder(poId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "purchase.order",
            res_id: poId,
            views: [[false, "form"]],
            target: "new",
        });
    },

    openSaleOrder(soId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: soId,
            views: [[false, "form"]],
            target: "new",
        });
    },

    openPicking(pickingId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: pickingId,
            views: [[false, "form"]],
            target: "new",
        });
    },

    // ========== Recommendation ==========
    getRecommendation(p) {
        const buyQty = p.incoming_qty || 0;
        const sellQty = p.outgoing_qty || 0;
        const buyCount = p.incoming_count || 0;
        const sellCount = p.outgoing_count || 0;
        const stock = p.qty_available || 0;
        const storageDays = p.avg_storage_days || 0;

        // Không có giao dịch
        if (buyCount === 0 && sellCount === 0) {
            return { text: 'Không hoạt động', cls: 'pf-rec-gray', icon: 'fa-minus-circle' };
        }

        // Chỉ mua, không bán
        if (sellCount === 0 && buyCount > 0) {
            if (stock > buyQty * 0.5) {
                return { text: 'Tồn nhiều, chưa bán', cls: 'pf-rec-red', icon: 'fa-exclamation-triangle' };
            }
            return { text: 'Chỉ mua, chưa bán', cls: 'pf-rec-orange', icon: 'fa-question-circle' };
        }

        // Chỉ bán, không mua (trong kỳ)
        if (buyCount === 0 && sellCount > 0) {
            if (stock <= 0) {
                return { text: 'Cần nhập hàng gấp', cls: 'pf-rec-red', icon: 'fa-exclamation-triangle' };
            }
            return { text: 'Bán tốt, cần nhập thêm', cls: 'pf-rec-blue', icon: 'fa-arrow-down' };
        }

        // Tỷ lệ bán/mua
        const sellBuyRatio = sellQty / (buyQty || 1);

        // Bán > mua nhiều → hot product
        if (sellBuyRatio > 1.2) {
            if (stock <= 0) {
                return { text: 'Bán chạy, hết hàng!', cls: 'pf-rec-red', icon: 'fa-fire' };
            }
            if (stock < sellQty * 0.3) {
                return { text: 'Bán chạy, sắp hết', cls: 'pf-rec-orange', icon: 'fa-fire' };
            }
            return { text: 'Bán chạy, nên nhập thêm', cls: 'pf-rec-blue', icon: 'fa-thumbs-up' };
        }

        // Mua > bán nhiều → overstocking
        if (sellBuyRatio < 0.5) {
            if (storageDays > 30) {
                return { text: 'Tồn lâu, giảm mua', cls: 'pf-rec-red', icon: 'fa-arrow-down' };
            }
            return { text: 'Mua nhiều hơn bán', cls: 'pf-rec-orange', icon: 'fa-balance-scale' };
        }

        // Lưu kho lâu
        if (storageDays > 30) {
            return { text: 'Lưu kho lâu, xem lại', cls: 'pf-rec-orange', icon: 'fa-clock-o' };
        }

        // Tồn kho = 0 nhưng có bán
        if (stock <= 0 && sellCount > 0) {
            return { text: 'Hết hàng, cần nhập', cls: 'pf-rec-orange', icon: 'fa-shopping-cart' };
        }

        // Cân đối
        if (storageDays > 0 && storageDays <= 7 && sellBuyRatio >= 0.8) {
            return { text: 'Luân chuyển tốt', cls: 'pf-rec-green', icon: 'fa-check-circle' };
        }

        return { text: 'Ổn định', cls: 'pf-rec-green', icon: 'fa-check' };
    },

    // ========== Navigation ==========
    openProduct(productId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            res_id: productId,
            views: [[false, "form"]],
            target: "current",
        });
    },

    openSupplier(partnerId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: partnerId,
            views: [[false, "form"]],
            target: "current",
        });
    },

    // ========== Helpers ==========
    formatNumber(num) {
        if (num === undefined || num === null) return "0";
        return Number(num).toLocaleString("vi-VN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    },

    formatCurrency(num) {
        if (num === undefined || num === null) return "0 ₫";
        return Number(num).toLocaleString("vi-VN", { minimumFractionDigits: 0, maximumFractionDigits: 0 }) + " ₫";
    },

    getStatusClass(status) {
        return { danger: "pf-status-danger", warning: "pf-status-warning", ok: "pf-status-ok" }[status] || "pf-status-ok";
    },

    getStatusLabel(status) {
        return { danger: "Cần nhập gấp", warning: "Sắp hết", ok: "Đủ hàng" }[status] || "Đủ hàng";
    },

    getTrendBarHeight(value, maxVal) {
        if (!maxVal || maxVal === 0) return "0%";
        return Math.round((value / maxVal) * 100) + "%";
    },

    get trendMaxVal() {
        if (!this.state.trendData.length) return 1;
        let max = 0;
        for (const t of this.state.trendData) {
            if (t.incoming > max) max = t.incoming;
            if (t.outgoing > max) max = t.outgoing;
        }
        return max || 1;
    },

    getHeatClass(value, field) {
        const products = this.state.products;
        if (!products.length || !value) return "";
        const vals = products.map(p => p[field] || 0).filter(v => v > 0);
        if (!vals.length) return "";
        const max = Math.max(...vals);
        const ratio = value / max;
        if (ratio >= 0.75) return "pf-heat-4";
        if (ratio >= 0.5) return "pf-heat-3";
        if (ratio >= 0.25) return "pf-heat-2";
        if (value > 0) return "pf-heat-1";
        return "";
    },

    getBarWidth(value, max) {
        if (!max) return "0%";
        return Math.round((value / max) * 100) + "%";
    },

    // ========== AI Analysis ==========
    async runAiAnalysis() {
        this.state.aiLoading = true;
        this.state.aiError = "";
        this.state.aiAnalysis = "";
        this.state.aiStats = null;
        try {
            const result = await this.orm.call(
                "product.flow.analysis",
                "get_ai_procurement_analysis",
                [],
                {
                    period: this.state.period,
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                    warehouse_id: this.state.warehouseId || false,
                }
            );
            if (result.error) {
                this.state.aiError = result.error;
            } else {
                this.state.aiAnalysis = result.analysis || "";
                this.state.aiStats = result.product_stats || null;
                this.state.aiModel = result.model || "";
                this.state.aiTokens = result.tokens || {};
            }
        } catch (e) {
            this.state.aiError = "Lỗi kết nối: " + (e.message || e);
        }
        this.state.aiLoading = false;
    },

    clearAiAnalysis() {
        this.state.aiAnalysis = "";
        this.state.aiError = "";
        this.state.aiStats = null;
    },

    // ========== AI Chat ==========
    onChatInputChange(ev) {
        this.state.aiChatInput = ev.target.value;
    },

    onChatKeydown(ev) {
        if (ev.key === 'Enter' && !ev.shiftKey) {
            ev.preventDefault();
            this.sendChatMessage();
        }
    },

    async sendChatMessage() {
        const text = (this.state.aiChatInput || '').trim();
        if (!text || this.state.aiChatLoading) return;

        // Add user message
        this.state.aiChatMessages = [
            ...this.state.aiChatMessages,
            { role: 'user', content: text, ts: Date.now() },
        ];
        this.state.aiChatInput = "";
        this.state.aiChatLoading = true;

        // Scroll to bottom
        this._scrollChatToBottom();

        try {
            // Build history (last 10 messages for context)
            const history = this.state.aiChatMessages
                .filter(m => m.role === 'user' || m.role === 'assistant')
                .slice(-10)
                .map(m => ({ role: m.role, content: m.content }));
            // Remove last user message (sent separately)
            history.pop();

            const result = await this.orm.call(
                "product.flow.analysis",
                "chat_with_ai",
                [],
                {
                    user_message: text,
                    conversation_history: history,
                    period: this.state.period,
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                    warehouse_id: this.state.warehouseId || false,
                }
            );

            if (result.error) {
                this.state.aiChatMessages = [
                    ...this.state.aiChatMessages,
                    { role: 'error', content: result.error, ts: Date.now() },
                ];
            } else {
                const msg = {
                    role: 'assistant',
                    content: result.reply || '',
                    model: result.model || '',
                    tokens: result.tokens || {},
                    ts: Date.now(),
                };
                if (result.excel) {
                    msg.excel = result.excel;
                }
                this.state.aiChatMessages = [...this.state.aiChatMessages, msg];
            }
        } catch (e) {
            this.state.aiChatMessages = [
                ...this.state.aiChatMessages,
                { role: 'error', content: 'Lỗi kết nối: ' + (e.message || e), ts: Date.now() },
            ];
        }
        this.state.aiChatLoading = false;
        this._scrollChatToBottom();
    },

    clearChat() {
        this.state.aiChatMessages = [];
        this.state.aiChatInput = "";
    },

    downloadExcel(msg) {
        if (!msg.excel) return;
        const { data, filename } = msg.excel;
        const byteCharacters = atob(data);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename || 'report.xlsx';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    },

    _scrollChatToBottom() {
        setTimeout(() => {
            const el = document.querySelector('.pf-chat-messages');
            if (el) el.scrollTop = el.scrollHeight;
        }, 50);
    },

    useSuggestion(text) {
        this.state.aiChatInput = text;
        this.sendChatMessage();
    },

    /** Convert markdown-like text to safe HTML for display */
    renderMarkdown(text) {
        if (!text) return "";
        let html = text;
        // Escape HTML entities first
        html = html.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        // Headings: ## heading → <h4>
        html = html.replace(/^### (.+)$/gm, '<h5 class="pf-ai-h5">$1</h5>');
        html = html.replace(/^## (.+)$/gm, '<h4 class="pf-ai-h4">$1</h4>');
        // Bold: **text** → <strong>
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        // Italic: *text* → <em>
        html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
        // Bullet lists: - item → <li>
        html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>\n?)+/gs, '<ul class="pf-ai-list">$&</ul>');
        // Numbered lists: 1. item
        html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
        // Line breaks
        html = html.replace(/\n\n/g, '</p><p>');
        html = html.replace(/\n/g, '<br/>');
        html = '<p>' + html + '</p>';
        // Clean up empty paragraphs
        html = html.replace(/<p>\s*<\/p>/g, '');
        html = html.replace(/<p>\s*(<h[45])/g, '$1');
        html = html.replace(/(<\/h[45]>)\s*<\/p>/g, '$1');
        html = html.replace(/<p>\s*(<ul)/g, '$1');
        html = html.replace(/(<\/ul>)\s*<\/p>/g, '$1');
        return markup(html);
    },
};
