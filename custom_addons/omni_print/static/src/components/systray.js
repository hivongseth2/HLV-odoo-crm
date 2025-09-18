/** @odoo-module **/

import { Component, useState } from "@odoo/owl"
import { registry } from "@web/core/registry"
import { useService, useBus } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { useDropdownState } from "@web/core/dropdown/dropdown_hooks";

const CONNECTION_UNKNOWN = "unknown"
const CONNECTION_ONLINE = "online"
const CONNECTION_OFFLINE = "offline"

class PrintTrayMenu extends Component {
    static components = { Dropdown };
    static template = "omni_print.PrintTrayMenu"
    static props = []

    setup() {
        this.state = useState({
            connection: CONNECTION_UNKNOWN,
        })

        this.heartbeatService = useService('print_heartbeat_service')
        this.registerHeartbeatHooks(this.heartbeatService)
        this.dropdown = useDropdownState();
    }

    registerHeartbeatHooks(heartbeatService) {
        useBus(heartbeatService.bus, "onopen", () => {
            this.state.connection = CONNECTION_ONLINE
        })
        useBus(heartbeatService.bus, "onmessage", (event) => {
            this.state.connection = CONNECTION_ONLINE
        })
        useBus(heartbeatService.bus, "onerror", (event) => {
            this.state.connection = CONNECTION_UNKNOWN
        })
        useBus(heartbeatService.bus, "onclose", (event) => {
            this.state.connection = CONNECTION_OFFLINE
        })

        if (heartbeatService.isAlive()) {
            this.state.connection = CONNECTION_ONLINE
        }
    }

    reconnect() {
        if (this.state.connection != CONNECTION_ONLINE) {
            this.heartbeatService.setupConnection()
        }
        this.dropdown.close();
    }

}

registry.category("systray").add("printer_systray", { Component: PrintTrayMenu }, { sequence: 200 })
