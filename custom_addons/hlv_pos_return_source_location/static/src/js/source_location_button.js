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
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        useEffect(
            () => {
                this._hlvRenderSourceLocationButton();
            },
            () => [this.pos.get_order()?.uiState?.selected_orderline_uuid]
        );
    },

    _hlvGetLocations() {
        const records = this.pos.data?.models?.["stock.location"]?.records ||
            this.pos.models?.["stock.location"]?.getAll?.() || [];
        return records
            .filter((location) => location.usage === "internal")
            .sort((a, b) => this._hlvGetLocationName(a).localeCompare(this._hlvGetLocationName(b)));
    },

    _hlvGetLocationName(location) {
        return location?.complete_name || location?.display_name || location?.name || "";
    },

    _hlvGetLocationId(value) {
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

    _hlvGetCurrentLocation(line) {
        const locationId = this._hlvGetLocationId(line?.[LOCATION_FIELD]);
        if (!locationId) {
            return false;
        }
        return this._hlvGetLocations().find((location) => location.id === locationId) || false;
    },

    _hlvGetButtonLabel() {
        const line = this.pos.get_order()?.get_selected_orderline();
        const location = this._hlvGetCurrentLocation(line);
        if (!line) {
            return "Vị trí lấy hàng";
        }
        return location ? `Lấy: ${this._hlvGetLocationName(location)}` : "Vị trí: mặc định";
    },

    _hlvRenderSourceLocationButton() {
        const render = () => {
            const container = document.querySelector(".control-buttons") ||
                document.querySelector(".product-screen .leftpane .pads .subpads") ||
                document.querySelector(".product-screen .leftpane .pads") ||
                document.querySelector(".product-screen .leftpane");
            if (!container) {
                return;
            }

            let button = container.querySelector(".hlv-source-location-button");
            if (!button) {
                button = document.createElement("button");
                button.type = "button";
                button.className = "button btn btn-light hlv-source-location-button";
                button.addEventListener("click", (ev) => this._hlvOnSourceLocationClick(ev));
                container.appendChild(button);
            }
            button.textContent = this._hlvGetButtonLabel();
        };

        render();
        setTimeout(render, 100);
        setTimeout(render, 500);
    },

    async _hlvOnSourceLocationClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();

        const order = this.pos.get_order();
        const line = order?.get_selected_orderline();
        if (!line) {
            this.notification.add("Chọn một dòng sản phẩm trước khi chọn vị trí lấy hàng.", { type: "warning" });
            return;
        }

        const locations = this._hlvGetLocations();
        if (!locations.length) {
            this.notification.add("Không tìm thấy vị trí kho nội bộ cho quầy POS này.", { type: "warning" });
            return;
        }

        const currentId = this._hlvGetLocationId(line[LOCATION_FIELD]);
        const list = [
            { id: "default", label: "Mặc định theo quầy POS", item: false, isSelected: !currentId },
            ...locations.map((location) => ({
                id: location.id,
                label: this._hlvGetLocationName(location),
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

        if (typeof line.update === "function") {
            line.update({ [LOCATION_FIELD]: selectedLocation || false });
        } else {
            line[LOCATION_FIELD] = selectedLocation || false;
            order?.setDirty?.();
        }
        this._hlvRenderSourceLocationButton();
    },
});