/** @odoo-module **/

import { Component, xml } from "@odoo/owl";
import { formatDistance } from "../../services/route_math";

export class RouteStopList extends Component {
    static props = {
        stops: { type: Array, optional: true },
        started: { type: Boolean, optional: true },
        onReorder: { type: Function, optional: true },
        nextDistance: { type: Number, optional: true },
    };

    static template = xml`<div class="hlv-route-sheet">
            <div class="hlv-route-sheet-handle"></div>
            <div class="hlv-route-next">
                <span>ĐIỂM TIẾP THEO</span>
                <strong>Cách <t t-esc="formatDistance(props.nextDistance || 0)"/></strong>
            </div>
            <div class="hlv-route-stop-list">
                <t t-foreach="props.stops || []" t-as="stop" t-key="stop.id">
                    <article class="hlv-route-stop"
                             t-att-draggable="!props.started"
                             t-on-dragstart="(ev) => this.onDragStart(stop_index, ev)"
                             t-on-dragover="onDragOver"
                             t-on-drop="(ev) => this.onDrop(stop_index, ev)">
                        <div class="hlv-stop-order"><t t-esc="stop_index + 1"/></div>
                        <div class="hlv-stop-body">
                            <div class="hlv-stop-title">
                                <strong><t t-esc="stop.picking_name"/></strong>
                                <span class="hlv-stop-badge"><i class="fa fa-box"></i> <t t-esc="stop.item_count"/> kiện</span>
                            </div>
                            <div class="hlv-stop-partner"><t t-esc="stop.partner_name"/></div>
                            <div class="hlv-stop-address"><i class="fa fa-map-marker-alt"></i> <t t-esc="stop.address"/></div>
                        </div>
                        <i class="fa fa-grip-lines hlv-stop-grip" t-if="!props.started"></i>
                    </article>
                </t>
            </div>
        </div>`;

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
