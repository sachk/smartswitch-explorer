from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget

from smartswitch_core.additional_export import (
    export_call_log,
    export_contacts,
    export_media_directory,
    export_watch_backup,
)
from smartswitch_core.applications.decrypt_extract import copy_app_apk_payload, decrypt_extract_app
from smartswitch_core.direct_file import map_direct_file_to_item_ids, path_key
from smartswitch_core.export import make_export_root
from smartswitch_core.messages.decode import decode_and_export_messages
from smartswitch_core.metadata import enrich_inventory
from smartswitch_core.other_export import export_other_entry, export_settings_entry, export_storage_entry
from smartswitch_core.scan import build_inventory, expand_input_path, find_backups, is_backup_dir
from smartswitch_core.sizes import InventorySizeResult, compute_inventory_sizes
from gui.config import load_settings, save_settings
from gui.localization import tr
from gui.ui.explorer_page import ExplorerPage
from gui.ui.landing_page import LandingPage
from gui.ui.progress_overlay import ProgressOverlay
from gui.ui.workers import CancelToken, FunctionWorker


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return left == right


def _render_issue_lines(lines: list[str], *, limit: int = 10) -> str:
    if len(lines) <= limit:
        return "\n".join(lines)
    remaining = len(lines) - limit
    return "\n".join([*lines[:limit], f"... and {remaining} more"])


def _resolve_backup_from_file(file_path: Path) -> Path | None:
    if not file_path.exists() or not file_path.is_file():
        return None

    parents_to_try = [file_path.parent]
    if file_path.parent.parent != file_path.parent:
        parents_to_try.append(file_path.parent.parent)
    if file_path.parent.parent.parent != file_path.parent.parent:
        parents_to_try.append(file_path.parent.parent.parent)

    seen: set[str] = set()
    for parent in parents_to_try:
        key = str(parent).casefold()
        if key in seen:
            continue
        seen.add(key)

        if is_backup_dir(parent):
            return parent
        backups = find_backups(parent)
        if backups:
            return backups[0].path

    return None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr("MainWindow", "SmartSwitch Explorer"))
        self.resize(QSize(500, 720))

        self.thread_pool = QThreadPool(self)
        self.settings = load_settings()
        self.current_backup: Path | None = None
        self._active_operation: str | None = None
        self._export_cancel_token: CancelToken | None = None

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.landing_page = LandingPage()
        self.explorer_page = ExplorerPage()
        self.explorer_page.set_destination(Path(self.settings["destination"]))

        self.stack.addWidget(self.landing_page)
        self.stack.addWidget(self.explorer_page)

        self.landing_page.backup_selected.connect(self._open_backup)
        self.landing_page.listing_started.connect(self._on_listing_started)
        self.landing_page.listing_progress.connect(self._on_listing_progress)
        self.landing_page.listing_status.connect(self._on_listing_status)
        self.landing_page.listing_error.connect(self._on_listing_error)
        self.landing_page.listing_finished.connect(self._on_listing_finished)
        self.landing_page.path_committed.connect(self._remember_scan_path)
        self.landing_page.file_selected.connect(self._open_file_direct)
        self.explorer_page.back_requested.connect(self._return_to_landing)
        self.explorer_page.run_action_requested.connect(self._run_action)

        self.progress_overlay = ProgressOverlay(self)
        self.progress_overlay.cancel_requested.connect(self._cancel_active_operation)

        last_backup = self.settings.get("last_backup")
        if last_backup:
            last = expand_input_path(last_backup)
            self.landing_page.set_recent_backups([last])
            self.landing_page.set_path_text(last)

        self.landing_page.refresh()

    def _remember_scan_path(self, path: Path) -> None:
        expanded = expand_input_path(path)
        self.settings["last_backup"] = str(expanded)
        save_settings(self.settings)

    def _return_to_landing(self) -> None:
        if self._active_operation == "export":
            return
        self.stack.setCurrentWidget(self.landing_page)

    def _open_file_direct(self, selected_files: object) -> None:
        if isinstance(selected_files, Path):
            raw_files = [selected_files]
        elif isinstance(selected_files, list):
            raw_files = [Path(path) if isinstance(path, str) else path for path in selected_files if isinstance(path, (Path, str))]
        else:
            raw_files = []
        if not raw_files:
            return

        files: list[Path] = []
        seen: set[str] = set()
        for raw in raw_files:
            expanded = expand_input_path(raw)
            key = path_key(expanded)
            if key in seen:
                continue
            seen.add(key)
            files.append(expanded)

        missing_or_invalid = [path for path in files if not path.exists() or not path.is_file()]
        valid_files = [path for path in files if path.exists() and path.is_file()]
        if not valid_files:
            QMessageBox.warning(
                self,
                tr("MainWindow", "Invalid file"),
                tr("MainWindow", "No valid files were selected."),
            )
            return

        backup_groups: dict[str, tuple[Path, list[Path]]] = {}
        resolve_errors: list[str] = []
        for file_path in valid_files:
            backup_dir = _resolve_backup_from_file(file_path)
            if backup_dir is None:
                resolve_errors.append(f"{file_path.name}: could not locate a Smart Switch backup nearby")
                continue
            key = path_key(backup_dir)
            if key not in backup_groups:
                backup_groups[key] = (backup_dir, [])
            backup_groups[key][1].append(file_path)

        if not backup_groups:
            details = resolve_errors or [tr("MainWindow", "Could not locate a Smart Switch backup near the selected file.")]
            QMessageBox.warning(
                self,
                tr("MainWindow", "Invalid backup"),
                _render_issue_lines(details),
            )
            return

        if len(backup_groups) > 1:
            lines = [tr("MainWindow", "Please select files from a single backup at a time.")]
            for backup_dir, backup_files in backup_groups.values():
                lines.append(f"{backup_dir.name}: {len(backup_files)} file(s)")
            QMessageBox.warning(
                self,
                tr("MainWindow", "Multiple backups selected"),
                _render_issue_lines(lines),
            )
            return

        backup_dir, backup_files = next(iter(backup_groups.values()))
        if not self._open_backup(backup_dir):
            return

        available_ids = self.explorer_page.model.item_ids()
        selected_item_ids: set[str] = set()
        mapping_issues: list[str] = []

        for file_path in backup_files:
            item_ids, reason = map_direct_file_to_item_ids(file_path, backup_dir, available_ids)
            if item_ids:
                selected_item_ids.update(item_ids)
                continue
            mapping_issues.append(f"{file_path.name}: {reason}")

        applied_item_ids = self.explorer_page.select_leaf_ids(selected_item_ids)
        if not applied_item_ids:
            details = mapping_issues or [tr("MainWindow", "No supported export items matched the selected files.")]
            QMessageBox.warning(
                self,
                tr("MainWindow", "Unsupported file"),
                _render_issue_lines(details),
            )
            return

        skipped = [f"{path.name}: file does not exist or is not a regular file" for path in missing_or_invalid]
        skipped.extend(resolve_errors)
        skipped.extend(mapping_issues)
        if skipped:
            QMessageBox.information(
                self,
                tr("MainWindow", "Some files were skipped"),
                _render_issue_lines(skipped),
            )

        self.explorer_page.open_export_prompt()

    def _on_listing_started(self) -> None:
        if self._active_operation == "export":
            return
        self._active_operation = "listing"
        self.progress_overlay.begin(tr("MainWindow", "Scanning backups"), cancellable=False)
        self.progress_overlay.set_status(tr("MainWindow", "Looking for Smart Switch backups..."))

    def _on_listing_progress(self, payload: object) -> None:
        if self._active_operation != "listing":
            return
        if isinstance(payload, dict):
            self.progress_overlay.update_progress(payload)

    def _on_listing_status(self, message: str) -> None:
        if self._active_operation != "listing":
            return
        self.progress_overlay.set_status(message)

    def _on_listing_error(self, message: str) -> None:
        self._show_error(message)

    def _on_listing_finished(self) -> None:
        if self._active_operation == "listing":
            self.progress_overlay.finish()
            self._active_operation = None

    def _open_backup(self, selected_path: Path) -> bool:
        if self._active_operation == "listing":
            self.progress_overlay.finish()
            self._active_operation = None

        backup_dir = expand_input_path(selected_path)
        if not is_backup_dir(backup_dir):
            backups = find_backups(backup_dir)
            if not backups:
                QMessageBox.warning(
                    self,
                    tr("MainWindow", "Invalid backup"),
                    tr("MainWindow", "No Smart Switch backup found in that folder."),
                )
                return False
            backup_dir = backups[0].path

        inventory = build_inventory(backup_dir)
        self.current_backup = backup_dir
        self.explorer_page.load_inventory(inventory)
        self.explorer_page.set_size_pending()
        self.stack.setCurrentWidget(self.explorer_page)

        worker = FunctionWorker(enrich_inventory, backup_dir, inventory)
        worker.signals.result.connect(self.explorer_page.apply_patch)
        worker.signals.error.connect(self._show_error)
        self.thread_pool.start(worker)

        size_worker = FunctionWorker(self._size_summary_for_backup, backup_dir, inventory)
        size_worker.signals.result.connect(self._apply_size_summary)
        size_worker.signals.error.connect(self._show_error)
        self.thread_pool.start(size_worker, -2)
        return True

    def _size_summary_for_backup(
        self, backup_dir: Path, inventory
    ) -> tuple[Path, InventorySizeResult]:
        return backup_dir, compute_inventory_sizes(backup_dir, inventory)

    def _apply_size_summary(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        backup_dir, summary = payload
        if not isinstance(backup_dir, Path) or not isinstance(summary, InventorySizeResult):
            return
        if self.current_backup is None or not _same_path(self.current_backup, backup_dir):
            return

        self.explorer_page.apply_sizes(summary.item_sizes)
        self.explorer_page.set_total_size(summary.total_bytes)

    def _run_action(self, options: dict, selected_nodes: list[dict], destination: Path) -> None:
        if self._active_operation is not None:
            return
        if not selected_nodes:
            QMessageBox.information(
                self,
                tr("MainWindow", "Nothing selected"),
                tr("MainWindow", "Select at least one item to process."),
            )
            return
        if self.current_backup is None:
            QMessageBox.warning(
                self,
                tr("MainWindow", "No backup"),
                tr("MainWindow", "Open a backup first."),
            )
            return

        destination.mkdir(parents=True, exist_ok=True)
        self.settings["destination"] = str(destination)
        save_settings(self.settings)

        self.explorer_page.set_busy(True)
        self._active_operation = "export"
        self._export_cancel_token = CancelToken()
        self.progress_overlay.begin(tr("MainWindow", "Exporting backup"), cancellable=True)
        self.progress_overlay.set_status(tr("MainWindow", "Preparing export..."))

        worker = FunctionWorker(
            self._execute_actions,
            self.current_backup,
            destination,
            selected_nodes,
            options,
            enable_progress=True,
            cancel_token=self._export_cancel_token,
        )
        worker.signals.progress.connect(self._on_export_progress)
        worker.signals.status.connect(self._on_export_status)
        worker.signals.result.connect(self._handle_action_result)
        worker.signals.error.connect(self._handle_action_error)
        self.thread_pool.start(worker)

    def _execute_actions(
        self,
        backup_dir: Path,
        destination: Path,
        selected_nodes: list[dict],
        options: dict,
        *,
        progress: Callable[[object], None] | None = None,
        set_status: Callable[[str], None] | None = None,
        cancel_token: CancelToken | None = None,
    ) -> dict:
        export_root = make_export_root(destination, backup_dir.name)
        warnings: list[str] = []
        errors: list[str] = []
        outputs: list[str] = []

        messages_format = str(options.get("messages_format", "json"))
        app_data_mode = str(options.get("app_data_mode", "extract"))
        app_data_include_decrypt = app_data_mode in {"decrypt", "both"}
        app_data_include_extract = app_data_mode in {"extract", "both"}

        message_parts = {
            node["id"].split(":", 1)[1]
            for node in selected_nodes
            if node["kind"] == "message_subitem"
        }

        app_modes: dict[str, set[str]] = {}
        for node in selected_nodes:
            kind = node["kind"]
            if kind not in {"app_data", "app_apk"}:
                continue
            package_id = node["package_id"]
            app_modes.setdefault(package_id, set()).add("data" if kind == "app_data" else "apk")

        media_kinds = {
            node["kind"] for node in selected_nodes if node["kind"] in {"media_photos", "media_videos"}
        }
        watch_kinds = {
            node["kind"] for node in selected_nodes if node["kind"] in {"watch_current", "watch_backup"}
        }
        contacts_selected = any(node["kind"] == "contacts" for node in selected_nodes)
        calllog_selected = any(node["kind"] == "calllog" for node in selected_nodes)
        other_entries = sorted(
            {
                node["package_id"]
                for node in selected_nodes
                if node["kind"] == "other_entry" and node["package_id"]
            }
        )
        storage_entries = sorted(
            {
                node["package_id"]
                for node in selected_nodes
                if node["kind"] == "storage_entry" and node["package_id"]
            }
        )
        settings_entries = sorted(
            {
                node["package_id"]
                for node in selected_nodes
                if node["kind"] == "settings_entry" and node["package_id"]
            }
        )

        total_steps = 1  # prepare
        total_steps += len(message_parts)
        total_steps += sum(1 for selected in app_modes.values() if "data" in selected)
        total_steps += sum(1 for selected in app_modes.values() if "apk" in selected)
        total_steps += 1 if "media_photos" in media_kinds else 0
        total_steps += 1 if "media_videos" in media_kinds else 0
        total_steps += 1 if "watch_current" in watch_kinds else 0
        total_steps += 1 if "watch_backup" in watch_kinds else 0
        total_steps += 1 if contacts_selected else 0
        total_steps += 1 if calllog_selected else 0
        total_steps += len(other_entries)
        total_steps += len(storage_entries)
        total_steps += len(settings_entries)
        total_steps += 1  # finalize
        total_steps = max(1, total_steps)
        completed_steps = 0

        def payload(*, cancelled: bool = False) -> dict:
            return {
                "ok": not errors and not cancelled,
                "cancelled": cancelled,
                "warnings": warnings,
                "errors": errors,
                "outputs": outputs,
                "export_root": str(export_root),
            }

        def emit_progress(phase_key: str, phase_label: str, detail: str) -> None:
            if progress is None:
                return
            progress(
                {
                    "operation": "export",
                    "phase_key": phase_key,
                    "phase_label": phase_label,
                    "current": completed_steps,
                    "total": total_steps,
                    "unit": "steps",
                    "detail": detail,
                }
            )

        def advance(steps: int, phase_key: str, phase_label: str, detail: str) -> None:
            nonlocal completed_steps
            completed_steps = min(total_steps, completed_steps + max(0, steps))
            emit_progress(phase_key, phase_label, detail)

        def is_cancelled() -> bool:
            return bool(cancel_token and cancel_token.is_cancelled())

        def maybe_cancel() -> dict | None:
            if not is_cancelled():
                return None
            if set_status is not None:
                set_status("Cancelling export...")
            emit_progress("cancelled", "Cancelling export", "Stopping after current step")
            return payload(cancelled=True)

        if set_status is not None:
            set_status("Preparing export")
        emit_progress("prepare", "Preparing export", backup_dir.name)
        advance(1, "prepare", "Preparing export", backup_dir.name)
        cancelled = maybe_cancel()
        if cancelled is not None:
            return cancelled

        if message_parts:
            if set_status is not None:
                set_status("Exporting messages")
            emit_progress("messages", "Messages", f"{len(message_parts)} selected")
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
            advance(len(message_parts), "messages", "Messages", f"{len(message_parts)} exported")
            cancelled = maybe_cancel()
            if cancelled is not None:
                return cancelled

        for package_id, selected_modes in app_modes.items():
            if "data" in selected_modes:
                if set_status is not None:
                    set_status(f"Exporting app data: {package_id}")
                emit_progress("applications", "Application data", package_id)
                result = decrypt_extract_app(
                    package_id,
                    "data",
                    backup_dir,
                    export_root / "applications",
                    include_decrypt=app_data_include_decrypt,
                    include_extract=app_data_include_extract,
                    manifest_name="manifest_data.json",
                )
                warnings.extend(result.warnings)
                errors.extend(result.errors)
                outputs.extend(str(path) for path in result.outputs)
                advance(1, "applications", "Application data", package_id)
                cancelled = maybe_cancel()
                if cancelled is not None:
                    return cancelled

            if "apk" in selected_modes:
                if set_status is not None:
                    set_status(f"Exporting app APK: {package_id}")
                emit_progress("applications", "Application APKs", package_id)
                result = copy_app_apk_payload(
                    package_id,
                    backup_dir,
                    export_root / "applications",
                )
                warnings.extend(result.warnings)
                errors.extend(result.errors)
                outputs.extend(str(path) for path in result.outputs)
                advance(1, "applications", "Application APKs", package_id)
                cancelled = maybe_cancel()
                if cancelled is not None:
                    return cancelled

        if "media_photos" in media_kinds:
            if set_status is not None:
                set_status("Exporting photos")
            emit_progress("media", "Photos", "Copying media directories")
            result = export_media_directory("photos", backup_dir, export_root)
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            outputs.extend(str(path) for path in result.outputs)
            advance(1, "media", "Photos", "Finished photos")
            cancelled = maybe_cancel()
            if cancelled is not None:
                return cancelled
        if "media_videos" in media_kinds:
            if set_status is not None:
                set_status("Exporting videos")
            emit_progress("media", "Videos", "Copying media directories")
            result = export_media_directory("videos", backup_dir, export_root)
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            outputs.extend(str(path) for path in result.outputs)
            advance(1, "media", "Videos", "Finished videos")
            cancelled = maybe_cancel()
            if cancelled is not None:
                return cancelled

        if "watch_current" in watch_kinds:
            if set_status is not None:
                set_status("Exporting current watch backup")
            emit_progress("watch", "Current watch backup", "Exporting encrypted payloads")
            result = export_watch_backup("current", backup_dir, export_root)
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            outputs.extend(str(path) for path in result.outputs)
            advance(1, "watch", "Current watch backup", "Finished current watch backup")
            cancelled = maybe_cancel()
            if cancelled is not None:
                return cancelled
        if "watch_backup" in watch_kinds:
            if set_status is not None:
                set_status("Exporting older watch backup")
            emit_progress("watch", "Older watch backup", "Exporting encrypted payloads")
            result = export_watch_backup("backup", backup_dir, export_root)
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            outputs.extend(str(path) for path in result.outputs)
            advance(1, "watch", "Older watch backup", "Finished older watch backup")
            cancelled = maybe_cancel()
            if cancelled is not None:
                return cancelled

        if contacts_selected:
            contacts_format = str(options.get("contacts_format", "csv"))
            if set_status is not None:
                set_status("Exporting contacts")
            emit_progress("contacts", "Contacts", f"Format: {contacts_format}")
            result = export_contacts(backup_dir, export_root, output_format=contacts_format)
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            outputs.extend(str(path) for path in result.outputs)
            advance(1, "contacts", "Contacts", "Finished contacts")
            cancelled = maybe_cancel()
            if cancelled is not None:
                return cancelled

        if calllog_selected:
            calllog_format = str(options.get("calllog_format", "csv"))
            if set_status is not None:
                set_status("Exporting call log")
            emit_progress("calllog", "Call log", f"Format: {calllog_format}")
            result = export_call_log(backup_dir, export_root, output_format=calllog_format)
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            outputs.extend(str(path) for path in result.outputs)
            advance(1, "calllog", "Call log", "Finished call log")
            cancelled = maybe_cancel()
            if cancelled is not None:
                return cancelled

        for entry_name in other_entries:
            if set_status is not None:
                set_status(f"Exporting other entry: {entry_name}")
            emit_progress("other_entries", "Other backup data", entry_name)
            result = export_other_entry(backup_dir, entry_name, export_root)
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            outputs.extend(str(path) for path in result.outputs)
            advance(1, "other_entries", "Other backup data", entry_name)
            cancelled = maybe_cancel()
            if cancelled is not None:
                return cancelled

        for entry_name in storage_entries:
            if set_status is not None:
                set_status(f"Exporting storage entry: {entry_name}")
            emit_progress("storage_entries", "Storage", entry_name)
            result = export_storage_entry(backup_dir, entry_name, export_root)
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            outputs.extend(str(path) for path in result.outputs)
            advance(1, "storage_entries", "Storage", entry_name)
            cancelled = maybe_cancel()
            if cancelled is not None:
                return cancelled

        for entry_name in settings_entries:
            if set_status is not None:
                set_status(f"Exporting settings entry: {entry_name}")
            emit_progress("settings_entries", "Settings", entry_name)
            result = export_settings_entry(backup_dir, entry_name, export_root)
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            outputs.extend(str(path) for path in result.outputs)
            advance(1, "settings_entries", "Settings", entry_name)
            cancelled = maybe_cancel()
            if cancelled is not None:
                return cancelled

        if set_status is not None:
            set_status("Finalizing export")
        advance(1, "finalize", "Finalizing export", "Wrapping up")
        return payload(cancelled=False)

    def _on_export_progress(self, payload: object) -> None:
        if self._active_operation != "export":
            return
        if isinstance(payload, dict):
            self.progress_overlay.update_progress(payload)

    def _on_export_status(self, message: str) -> None:
        if self._active_operation != "export":
            return
        self.progress_overlay.set_status(message)

    def _cancel_active_operation(self) -> None:
        if self._active_operation != "export":
            return
        if self._export_cancel_token is None:
            return
        self._export_cancel_token.cancel()
        self.progress_overlay.set_cancel_enabled(False)
        self.progress_overlay.set_status(tr("MainWindow", "Cancelling export..."))

    def _handle_action_result(self, payload: dict) -> None:
        self.explorer_page.set_busy(False)
        self.progress_overlay.finish()
        self._active_operation = None
        self._export_cancel_token = None

        cancelled = payload.get("cancelled", False)
        ok = payload.get("ok", False)
        warnings = payload.get("warnings", [])
        errors = payload.get("errors", [])
        export_root = payload.get("export_root", "")

        if cancelled:
            summary = [f"{tr('MainWindow', 'Export cancelled')}: {export_root}"]
            if errors:
                summary.append(f"{tr('MainWindow', 'Errors')}: {len(errors)}")
            if warnings:
                summary.append(f"{tr('MainWindow', 'Warnings')}: {len(warnings)}")
            self._show_export_result(tr("MainWindow", "Cancelled"), "\n".join(summary), export_root, warning=False)
            return

        if ok:
            summary = [f"{tr('MainWindow', 'Export complete')}: {export_root}"]
            if warnings:
                summary.append(f"{tr('MainWindow', 'Warnings')}: {len(warnings)}")
            self._show_export_result(tr("MainWindow", "Done"), "\n".join(summary), export_root, warning=False)
        else:
            summary = [
                f"{tr('MainWindow', 'Export finished with errors')}: {export_root}",
                f"{tr('MainWindow', 'Errors')}: {len(errors)}",
            ]
            if warnings:
                summary.append(f"{tr('MainWindow', 'Warnings')}: {len(warnings)}")
            self._show_export_result(
                tr("MainWindow", "Completed with errors"),
                "\n".join(summary),
                export_root,
                warning=True,
            )

    def _handle_action_error(self, message: str) -> None:
        self.explorer_page.set_busy(False)
        self.progress_overlay.finish()
        self._active_operation = None
        self._export_cancel_token = None
        self._show_error(message)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, tr("MainWindow", "Error"), message)

    def _show_export_result(self, title: str, text: str, export_root: str, *, warning: bool) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Information)
        open_button = box.addButton(tr("MainWindow", "Open Folder"), QMessageBox.ButtonRole.ActionRole)
        close_button = box.addButton(QMessageBox.StandardButton.Close)
        box.setDefaultButton(close_button)
        box.exec()
        if box.clickedButton() is open_button and export_root:
            QDesktopServices.openUrl(QUrl.fromLocalFile(export_root))
