from blacs.device_base_class import DeviceTab
from blacs.tab_base_classes import define_state, MODE_MANUAL
from qtutils import inmain_decorator
from qtutils.qt import QtWidgets, QtGui

from labscript_devices.QICKBoard.manual_programs import (
    MANUAL_PROGRAMS, CONNECTION_TABLE_PROGRAM,
)


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

        self.program_combo = QtWidgets.QComboBox()
        # No class name shown here -- tproc_program_module/class live only in
        # device_properties (can legitimately vary per shot via
        # set_tproc_program()), not in this compile-time connection_table_properties
        # snapshot. The worker resolves the actual current value fresh from the
        # connection table file when this option is run; the resolved class name
        # then appears in the result text box.
        self.program_combo.addItem("Connection table program", CONNECTION_TABLE_PROGRAM)
        for name in MANUAL_PROGRAMS:
            self.program_combo.addItem(name, name)

        self.start_button = QtWidgets.QPushButton("Start")
        self.stop_button = QtWidgets.QPushButton("Stop / reset outputs")
        self.start_button.clicked.connect(self.on_start_clicked)
        self.stop_button.clicked.connect(self.on_stop_clicked)

        controls_layout = QtWidgets.QHBoxLayout()
        controls_layout.addWidget(self.program_combo)
        controls_layout.addWidget(self.start_button)
        controls_layout.addWidget(self.stop_button)
        controls_widget = QtWidgets.QWidget()
        controls_widget.setLayout(controls_layout)

        self.manual_output = QtWidgets.QPlainTextEdit()
        self.manual_output.setReadOnly(True)
        self.manual_output.setFont(QtGui.QFont("Courier"))
        self.manual_output.setPlaceholderText(
            "Select a program and click Start. The board's hardware report "
            "(soc info) will be shown here, confirming the RFSoC received it."
        )

        group_box = QtWidgets.QGroupBox("Manual Program Control")
        group_layout = QtWidgets.QVBoxLayout()
        group_layout.addWidget(controls_widget)
        group_layout.addWidget(self.manual_output)
        group_box.setLayout(group_layout)
        self.get_tab_layout().addWidget(group_box)

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
            "labscript_devices.QICKBoard.blacs_workers.QICKBoardWorker",
            worker_initialisation_kwargs,
        )
        self.primary_worker = "main_worker"

    @inmain_decorator()
    def _show_result(self, result):
        # Called from _run_manual_program/_stop_manual_program's @define_state
        # generators, after their yield -- that continuation runs on BLACS's
        # tab state-machine thread, not reliably the Qt GUI thread, so widget
        # access here must be marshalled via inmain_decorator (matching
        # IMAQdxCameraTab.update_text_slot's identical pattern) rather than
        # called directly.
        self.manual_output.setPlainText(f"{result['status']}\n\n{result['soc_info']}")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(True)

    def on_start_clicked(self, button):
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        program_key = self.program_combo.currentData()
        self._run_manual_program(program_key)

    @define_state(MODE_MANUAL, queue_state_indefinitely=True, delete_stale_states=True)
    def _run_manual_program(self, program_key):
        result = yield (
            self.queue_work(self.primary_worker, 'run_manual_program', program_key)
        )
        self._show_result(result)

    def on_stop_clicked(self, button):
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self._stop_manual_program()

    @define_state(MODE_MANUAL, queue_state_indefinitely=True, delete_stale_states=True)
    def _stop_manual_program(self):
        result = yield (self.queue_work(self.primary_worker, 'stop_manual_program'))
        self._show_result(result)
