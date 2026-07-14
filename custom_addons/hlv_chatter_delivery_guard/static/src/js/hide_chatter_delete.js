/** @odoo-module **/

import { onWillStart, useComponent, useState } from "@odoo/owl";
import { messageActionsRegistry } from "@mail/core/common/message_actions";
import { user } from "@web/core/user";


const deleteAction = messageActionsRegistry.get("delete");
const originalDeleteCondition = deleteAction.condition;
const originalDeleteSetup = deleteAction.setup;

deleteAction.setup = (action) => {
    originalDeleteSetup?.(action);
    const component = useComponent();
    component.hlvChatterDeleteAccess = useState({ allowed: false });
    onWillStart(async () => {
        component.hlvChatterDeleteAccess.allowed = await user.hasGroup(
            "hlv_chatter_delivery_guard.group_delete_chatter_message"
        );
    });
};

deleteAction.condition = (component) => {
    if (!component.env.inChatter) {
        return originalDeleteCondition(component);
    }
    return Boolean(
        component.hlvChatterDeleteAccess?.allowed
        && component.message.message_type === "comment"
        && component.message.trackingValues.length === 0
    );
};
