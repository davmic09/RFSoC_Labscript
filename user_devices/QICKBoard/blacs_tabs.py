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
            f"({props['board_model']}, trigger_mode={props['trigger_mode']})"
        )
        self.get_tab_layout().addWidget(self.status_label)
        self.supports_smart_programming(False)

    def initialise_workers(self):
        props = self.connection_table_properties
        worker_initialisation_kwargs = {
            # NOTE: no need to pass device_name explicitly -- zprocess.Process
            # (Worker's base class) already sets self.device_name itself;
            # passing it again here just triggers a harmless-but-noisy
            # RuntimeWarning about overwriting a base class attribute.
            "ns_host": props["ns_host"],
            "ns_port": props["ns_port"],
            "proxy_name": props["proxy_name"],
            "trigger_mode": props["trigger_mode"],
            "auto_setup": props["auto_setup"],
            "ssh_host": props["ssh_host"],
            "ssh_user": props["ssh_user"],
            "board_env_name": props["board_env_name"],
            "remote_qick_repo_path": props["remote_qick_repo_path"],
            "pynq_venv_path": props["pynq_venv_path"],
        }
        self.create_worker(
            "main_worker",
            "user_devices.QICKBoard.blacs_workers.QICKBoardWorker",
            worker_initialisation_kwargs,
        )
        self.primary_worker = "main_worker"
