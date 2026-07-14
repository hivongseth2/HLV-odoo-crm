/** @odoo-module **/

import { messageActionsRegistry } from "@mail/core/common/message_actions";


const deleteAction = messageActionsRegistry.get("delete");
const originalDeleteCondition = deleteAction.condition;

deleteAction.condition = (component) =>
    !component.env.inChatter && originalDeleteCondition(component);
