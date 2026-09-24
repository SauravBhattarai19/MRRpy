# -*- coding: utf-8 -*-
"""
dependency_dialog.py
====================
A small dialog that shows which Python packages the model needs, whether each
is present in QGIS's interpreter, and offers a one-click install (into that
same interpreter) with a live log and a copyable manual-command fallback.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QPushButton,
    QPlainTextEdit, QSizePolicy, QApplication,
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal

from ..bridge import dependencies as deps


class _InstallWorker(QThread):
    """Runs deps.install() off the GUI thread, streaming output to log()."""

    log = pyqtSignal(str)
    done = pyqtSignal(bool, int)

    def __init__(self, pip_names, parent=None):
        super().__init__(parent)
        self._pip_names = pip_names

    def run(self):
        ok, rc = deps.install(self._pip_names, log=self.log.emit)
        self.done.emit(ok, rc)


class DependencyDialog(QDialog):
    """Dependency status + installer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self.setWindowTitle("MRRpy_plugin — Python Dependencies")
        self.setMinimumSize(680, 560)
        self._build_ui()
        self.refresh()

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)

        intro = QLabel(
            "These packages must be importable from <b>QGIS's own Python</b> "
            "(not your system Python).  Install targets:<br><code>{}</code>"
            .format(deps.python_executable())
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        grp = QGroupBox("Status")
        self._status_box = QVBoxLayout(grp)
        root.addWidget(grp)

        self.manual_label = QLabel()
        self.manual_label.setWordWrap(True)
        self.manual_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.manual_label.setStyleSheet("QLabel { color:#555; }")
        root.addWidget(self.manual_label)

        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setPlaceholderText("Install output will appear here …")
        mono = self.log_panel.font(); mono.setFamily("Monospace"); mono.setPointSize(9)
        self.log_panel.setFont(mono)
        self.log_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.log_panel, stretch=1)

        btn_row = QHBoxLayout()
        self.install_btn = QPushButton("⬇  Install missing")
        self.install_btn.setStyleSheet(
            "QPushButton { background:#2E86AB; color:white; font-weight:bold;"
            " padding:6px 14px; border-radius:4px; }"
            "QPushButton:disabled { background:#aaa; }"
        )
        self.install_btn.clicked.connect(lambda: self._start_install(include_optional=False))

        self.install_all_btn = QPushButton("⬇  Install missing + optional")
        self.install_all_btn.clicked.connect(lambda: self._start_install(include_optional=True))

        self.copy_btn = QPushButton("📋  Copy manual command")
        self.copy_btn.clicked.connect(self._copy_manual)

        self.refresh_btn = QPushButton("↻  Re-check")
        self.refresh_btn.clicked.connect(self.refresh)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)

        btn_row.addWidget(self.install_btn)
        btn_row.addWidget(self.install_all_btn)
        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.refresh_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.close_btn)
        root.addLayout(btn_row)

    # ── Status ──────────────────────────────────────────────────────────────

    def _clear_status(self):
        while self._status_box.count():
            item = self._status_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def refresh(self):
        """Re-probe every package and repaint the status list."""
        self._clear_status()
        all_missing = deps.missing(include_optional=True)
        missing_names = {m[0] for m in all_missing}

        for mod, pip, why in deps.REQUIRED + deps.OPTIONAL:
            ok = mod not in missing_names
            optional = (mod, pip, why) in deps.OPTIONAL
            tag = "optional" if optional else "required"
            mark = "✓" if ok else "✗"
            colour = "#1a7f37" if ok else ("#9a6700" if optional else "#cf222e")
            lbl = QLabel(f"<span style='color:{colour};font-weight:bold'>{mark}</span> "
                         f"<b>{pip}</b> — {why} <i>({tag})</i>")
            self._status_box.addWidget(lbl)

        req_missing = deps.missing(include_optional=False)
        self.manual_label.setText(
            "Manual fallback (paste into the OSGeo4W Shell on Windows, or a "
            "terminal on Linux/macOS):<br><code>{}</code>".format(
                deps.manual_command([m[1] for m in (req_missing or deps.REQUIRED)])
            )
        )
        self.install_btn.setEnabled(bool(req_missing))
        self.install_all_btn.setEnabled(bool(all_missing))

    # ── Install ─────────────────────────────────────────────────────────────

    def _start_install(self, include_optional):
        pip_names = [m[1] for m in deps.missing(include_optional=include_optional)]
        if not pip_names:
            return
        self._set_running(True)
        self.log_panel.clear()
        self._append(f"Installing: {', '.join(pip_names)}\n")
        self._worker = _InstallWorker(pip_names, parent=self)
        self._worker.log.connect(self._append)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, ok, rc):
        self._set_running(False)
        if ok:
            # Make the just-installed packages usable in THIS QGIS session
            # (no restart) by adding their site dirs to sys.path.
            added = deps.refresh_import_paths()
            if added:
                self._append("\n[INFO] Refreshed import paths:")
                for d in added:
                    self._append(f"    + {d}")
            self.refresh()
            still = deps.missing(include_optional=False)
            if still:
                self._append(
                    "\n[OK] Install finished, but some packages still aren't "
                    "importable in this running session.\n"
                    "Please RESTART QGIS, then re-open this dialog and click "
                    "Re-check — they should turn green."
                )
            else:
                self._append(
                    "\n[OK] Done — all required packages are now available. "
                    "You can close this dialog and press Run (no restart needed)."
                )
        else:
            self._append(
                f"\n[ERROR] pip exited with code {rc}.\n"
                "If this is a permission error, run the manual command shown "
                "above in the OSGeo4W Shell (Start → OSGeo4W → OSGeo4W Shell), "
                "then restart QGIS."
            )
            self.refresh()

    def _set_running(self, running):
        for b in (self.install_btn, self.install_all_btn, self.refresh_btn, self.close_btn):
            b.setEnabled(not running)

    def _append(self, text):
        self.log_panel.appendPlainText(text)
        sb = self.log_panel.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _copy_manual(self):
        req_missing = deps.missing(include_optional=False) or deps.REQUIRED
        QApplication.clipboard().setText(deps.manual_command([m[1] for m in req_missing]))
