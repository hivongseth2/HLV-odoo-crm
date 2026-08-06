/** @odoo-module **/

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";


patch(Chatter.prototype, {
    setup() {
        super.setup();
        this.hlvChatterCollapse = useState({ collapsed: false });

        onWillUpdateProps((nextProps) => {
            if (
                this.props.threadId !== nextProps.threadId ||
                this.props.threadModel !== nextProps.threadModel
            ) {
                this.hlvChatterCollapse.collapsed = false;
            }
        });
    },

    get hlvChatterToggleTitle() {
        return this.hlvChatterCollapse.collapsed
            ? _t("Expand chatter")
            : _t("Collapse chatter");
    },

    toggleHlvChatter() {
        this.hlvChatterCollapse.collapsed = !this.hlvChatterCollapse.collapsed;
    },
});
