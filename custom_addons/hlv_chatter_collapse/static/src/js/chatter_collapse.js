/** @odoo-module **/

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { useEffect, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";


const COLLAPSED_CLASS = "o-hlv-chatter-collapsed";
const STORAGE_KEY = "hlv.chatter.aside.collapsed";

patch(Chatter.prototype, {
    setup() {
        super.setup();
        this.hlvChatterCollapse = useState({
            // Start collapsed until the user explicitly chooses to keep it expanded.
            collapsed: browser.localStorage.getItem(STORAGE_KEY) !== "0",
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
        browser.localStorage.setItem(
            STORAGE_KEY,
            this.hlvChatterCollapse.collapsed ? "1" : "0"
        );
    },
});
