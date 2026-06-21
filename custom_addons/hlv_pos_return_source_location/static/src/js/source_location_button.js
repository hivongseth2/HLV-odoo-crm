/** @odoo-module **/

import { Component, useEffect, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { usePos } from "@point_of_sale/app/store/pos_hook";

const LOCATION_FIELD = "hlv_source_location_id";
const ALLOCATION_FIELD = "hlv_source_location_allocations";

export class SourceLocationAllocationPopup extends Component {
    static template = "hlv_pos_return_source_location.SourceLocationAllocationPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        lineQty: Number,
        locations: Array,
        initialAllocations: Array,
        onSave: Function,
    };

    setup() {
        this.notification = useService("notification");
        const allocations = {};
        for (const item of this.props.initialAllocations || []) {
            allocations[item.location_id] = item.qty;
        }
        if (!Object.keys(allocations).length && this.props.locations.length) {
            for (const item of this._buildDefaultAllocations(this.props.lineQty, this.props.locations)) {
                allocations[item.location_id] = item.qty;
            }
        }
        this.state = useState({ allocations });
        this.onQtyInput = (locationId, ev) => {
            const qty = Math.max(0, parseFloat(ev.target.value || "0") || 0);
            this.state.allocations[locationId] = qty;
        };
        this.clearAll = () => {
            for (const location of this.props.locations) {
                this.state.allocations[location.id] = 0;
            }
        };
        this.save = () => this._save();
    }

    _buildDefaultAllocations(qty, locations) {
        let remaining = qty;
        const result = [];
        for (const location of locations) {
            if (remaining <= 0) {
                break;
            }
            const available = parseFloat(location.available_quantity || 0) || 0;
            const takeQty = Math.min(available, remaining);
            if (takeQty > 0) {
                result.push({
                    location_id: location.id,
                    location_name: location.name,
                    qty: takeQty,
                });
                remaining -= takeQty;
            }
        }
        return result;
    }

    getQty(locationId) {
        return this.state.allocations[locationId] || 0;
    }

    get totalQty() {
        return Object.values(this.state.allocations).reduce((sum, qty) => sum + (parseFloat(qty) || 0), 0);
    }

    _save() {
        const total = this.totalQty;
        if (Math.abs(total - this.props.lineQty) > 0.0001) {
            this.notification.add(`T\u1ed5ng s\u1ed1 l\u01b0\u1ee3ng ph\u00e2n b\u1ed5 ph\u1ea3i b\u1eb1ng ${this.props.lineQty}. Hi\u1ec7n t\u1ea1i: ${total}.`, { type: "warning" });
            return;
        }
        for (const location of this.props.locations) {
            const qty = parseFloat(this.state.allocations[location.id] || 0) || 0;
            if (qty > location.available_quantity + 0.0001) {
                this.notification.add(`${location.name} ch\u1ec9 c\u00f2n ${location.available_quantity}.`, { type: "warning" });
                return;
            }
        }
        const allocations = this.props.locations
            .map((location) => ({
                location_id: location.id,
                location_name: location.name,
                qty: parseFloat(this.state.allocations[location.id] || 0),
            }))
            .filter((item) => item.qty > 0);
        this.props.onSave(allocations);
        this.props.close();
    }
}

patch(ProductScreen.prototype, {
    setup() {
        super.setup();
        this.pos = usePos();
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.hlvSourceLocationCache = {};
        this.hlvDefaultAllocationPromises = {};
        useEffect(
            () => {
                this._hlvRenderSourceLocationButtons();
            },
            () => {
                const order = this.pos.get_order();
                const lines = order?.get_orderlines?.() || [];
                return [
                    order?.uiState?.selected_orderline_uuid,
                    lines.length,
                    ...lines.map((line) => `${this._hlvGetLineKey(line)}:${this._hlvGetLineQty(line)}:${line[ALLOCATION_FIELD] || ""}`),
                ];
            }
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

    _hlvGetLineQty(line) {
        const qty = typeof line?.get_quantity === "function" ? line.get_quantity() : line?.qty;
        return Math.abs(parseFloat(qty || 0) || 0);
    },

    _hlvGetLineKey(line) {
        return line?.uuid || line?.cid || line?.id || line;
    },

    _hlvParseAllocations(line) {
        const raw = line?.[ALLOCATION_FIELD];
        if (!raw) {
            const locationId = this._hlvGetRecordId(line?.[LOCATION_FIELD]);
            return locationId ? [{ location_id: locationId, location_name: `#${locationId}`, qty: this._hlvGetLineQty(line) }] : [];
        }
        if (Array.isArray(raw)) {
            return raw;
        }
        try {
            return JSON.parse(raw) || [];
        } catch (_error) {
            return [];
        }
    },

    _hlvGetReservedSourceQtyByLocation(currentLine) {
        const order = this.pos.get_order();
        const currentKey = this._hlvGetLineKey(currentLine);
        const productId = this._hlvGetProductId(currentLine);
        const reserved = {};
        for (const line of order?.get_orderlines?.() || []) {
            if (this._hlvGetLineKey(line) === currentKey || this._hlvGetProductId(line) !== productId) {
                continue;
            }
            for (const allocation of this._hlvParseAllocations(line)) {
                const locationId = allocation.location_id;
                reserved[locationId] = (reserved[locationId] || 0) + (parseFloat(allocation.qty) || 0);
            }
        }
        return reserved;
    },

    _hlvApplyCartReservations(locations, line) {
        const reserved = this._hlvGetReservedSourceQtyByLocation(line);
        return locations.map((location) => ({
            ...location,
            available_quantity: Math.max(0, (parseFloat(location.available_quantity || 0) || 0) - (reserved[location.id] || 0)),
        }));
    },

    _hlvGetLineSourceLocationLabel(line) {
        const allocations = this._hlvParseAllocations(line);
        const qty = this._hlvGetLineQty(line);
        const total = allocations.reduce((sum, item) => sum + (parseFloat(item.qty) || 0), 0);
        if (!allocations.length) {
            return "Chọn vị trí lấy hàng";
        }
        if (Math.abs(total - qty) > 0.0001) {
            return `Phân bổ ${total}/${qty}`;
        }
        return allocations.length === 1 ? `Lấy: ${allocations[0].location_name}` : `${allocations.length} vị trí lấy hàng`;
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

    _hlvBuildDefaultAllocations(qty, locations) {
        let remaining = qty;
        const result = [];
        for (const location of locations) {
            if (remaining <= 0) {
                break;
            }
            const available = parseFloat(location.available_quantity || 0) || 0;
            const takeQty = Math.min(available, remaining);
            if (takeQty > 0) {
                result.push({
                    location_id: location.id,
                    location_name: location.name,
                    qty: takeQty,
                });
                remaining -= takeQty;
            }
        }
        return result;
    },

    _hlvSetLineAllocations(line, allocations) {
        const firstLocationId = allocations[0]?.location_id || false;
        const values = {
            [LOCATION_FIELD]: firstLocationId,
            [ALLOCATION_FIELD]: JSON.stringify(allocations),
        };
        if (typeof line.update === "function") {
            line.update(values);
        }
        line[LOCATION_FIELD] = firstLocationId;
        line[ALLOCATION_FIELD] = values[ALLOCATION_FIELD];
        this.pos.get_order()?.setDirty?.();
    },

    async _hlvEnsureDefaultAllocation(line) {
        const qty = this._hlvGetLineQty(line);
        if (qty <= 0) {
            return;
        }
        const currentAllocations = this._hlvParseAllocations(line);
        const currentTotal = currentAllocations.reduce((sum, item) => sum + (parseFloat(item.qty) || 0), 0);
        if (currentAllocations.length && Math.abs(currentTotal - qty) <= 0.0001) {
            return;
        }
        const productId = this._hlvGetProductId(line);
        const key = line.uuid || line.id || `${productId}-${qty}`;
        if (!productId || this.hlvDefaultAllocationPromises[key]) {
            return;
        }
        this.hlvDefaultAllocationPromises[key] = true;
        try {
            const locations = this._hlvApplyCartReservations(await this._hlvLoadProductSourceLocations(line), line);
            const allocations = this._hlvBuildDefaultAllocations(qty, locations);
            if (allocations.length) {
                this._hlvSetLineAllocations(line, allocations);
                this._hlvRenderSourceLocationButtons();
            }
        } finally {
            delete this.hlvDefaultAllocationPromises[key];
        }
    },

    _hlvRenderAllocationSummary(item, line) {
        let summary = item.querySelector(".hlv-source-location-summary");
        if (!summary) {
            summary = document.createElement("div");
            summary.className = "hlv-source-location-summary";
            item.appendChild(summary);
        }
        const allocations = this._hlvParseAllocations(line);
        summary.innerHTML = "";
        for (const allocation of allocations) {
            const row = document.createElement("div");
            row.className = "hlv-source-location-summary-row";
            row.textContent = `${allocation.location_name}: ${allocation.qty}`;
            summary.appendChild(row);
        }
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
                this._hlvEnsureDefaultAllocation(line);
                const button = item.querySelector("button");
                button.textContent = this._hlvGetLineSourceLocationLabel(line);
                button.onclick = (ev) => this._hlvOnSourceLocationClick(ev, line);
                this._hlvRenderAllocationSummary(item, line);
            });
        };

        render();
        setTimeout(render, 100);
        setTimeout(render, 500);
    },

    async _hlvOnSourceLocationClick(ev, line) {
        ev.preventDefault();
        ev.stopPropagation();

        const locations = this._hlvApplyCartReservations(await this._hlvLoadProductSourceLocations(line), line);
        if (!locations.length) {
            this.notification.add("Sản phẩm này chưa có tồn khả dụng ở vị trí kho nào.", { type: "warning" });
            return;
        }

        this.dialog.add(SourceLocationAllocationPopup, {
            lineQty: this._hlvGetLineQty(line),
            locations,
            initialAllocations: this._hlvParseAllocations(line),
            onSave: (allocations) => {
                this._hlvSetLineAllocations(line, allocations);
                this._hlvRenderSourceLocationButtons();
            },
        });
    },
});
