/** @odoo-module **/

const PRODUCT_PAGE_SIZE = 50;

export const productManagerMethods = {
    async loadGroupProducts(pageOrEvent) {
        if (!this.state.groupId) return;
        const page = (typeof pageOrEvent === "number") ? pageOrEvent : this.state.groupProductPage;
        this.state.groupProductPage = page;
        this.state.groupProductLoading = true;
        try {
            const result = await this.orm.call(
                "hlv.stock.quick",
                "get_group_products",
                [
                    this.state.groupId,
                    this.state.groupProductQuery.trim(),
                    page * PRODUCT_PAGE_SIZE,
                    PRODUCT_PAGE_SIZE,
                ]
            );
            this.state.groupProducts = result.items;
            this.state.groupProductTotalCount = result.total;
        } finally {
            this.state.groupProductLoading = false;
        }
    },

    onGroupProductQueryKeydown(ev) {
        if (ev.key === "Enter") {
            this.loadGroupProducts(0);
        }
    },

    clearGroupProductQuery() {
        this.state.groupProductQuery = "";
        this.loadGroupProducts(0);
    },

    groupProductsPrev() {
        if (this.state.groupProductPage > 0) {
            this.loadGroupProducts(this.state.groupProductPage - 1);
        }
    },

    groupProductsNext() {
        const maxPage = Math.ceil(this.state.groupProductTotalCount / PRODUCT_PAGE_SIZE) - 1;
        if (this.state.groupProductPage < maxPage) {
            this.loadGroupProducts(this.state.groupProductPage + 1);
        }
    },

    onProductQueryKeydown(ev) {
        if (ev.key === "Enter") {
            this.searchProducts();
        }
    },

    async searchProducts(pageOrEvent) {
        const query = this.state.productQuery.trim();
        if (!query) return;
        const page = (typeof pageOrEvent === "number") ? pageOrEvent : 0;
        this.state.productPage = page;
        this.state.productLoading = true;
        try {
            const result = await this.orm.call(
                "hlv.stock.quick",
                "search_products",
                [query, this.state.groupId, page * PRODUCT_PAGE_SIZE, PRODUCT_PAGE_SIZE]
            );
            this.state.productResults = result.items;
            this.state.productTotalCount = result.total;
        } finally {
            this.state.productLoading = false;
        }
    },

    searchProductsPrev() {
        if (this.state.productPage > 0) {
            this.searchProducts(this.state.productPage - 1);
        }
    },

    searchProductsNext() {
        const maxPage = Math.ceil(this.state.productTotalCount / PRODUCT_PAGE_SIZE) - 1;
        if (this.state.productPage < maxPage) {
            this.searchProducts(this.state.productPage + 1);
        }
    },

    async addProductToGroup(productId) {
        await this.orm.call(
            "hlv.stock.quick",
            "add_product_to_group",
            [this.state.groupId, productId]
        );
        await this.loadGroupProducts(0);
        this.state.productResults = this.state.productResults.filter(p => p.id !== productId);
        if (this.state.productTotalCount > 0) {
            this.state.productTotalCount -= 1;
        }
        if (this.state.productResults.length === 0 && this.state.productPage > 0) {
            await this.searchProducts(this.state.productPage - 1);
        }
        this.markStockDirty();
    },

    async removeProductFromGroup(productId) {
        await this.orm.call(
            "hlv.stock.quick",
            "remove_product_from_group",
            [this.state.groupId, productId]
        );
        if (this.state.groupProducts.length === 1 && this.state.groupProductPage > 0) {
            await this.loadGroupProducts(this.state.groupProductPage - 1);
        } else {
            await this.loadGroupProducts(this.state.groupProductPage);
        }
        if (this.state.productQuery.trim()) {
            await this.searchProducts(this.state.productPage);
        }
        this.markStockDirty();
    },
};
