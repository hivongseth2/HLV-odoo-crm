/** @odoo-module **/

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { onWillUpdateProps, useEffect, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";


const COLLAPSED_CLASS = "o-hlv-chatter-collapsed";

patch(Chatter.prototype, {
    setup() {
        super.setup();
        this.hlvChatterCollapse = useState({ collapsed: true });

        onWillUpdateProps((nextProps) => {
            if (
                this.props.threadId !== nextProps.threadId ||
                this.props.threadModel !== nextProps.threadModel
            ) {
                this.hlvChatterCollapse.collapsed = true;
            }
        });

        useEffect(
            () => {
                const container = this.rootRef.el?.parentElement;
                if (!container) {
                    return;
                }
                container.classList.toggle(
                    COLLAPSED_CLASS,
                    Boolean(this.props.isChatterAside && this.hlvChatterCollapse.collapsed)
                );
                return () => container.classList.remove(COLLAPSED_CLASS);
            },
            () => [this.props.isChatterAside, this.hlvChatterCollapse.collapsed]
        );
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
