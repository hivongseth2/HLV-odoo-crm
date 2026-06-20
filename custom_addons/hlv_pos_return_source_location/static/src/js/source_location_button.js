/** @odoo-module **/

import { useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";

const LOCATION_FIELD = "hlv_source_location_id";

patch(ProductScreen.prototype, {
    setup() {
        super.setup();
        this.pos = usePos();
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.hlvSourceLocationCache = {};
        useEffect(
            () => {
                this._hlvRenderSourceLocationButtons();
            },
            () => [this.pos.get_order()?.uiState?.selected_orderline_uuid]
        );
    },

    _hlvGetRecordId(value) {
        if (!value) {
            return false;
        }
        if (Array.isArray(value)) {
            return value[0];
        }
        if (typeof value === "object") {
            return value.id;
        }
        return value;
    },

    _hlvGetProductId(line) {
        return this._hlvGetRecordId(line?.product_id || line?.product || line?.get_product?.());
    },

    _hlvGetSourceLocationId(line) {
        return this._hlvGetRecordId(line?.[LOCATION_FIELD]);
    },

    _hlvGetLineSourceLocationLabel(line) {
        const locationId = this._hlvGetSourceLocationId(line);
        if (!locationId) {
            return "Chọn vị trí lấy hàng";
        }
        const productId = this._hlvGetProductId(line);
        const locations = this.hlvSourceLocationCache[productId] || [];
        const location = locations.find((item) => item.id === locationId);
        return location ? `Lấy: ${location.name}` : `Lấy vị trí #${locationId}`;
    },

    _hlvGetSessionId() {
        const session = this.pos.pos_session || this.pos.session || {};
        return session.id || this.pos.pos_session_id || false;
    },

    async _hlvLoadProductSourceLocations(line) {
        const productId = this._hlvGetProductId(line);
        if (!productId) {
            return [];
        }
        if (!this.hlvSourceLocationCache[productId]) {
            const configId = this.pos.config?.id || false;
            const sessionId = this._hlvGetSessionId();
            this.hlvSourceLocationCache[productId] = await this.orm.call(
                "pos.session",
                "get_product_source_locations",
                [productId, sessionId, configId]
            ) || [];
        }
        return this.hlvSourceLocationCache[productId];
    },

    _hlvRenderSourceLocationButtons() {
        const render = () => {
            const order = this.pos.get_order();
            const lines = order?.get_orderlines?.() || [];
            const nodes = [...document.querySelectorAll(".product-screen .orderline")];
            nodes.forEach((node, index) => {
                const line = lines[index];
                if (!line) {
                    return;
                }
                const container = node.querySelector(".info-list") || node;
                let item = node.querySelector(".hlv-source-location-line");
                if (!item) {
                    item = document.createElement("li");
                    item.className = "hlv-source-location-line";
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "hlv-source-location-button";
                    item.appendChild(button);
                    container.appendChild(item);
                }
                const button = item.querySelector("button");
                button.textContent = this._hlvGetLineSourceLocationLabel(line);
                button.onclick = (ev) => this._hlvOnSourceLocationClick(ev, line);
            });
        };

        render();
        setTimeout(render, 100);
        setTimeout(render, 500);
    },

    async _hlvOnSourceLocationClick(ev, line) {
        ev.preventDefault();
        ev.stopPropagation();

        const locations = await this._hlvLoadProductSourceLocations(line);
        if (!locations.length) {
            this.notification.add("Sản phẩm này chưa có tồn khả dụng ở vị trí kho nào.", { type: "warning" });
            return;
        }

        const currentId = this._hlvGetSourceLocationId(line);
        const list = [
            { id: "default", label: "Mặc định theo quầy POS", item: false, isSelected: !currentId },
            ...locations.map((location) => ({
                id: location.id,
                label: `${location.name} - còn ${location.available_quantity}`,
                item: location,
                isSelected: location.id === currentId,
            })),
        ];

        const selectedLocation = await makeAwaitable(this.dialog, SelectionPopup, {
            title: "Chọn vị trí lấy hàng",
            list,
        });

        if (selectedLocation === undefined) {
            return;
        }

        const value = selectedLocation ? selectedLocation.id : false;
        if (typeof line.update === "function") {
            line.update({ [LOCATION_FIELD]: value });
        } else {
            line[LOCATION_FIELD] = value;
            this.pos.get_order()?.setDirty?.();
        }
        this._hlvRenderSourceLocationButtons();
    },
});
