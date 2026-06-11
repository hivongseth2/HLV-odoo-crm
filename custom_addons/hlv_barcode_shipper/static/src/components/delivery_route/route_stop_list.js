/** @odoo-module **/

import { Component, xml } from "@odoo/owl";
import { formatDistance } from "../../services/route_math";

export class RouteStopList extends Component {
    static props = {
        stops: { type: Array, optional: true },
        started: { type: Boolean, optional: true },
        expanded: { type: Boolean, optional: true },
        onReorder: { type: Function, optional: true },
        onExpand: { type: Function, optional: true },
        onCollapse: { type: Function, optional: true },
        nextDistance: { type: Number, optional: true },
    };

    static template = xml`<div class="hlv-route-sheet" t-att-class="{ 'is-expanded': props.expanded }">
            <div class="hlv-route-sheet-handle"
                 t-on-click="toggleExpanded"
                 t-on-pointerdown="onHandlePointerDown"></div>
            <div class="hlv-route-next">
                <span>DIEM TIEP THEO</span>
                <strong>Cach <t t-esc="formatDistance(props.nextDistance || 0)"/></strong>
            </div>
            <div class="hlv-route-stop-list">
                <t t-foreach="props.stops || []" t-as="stop" t-key="stop.id">
                    <article class="hlv-route-stop"
                             t-att-data-index="stop_index"
                             t-att-class="{ 'is-dragging': draggingId === stop.id }"
                             t-on-pointerdown="(ev) => this.onCardPointerDown(stop_index, stop.id, ev)">
                        <div class="hlv-stop-order"><t t-esc="stop_index + 1"/></div>
                        <div class="hlv-stop-body">
                            <div class="hlv-stop-title">
                                <strong><t t-esc="stop.picking_name"/></strong>
                                <span class="hlv-stop-badge"><span class="hlv-mini-icon">□</span> <t t-esc="stop.item_count"/> kien</span>
                            </div>
                            <div class="hlv-stop-partner"><t t-esc="stop.partner_name"/></div>
                            <div class="hlv-stop-address"><span class="hlv-mini-icon">⌖</span> <t t-esc="stop.address"/></div>
                        </div>
                        <span class="hlv-stop-grip" t-if="!props.started">≡</span>
                    </article>
                </t>
            </div>
        </div>`;

    setup() {
        this.draggingId = null;
        this.draggingIndex = null;
        this.longPressTimer = null;
        this.handleStartY = 0;
    }

    formatDistance(value) {
        return formatDistance(value);
    }

    toggleExpanded() {
        if (this.props.expanded) {
            this.props.onCollapse?.();
        } else {
            this.props.onExpand?.();
        }
    }

    onHandlePointerDown(ev) {
        this.handleStartY = ev.clientY;
        const onMove = (moveEv) => {
            const delta = moveEv.clientY - this.handleStartY;
            if (delta < -20) {
                this.props.onExpand?.();
                cleanup();
            } else if (delta > 20) {
                this.props.onCollapse?.();
                cleanup();
            }
        };
        const cleanup = () => {
            document.removeEventListener("pointermove", onMove);
            document.removeEventListener("pointerup", cleanup);
            document.removeEventListener("pointercancel", cleanup);
        };
        document.addEventListener("pointermove", onMove);
        document.addEventListener("pointerup", cleanup);
        document.addEventListener("pointercancel", cleanup);
    }

    onCardPointerDown(index, id, ev) {
        if (this.props.started || ev.button === 2) {
            return;
        }
        const target = ev.currentTarget;
        const startX = ev.clientX;
        const startY = ev.clientY;

        this.longPressTimer = setTimeout(() => {
            this.draggingId = id;
            this.draggingIndex = index;
            target.setPointerCapture?.(ev.pointerId);
            document.body.classList.add("hlv-route-dragging");
            target.classList.add("is-dragging");
        }, 220);

        const onMove = (moveEv) => {
            const moved = Math.abs(moveEv.clientX - startX) + Math.abs(moveEv.clientY - startY);
            if (!this.draggingId && moved > 12) {
                clearTimeout(this.longPressTimer);
            }
            if (!this.draggingId) {
                return;
            }
            moveEv.preventDefault();
            const element = document.elementFromPoint(moveEv.clientX, moveEv.clientY);
            const row = element?.closest?.(".hlv-route-stop");
            if (!row) {
                return;
            }
            const targetIndex = Number(row.dataset.index);
            if (!Number.isFinite(targetIndex) || targetIndex === this.draggingIndex) {
                return;
            }
            const stops = [...(this.props.stops || [])];
            const [movedStop] = stops.splice(this.draggingIndex, 1);
            stops.splice(targetIndex, 0, movedStop);
            this.draggingIndex = targetIndex;
            this.props.onReorder?.(stops);
        };

        const onUp = () => {
            clearTimeout(this.longPressTimer);
            this.draggingId = null;
            this.draggingIndex = null;
            target.classList.remove("is-dragging");
            document.body.classList.remove("hlv-route-dragging");
            document.removeEventListener("pointermove", onMove);
            document.removeEventListener("pointerup", onUp);
            document.removeEventListener("pointercancel", onUp);
        };

        document.addEventListener("pointermove", onMove, { passive: false });
        document.addEventListener("pointerup", onUp);
        document.addEventListener("pointercancel", onUp);
    }
}
