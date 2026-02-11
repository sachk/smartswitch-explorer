from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, QThreadPool
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget

from smartswitch_core.applications.decrypt_extract import decrypt_extract_app
from smartswitch_core.export import make_export_root
from smartswitch_core.messages.decode import decode_and_export_messages
from smartswitch_core.metadata import enrich_inventory
from smartswitch_core.scan import build_inventory, find_backups, is_backup_dir
from gui.config import load_settings, save_settings
from gui.ui.explorer_page import ExplorerPage
from gui.ui.landing_page import LandingPage
from gui.ui.workers import FunctionWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SmartSwitch Explorer")
        self.resize(QSize(544, 720))

        self.thread_pool = QThreadPool(self)
        self.settings = load_settings()
        self.current_backup: Path | None = None

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.landing_page = LandingPage()
        self.explorer_page = ExplorerPage()
        self.explorer_page.set_destination(Path(self.settings["destination"]))

        self.stack.addWidget(self.landing_page)
        self.stack.addWidget(self.explorer_page)

        self.landing_page.backup_selected.connect(self._open_backup)
        self.explorer_page.run_action_requested.connect(self._run_action)

        last_backup = self.settings.get("last_backup")
        if last_backup:
            last = Path(last_backup)
            self.landing_page.set_recent_backups([last])
            self.landing_page.set_path_text(last)

        self.landing_page.refresh()

    def _open_backup(self, selected_path: Path) -> None:
        backup_dir = selected_path
        if not is_backup_dir(backup_dir):
            backups = find_backups(backup_dir)
            if not backups:
                QMessageBox.warning(self, "Invalid backup", "No Smart Switch backup found in that folder.")
                return
            backup_dir = backups[0].path

        inventory = build_inventory(backup_dir)
        self.current_backup = backup_dir
        self.explorer_page.load_inventory(inventory)
        self.stack.setCurrentWidget(self.explorer_page)

        self.settings["last_backup"] = str(backup_dir)
        save_settings(self.settings)
        self.landing_page.set_recent_backups([backup_dir])
        self.landing_page.set_path_text(backup_dir)

        worker = FunctionWorker(enrich_inventory, backup_dir, inventory)
        worker.signals.result.connect(self.explorer_page.apply_patch)
        worker.signals.error.connect(self._show_error)
        self.thread_pool.start(worker)

    def _run_action(self, options: dict, selected_nodes: list[dict], destination: Path) -> None:
        if not selected_nodes:
            QMessageBox.information(self, "Nothing selected", "Select at least one item to process.")
            return
        if self.current_backup is None:
            QMessageBox.warning(self, "No backup", "Open a backup first.")
            return

        destination.mkdir(parents=True, exist_ok=True)
        self.settings["destination"] = str(destination)
        save_settings(self.settings)

        self.explorer_page.set_busy(True)
        worker = FunctionWorker(
            self._execute_actions,
            self.current_backup,
            destination,
            selected_nodes,
            options,
        )
        worker.signals.result.connect(self._handle_action_result)
        worker.signals.error.connect(self._handle_action_error)
        self.thread_pool.start(worker)

    def _execute_actions(
        self,
        backup_dir: Path,
        destination: Path,
        selected_nodes: list[dict],
        options: dict,
    ) -> dict:
        export_root = make_export_root(destination, backup_dir.name)
        warnings: list[str] = []
        errors: list[str] = []
        outputs: list[str] = []

        messages_format = str(options.get("messages_format", "json"))
        apps_mode = str(options.get("apps_mode", "extract"))
        apps_include_decrypt = apps_mode in {"decrypt", "both"}
        apps_include_extract = apps_mode in {"extract", "both"}

        message_parts = {
            node["id"].split(":", 1)[1]
            for node in selected_nodes
            if node["kind"] == "message_subitem"
        }

        if message_parts:
            result = decode_and_export_messages(
                backup_dir,
                export_root,
                message_parts,
                message_format=messages_format,
                include_decrypt=messages_format in {"json", "csv"},
                include_extract=True,
            )
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            outputs.extend(str(path) for path in result.outputs)

        app_modes: dict[str, set[str]] = {}
        for node in selected_nodes:
            kind = node["kind"]
            if kind not in {"app_data", "app_apk"}:
                continue
            package_id = node["package_id"]
            app_modes.setdefault(package_id, set()).add("data" if kind == "app_data" else "apk")

        for package_id, selected_modes in app_modes.items():
            if selected_modes == {"data", "apk"}:
                mode = "both"
            elif "data" in selected_modes:
                mode = "data"
            else:
                mode = "apk"

            result = decrypt_extract_app(
                package_id,
                mode,
                backup_dir,
                export_root / "applications",
                include_decrypt=apps_include_decrypt,
                include_extract=apps_include_extract,
            )
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            outputs.extend(str(path) for path in result.outputs)

        return {
            "ok": not errors,
            "warnings": warnings,
            "errors": errors,
            "outputs": outputs,
            "export_root": str(export_root),
        }

    def _handle_action_result(self, payload: dict) -> None:
        self.explorer_page.set_busy(False)
        ok = payload.get("ok", False)
        warnings = payload.get("warnings", [])
        errors = payload.get("errors", [])
        export_root = payload.get("export_root", "")

        if ok:
            summary = [f"Export complete: {export_root}"]
            if warnings:
                summary.append(f"Warnings: {len(warnings)}")
            QMessageBox.information(self, "Done", "\n".join(summary))
        else:
            summary = [f"Export finished with errors: {export_root}", f"Errors: {len(errors)}"]
            if warnings:
                summary.append(f"Warnings: {len(warnings)}")
            QMessageBox.warning(self, "Completed with errors", "\n".join(summary))

    def _handle_action_error(self, message: str) -> None:
        self.explorer_page.set_busy(False)
        self._show_error(message)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)
