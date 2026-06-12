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
                 t-on-click="toggleSheet"
                 t-on-pointerdown="onHandlePointerDown">
                <span></span>
            </div>
            <div class="hlv-route-next">
                <span>DIEM TIEP THEO</span>
                <strong>Cach <t t-esc="formatDistance(props.nextDistance || 0)"/></strong>
            </div>
            <div class="hlv-route-stop-list">
                <t t-foreach="props.stops || []" t-as="stop" t-key="stop.id">
                    <article class="hlv-route-stop"
                             t-att-data-index="stop_index"
                             t-att-class="{ 'is-dragging': draggingId === stop.id }">
                        <div class="hlv-stop-order"><t t-esc="stop_index + 1"/></div>
                        <div class="hlv-stop-body">
                            <div class="hlv-stop-title">
                                <strong><t t-esc="stop.picking_name"/></strong>
                                <span class="hlv-stop-badge">□ <t t-esc="stop.item_count"/> kien</span>
                            </div>
                            <div class="hlv-stop-partner"><t t-esc="stop.partner_name"/></div>
                            <div class="hlv-stop-address">⌖ <t t-esc="stop.address"/></div>
                        </div>
                        <button class="hlv-stop-grip"
                                t-if="!props.started"
                                t-on-pointerdown="(ev) => this.onGripPointerDown(stop_index, stop.id, ev)"
                                title="Nhan giu de sap xep">≡</button>
                    </article>
                </t>
            </div>
        </div>`;

    setup() {
        this.draggingId = null;
        this.draggingIndex = null;
        this.longPressTimer = null;
        this.handleStartY = 0;
        this.handleMoved = false;
        this.lastTargetIndex = null;
        this.dragGhost = null;
        this.dragOffsetY = 0;
    }

    formatDistance(value) {
        return formatDistance(value);
    }

    onHandlePointerDown(ev) {
        ev.preventDefault();
        this.handleStartY = ev.clientY;
        this.handleMoved = false;
        ev.currentTarget?.setPointerCapture?.(ev.pointerId);
        const onMove = (moveEv) => {
            moveEv.preventDefault();
            const delta = moveEv.clientY - this.handleStartY;
            if (delta < -14) {
                this.handleMoved = true;
                this.props.onExpand?.();
                cleanup();
            } else if (delta > 14) {
                this.handleMoved = true;
                this.props.onCollapse?.();
                cleanup();
            }
        };
        const cleanup = () => {
            document.removeEventListener("pointermove", onMove);
            document.removeEventListener("pointerup", cleanup);
            document.removeEventListener("pointercancel", cleanup);
        };
        document.addEventListener("pointermove", onMove, { passive: false });
        document.addEventListener("pointerup", cleanup);
        document.addEventListener("pointercancel", cleanup);
    }

    toggleSheet() {
        if (this.handleMoved) {
            this.handleMoved = false;
            return;
        }
        if (this.props.expanded) {
            this.props.onCollapse?.();
        } else {
            this.props.onExpand?.();
        }
    }

    onGripPointerDown(index, id, ev) {
        if (this.props.started || ev.button === 2) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();

        const grip = ev.currentTarget;
        const card = grip.closest(".hlv-route-stop");
        const startX = ev.clientX;
        const startY = ev.clientY;

        this.longPressTimer = setTimeout(() => {
            this.draggingId = id;
            this.draggingIndex = index;
            this.lastTargetIndex = index;
            grip.setPointerCapture?.(ev.pointerId);
            document.body.classList.add("hlv-route-dragging");
            card?.classList.add("is-dragging");
            this.createDragGhost(card, ev.clientX, ev.clientY);
        }, 140);

        const onMove = (moveEv) => {
            const moved = Math.abs(moveEv.clientX - startX) + Math.abs(moveEv.clientY - startY);
            if (!this.draggingId && moved > 10) {
                clearTimeout(this.longPressTimer);
                return;
            }
            if (!this.draggingId) {
                return;
            }

            moveEv.preventDefault();
            this.moveDragGhost(moveEv.clientX, moveEv.clientY);
            const element = document.elementFromPoint(moveEv.clientX, moveEv.clientY);
            const targetCard = element?.closest?.(".hlv-route-stop");
            if (!targetCard) {
                return;
            }
            const targetIndex = Number(targetCard.dataset.index);
            if (!Number.isFinite(targetIndex) || targetIndex === this.draggingIndex || targetIndex === this.lastTargetIndex) {
                return;
            }

            window.requestAnimationFrame(() => {
                const stops = [...(this.props.stops || [])];
                const [movedStop] = stops.splice(this.draggingIndex, 1);
                stops.splice(targetIndex, 0, movedStop);
                this.draggingIndex = targetIndex;
                this.lastTargetIndex = targetIndex;
                this.props.onReorder?.(stops);
            });
        };

        const onUp = () => {
            clearTimeout(this.longPressTimer);
            this.draggingId = null;
            this.draggingIndex = null;
            this.lastTargetIndex = null;
            card?.classList.remove("is-dragging");
            this.removeDragGhost();
            document.body.classList.remove("hlv-route-dragging");
            document.removeEventListener("pointermove", onMove);
            document.removeEventListener("pointerup", onUp);
            document.removeEventListener("pointercancel", onUp);
        };

        document.addEventListener("pointermove", onMove, { passive: false });
        document.addEventListener("pointerup", onUp);
        document.addEventListener("pointercancel", onUp);
    }

    createDragGhost(card, x, y) {
        if (!card) {
            return;
        }
        const rect = card.getBoundingClientRect();
        this.dragOffsetY = y - rect.top;
        const ghost = card.cloneNode(true);
        ghost.classList.add("hlv-route-drag-ghost");
        ghost.style.width = `${rect.width}px`;
        ghost.style.left = `${rect.left}px`;
        ghost.style.top = `${rect.top}px`;
        ghost.style.transform = "translate3d(0,0,0)";
        document.body.appendChild(ghost);
        this.dragGhost = ghost;
    }

    moveDragGhost(x, y) {
        if (!this.dragGhost) {
            return;
        }
        this.dragGhost.style.top = `${y - this.dragOffsetY}px`;
    }

    removeDragGhost() {
        this.dragGhost?.remove();
        this.dragGhost = null;
    }
}
