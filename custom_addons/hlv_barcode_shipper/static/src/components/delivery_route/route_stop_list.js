/** @odoo-module **/

import { Component } from "@odoo/owl";
import { formatDistance } from "../../services/route_math";

export class RouteStopList extends Component {
    static props = {
        stops: { type: Array, optional: true },
        started: { type: Boolean, optional: true },
        onReorder: { type: Function, optional: true },
        nextDistance: { type: Number, optional: true },
    };

    static template = "hlv_barcode_shipper.RouteStopList";

    setup() {
        this.dragIndex = null;
    }

    formatDistance(value) {
        return formatDistance(value);
    }

    onDragStart(index, ev) {
        if (this.props.started) {
            ev.preventDefault();
            return;
        }
        this.dragIndex = index;
        ev.dataTransfer.effectAllowed = "move";
    }

    onDragOver(ev) {
        if (!this.props.started) {
            ev.preventDefault();
        }
    }

    onDrop(index, ev) {
        ev.preventDefault();
        if (this.dragIndex === null || this.dragIndex === index || this.props.started) {
            this.dragIndex = null;
            return;
        }
        const stops = [...(this.props.stops || [])];
        const [moved] = stops.splice(this.dragIndex, 1);
        stops.splice(index, 0, moved);
        this.dragIndex = null;
        this.props.onReorder?.(stops);
    }
}
