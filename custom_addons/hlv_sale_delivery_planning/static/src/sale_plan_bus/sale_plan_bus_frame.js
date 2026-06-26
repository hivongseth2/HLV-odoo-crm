/** @odoo-module **/

import { Component, onWillDestroy, onWillStart, xml } from "@odoo/owl";
import { mountComponent } from "@web/env";
import { useService } from "@web/core/utils/hooks";
import { whenReady } from "@odoo/owl";

class SalePlanPublicBusFrame extends Component {
    static template = xml`<div/>`;

    setup() {
        this.busService = useService("bus_service");
        this._onMention = (payload) => this._postMention(payload);
        onWillStart(() => {
            this.busService.addChannel("sale_plan_public_channel");
            this.busService.subscribe("sale_plan_mention", this._onMention);
            this._postStatus("listening");
        });
        onWillDestroy(() => {
            this.busService.unsubscribe("sale_plan_mention", this._onMention);
            this.busService.deleteChannel("sale_plan_public_channel");
            this._postStatus("closed");
        });
    }

    _postStatus(status) {
        try {
            window.parent?.HLVSalePlanMentionBus?.onStatus?.(status);
        } catch (e) {
            // Parent may be unavailable during navigation.
        }
    }

    _postMention(payload) {
        try {
            window.parent?.HLVSalePlanMentionBus?.onEvent?.(payload || {});
        } catch (e) {
            // Parent may be unavailable during navigation.
        }
    }
}

whenReady(async () => {
    const root = document.getElementById("sale_plan_bus_frame_root");
    if (!root) return;
    try {
        await mountComponent(SalePlanPublicBusFrame, root, { dev: false });
    } catch (error) {
        try {
            window.parent?.HLVSalePlanMentionBus?.onStatus?.("error");
        } catch (e) {}
        console.error("Sale Plan public bus frame mount error", error);
    }
});
