from blacs.device_base_class import DeviceTab
from qtutils.qt import QtWidgets


class QICKBoardTab(DeviceTab):
    def initialise_GUI(self):
        self.connection_table_properties = (
            self.settings["connection_table"].find_by_name(self.device_name).properties
        )
        props = self.connection_table_properties
        self.status_label = QtWidgets.QLabel(
            f"QICK @ {props['ns_host']}:{props['ns_port']}/{props['proxy_name']} "
            f"({props['board_model']})"
        )
        self.get_tab_layout().addWidget(self.status_label)
        self.supports_smart_programming(False)

    def initialise_workers(self):
        props = self.connection_table_properties
        worker_initialisation_kwargs = {
            "ns_host": props["ns_host"],
            "ns_port": props["ns_port"],
            "proxy_name": props["proxy_name"],
        }
        self.create_worker(
            "main_worker",
            "user_devices.QICKBoard.blacs_workers.QICKBoardWorker",
            worker_initialisation_kwargs,
        )
        self.primary_worker = "main_worker"
