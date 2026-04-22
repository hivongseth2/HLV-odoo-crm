/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { session } from "@web/session";

export class MilwaukeeIframeAction extends Component {
    static template = "hlv_milwaukee_embedded.IframeAction";

    setup() {
        this.state = useState({
            url: ""
        });

        onWillStart(async () => {
            const baseUrl = session.milwaukee_base_url || "http://localhost:3000";
            const path = this.props.action.context.iframe_path || "/?embedded=1";
            // ensure no double slashes, handle trailing slashes
            const cleanBaseUrl = baseUrl.replace(/\/$/, "");
            this.state.url = cleanBaseUrl + path;
        });
    }
}

registry.category("actions").add("milwaukee_iframe_action", MilwaukeeIframeAction);
