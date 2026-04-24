/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ActionMenus } from "@web/search/action_menus/action_menus";

patch(ActionMenus.prototype, {
    async _loadActions() {
        // Inject active_ids vào context trước khi gọi get_bindings
        const activeIds = this.props.activeIds || [];
        const originalContext = this.env.services.user.context;
        
        // Patch context tạm thời
        if (activeIds.length > 0) {
            this.env.services.orm.context = {
                ...originalContext,
                active_ids: activeIds,
                active_id: activeIds[0],
            };
        }
        
        return super._loadActions(...arguments);
    }
});