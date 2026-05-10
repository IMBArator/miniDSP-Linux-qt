"""Main window: owns the DeviceThread, DeviceState, and view stack."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QActionGroup, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
)

from ..device_thread import DeviceThread
from ..model import DeviceState, PEQBand
from ..theme import theme_manager
from ..unt_loader import UntParseError, load_unt, load_unt_all_slots
from ..unt_writer import save_unt
from ..virtual_dsp import VirtualDSP
from .channel_linking_dialog import ChannelLinkingDialog
from .detail_view import DetailView
from .home_view import HomeView
from .preset_picker import PresetPickerDialog

log = logging.getLogger(__name__)


def _logo_path() -> Path:
    try:
        import importlib.resources as ir

        ref = ir.files("minidspqt.resources").joinpath("logo.svg")
        return Path(str(ref))
    except Exception:
        return Path()


class MainWindow(QMainWindow):
    def __init__(self, *, dsp_instance=None, offline: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("DSP 4x4 Mini")
        self.setMinimumWidth(960)
        logo = _logo_path()
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))
        self._offline = offline

        self._state = DeviceState()

        self._stack = QStackedWidget()
        self._home_view = HomeView()
        self._detail_view = DetailView()
        self._stack.addWidget(self._home_view)
        self._stack.addWidget(self._detail_view)
        self.setCentralWidget(self._stack)

        if dsp_instance is not None:
            factory = type(dsp_instance)
        else:
            from minidsp.device import DSPmini

            factory = DSPmini

        self._thread = DeviceThread(
            dsp_factory=factory,
            dsp_instance=dsp_instance,
            parent=self,
        )
        self._thread.levels_updated.connect(self._on_levels_updated)
        self._thread.connection_changed.connect(self._on_connection_changed)
        self._thread.config_loaded.connect(self._on_config_loaded)

        self._home_view.gain_changed.connect(self._on_gain_changed)
        self._home_view.mute_changed.connect(self._on_mute_changed)
        self._home_view.phase_changed.connect(self._on_phase_changed)
        self._home_view.gate_clicked.connect(self._show_detail)
        self._home_view.output_feature_toggled.connect(
            self._on_output_feature_toggled
        )
        self._home_view.name_changed.connect(self._on_name_changed)
        self._home_view.route_changed.connect(self._on_route_changed)
        self._home_view.recall_clicked.connect(self._on_recall)
        self._home_view.store_clicked.connect(self._on_store)

        self._detail_view.back_clicked.connect(self._on_detail_back)
        self._detail_view.gain_changed.connect(self._on_gain_changed)
        self._detail_view.mute_changed.connect(self._on_mute_changed)
        self._detail_view.phase_changed.connect(self._on_phase_changed)
        self._detail_view.gate_clicked.connect(self._on_detail_gate_clicked)
        self._detail_view.gate_params_changed.connect(self._on_detail_gate_params)
        self._detail_view.name_changed.connect(self._on_name_changed)
        self._detail_view.output_feature_toggled.connect(
            self._on_output_feature_toggled
        )
        self._detail_view.peq_band_changed.connect(self._on_detail_peq_band)
        self._detail_view.peq_channel_bypass_changed.connect(
            self._on_detail_peq_channel_bypass
        )
        self._detail_view.xover_changed.connect(self._on_detail_xover_changed)

        self._thread.start()

        menu = QMenu(self)
        menu.addAction("Load .unt file\u2026").triggered.connect(self._on_load_unt)
        self._save_action = menu.addAction("Save .unt file\u2026")
        self._save_action.triggered.connect(self._on_save_unt)
        self._save_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Channel linking\u2026").triggered.connect(self._on_channel_linking)
        self._linking_dialog: ChannelLinkingDialog | None = None
        menu.addSeparator()
        self._build_theme_menu(menu)
        menu.addSeparator()
        menu.addAction("About").triggered.connect(self._on_about)
        btn = self._home_view.menu_button
        btn.setMenu(menu)

        self._detail_view.menu_button.setMenu(menu)

        if offline:
            self._home_view.set_offline_mode()
            self._detail_view.set_offline_mode()
            self._save_action.setEnabled(True)

    @property
    def _virtual_dsp(self) -> VirtualDSP | None:
        inst = self._thread._dsp_instance
        return inst if isinstance(inst, VirtualDSP) else None

    # --- DeviceThread -> UI ---

    def _on_levels_updated(self, payload: dict) -> None:
        self._home_view.update_levels(payload)
        if self._stack.currentIndex() == 1:
            self._detail_view.update_levels(payload)

    def _on_connection_changed(self, connected: bool) -> None:
        self._state.connected = connected
        if self._offline:
            return
        self._home_view.set_connected(connected)
        self._detail_view.set_connected(connected)

    def _on_config_loaded(self, cfg: dict) -> None:
        log.info(
            "config_loaded: keys=%s active_slot=%s preset_names=%d entries",
            sorted(cfg.keys()),
            cfg.get("active_slot"),
            len(cfg.get("preset_names", [])),
        )
        old_names = list(self._state.preset_names)
        try:
            self._state = DeviceState.from_config(cfg)
        except Exception:
            log.exception("Failed to parse config dict")
            return
        if not self._state.preset_names and old_names:
            self._state.preset_names = old_names
        log.info(
            "config_loaded: state updated, slot=%s gains=%s",
            self._state.active_slot,
            [ch.gain_raw for ch in self._state.inputs + self._state.outputs],
        )
        self._home_view.apply_state(self._state)
        self._sync_linking_dialog()

    def _sync_linking_dialog(self) -> None:
        """Refresh the channel-linking dialog if it's currently open.

        Called wherever ``self._state`` is replaced (config reload, .unt
        load) so the dialog reflects the authoritative state — crucial
        after _apply_channel_links so any silent device rejection snaps
        the radios back instead of showing stale optimistic state.
        """
        if self._linking_dialog is not None and self._linking_dialog.isVisible():
            self._linking_dialog.refresh(self._state)

    def _on_load_unt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load .unt preset",
            "",
            "miniDSP preset (*.unt);;All files (*)",
        )
        if not path:
            return

        vdsp = self._virtual_dsp
        if vdsp is not None:
            try:
                slots, active_slot, names, raw = load_unt_all_slots(path)
            except (UntParseError, OSError) as e:
                QMessageBox.critical(self, "Cannot load .unt file", str(e))
                return
            vdsp.load_from_unt_bytes(raw, slots, active_slot, names)
            cfg = vdsp.read_config()
            try:
                self._state = DeviceState.from_config(cfg)
            except Exception:
                log.exception("Failed to parse config from loaded .unt")
                return
            self._home_view.apply_state(self._state)
            self._sync_linking_dialog()
            self._save_action.setEnabled(True)
            return

        try:
            cfg, active_slot, names = load_unt(path)
        except (UntParseError, OSError) as e:
            QMessageBox.critical(self, "Cannot load .unt file", str(e))
            return
        cfg["active_slot"] = active_slot
        cfg["preset_names"] = names
        self._state = DeviceState.from_config(cfg)
        self._state.connected = False
        self._home_view.set_connected(False)
        self._home_view.apply_state(self._state)
        self._sync_linking_dialog()
        self._home_view.show_preview_banner(Path(path).name)

    def _on_save_unt(self) -> None:
        vdsp = self._virtual_dsp
        if vdsp is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save .unt preset",
            "",
            "miniDSP preset (*.unt);;All files (*)",
        )
        if not path:
            return
        slots_0based, active_0based, template = vdsp.export_to_unt_args()
        slot_names = self._state.preset_names
        try:
            save_unt(path, slots_0based, slot_names, active_0based, template)
        except Exception as e:
            QMessageBox.critical(self, "Cannot save .unt file", str(e))

    # --- Recall / Store ---

    def _preset_display_names(self) -> list[str]:
        return self._state.preset_names

    def _on_recall(self) -> None:
        display_names = self._preset_display_names()
        active = self._state.active_slot if self._state.active_slot is not None else 1
        active_in_list = active  # F00=row 0, U01=row 1, … (matches chosen_slot)
        dlg = PresetPickerDialog(
            self,
            display_names,
            active_in_list,
            "recall",
        )
        if dlg.exec() == QDialog.Accepted:
            slot = dlg.chosen_slot
            self._thread.request_load_preset(slot)

    def _on_store(self) -> None:
        display_names = self._preset_display_names()
        active = self._state.active_slot if self._state.active_slot is not None else 1
        active_in_list = active
        current_name = ""
        names_30 = display_names
        if 1 <= active <= 30:
            idx = active - 1
            if idx < len(names_30):
                current_name = names_30[idx]

        dlg = PresetPickerDialog(
            self,
            display_names,
            active_in_list,
            "store",
            current_name,
        )
        if dlg.exec() == QDialog.Accepted:
            slot = dlg.chosen_slot
            reply = QMessageBox.question(
                self,
                "Store Preset",
                f'Store the current configuration to slot U{slot:02d} "{dlg.chosen_name}"?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._thread.request_store_preset(slot, dlg.chosen_name)
            names = self._state.preset_names
            idx = slot - 1
            if 0 <= idx < len(names):
                names[idx] = dlg.chosen_name
            self._home_view.apply_state(self._state)

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About DSP 4x4 Mini",
            "<h3>DSP 4x4 Mini</h3>"
            "<p>Qt graphical interface for the t.racks DSP 4x4 Mini.</p>"
            '<p><a href="https://github.com/IMBArator/miniDSP-Linux-qt">'
            "github.com/IMBArator/miniDSP-Linux-qt</a></p>"
            "<p>Licensed under the "
            '<a href="https://www.gnu.org/licenses/gpl-3.0.en.html">'
            "GNU General Public License v3.0</a>.</p>"
            "<hr>"
            "<p>This application uses <b>PySide6</b> (Qt for Python), "
            "licensed under the "
            '<a href="https://www.gnu.org/licenses/lgpl-3.0.en.html">'
            "GNU Lesser General Public License v3</a>. "
            "PySide6 is dynamically linked; users may replace the library "
            "with a modified version.</p>",
        )

    # --- UI -> DeviceThread ---

    def _on_gain_changed(self, channel: int, raw: int) -> None:
        for ch in self._state.set_field_with_links(channel, "gain_raw", raw):
            self._thread.request_gain(ch, raw)
            if ch != channel:
                self._apply_strip_gain(ch, raw)

    def _on_mute_changed(self, channel: int, muted: bool) -> None:
        for ch in self._state.set_field_with_links(channel, "muted", muted):
            self._thread.request_mute(ch, muted)
            if ch != channel:
                self._apply_strip_toggle(ch, "mute", muted)

    def _on_phase_changed(self, channel: int, inverted: bool) -> None:
        for ch in self._state.set_field_with_links(channel, "phase_inverted", inverted):
            self._thread.request_phase(ch, inverted)
            if ch != channel:
                self._apply_strip_toggle(ch, "phase", inverted)

    def _show_detail(self, channel: int) -> None:
        self._detail_view.set_channel(channel, self._state)
        self._stack.setCurrentIndex(1)

    def _on_detail_back(self) -> None:
        self._stack.setCurrentIndex(0)

    def _on_detail_gate_clicked(self, channel: int) -> None:
        pass

    def _on_detail_gate_params(
        self, channel: int, attack: int, release: int, hold: int, threshold: int
    ) -> None:
        if 0 <= channel < 4 and channel < len(self._state.inputs):
            gate = self._state.inputs[channel].gate
            gate.attack = attack
            gate.release = release
            gate.hold = hold
            gate.threshold = threshold
        self._thread.request_gate(channel, attack, release, hold, threshold)
        self._home_view._input_strips[channel].set_gate_active(threshold > 0)

    def _on_output_feature_toggled(
        self, channel: int, feature: str, checked: bool
    ) -> None:
        # Output feature buttons (xover/peq/comp/delay) are navigation buttons.
        # The strip auto-unchecks PEQ; only act on the press (checked=True).
        if not checked:
            return
        if feature == "peq":
            self._show_detail(channel)
            self._detail_view.show_feature(channel, "PEQ")
        elif feature == "xover":
            self._show_detail(channel)
            self._detail_view.show_feature(channel, "Xover")
        else:
            log.info(
                "Output feature ch=%d feature=%s checked=%s (no panel yet)",
                channel,
                feature,
                checked,
            )

    def _on_detail_peq_band(
        self,
        channel: int,
        band: int,
        gain_raw: int,
        freq_raw: int,
        q_raw: int,
        filter_type: int,
        bypass: bool,
    ) -> None:
        out_idx = channel - 4
        if 0 <= out_idx < len(self._state.outputs):
            peqs = self._state.outputs[out_idx].peqs
            while len(peqs) <= band:
                peqs.append(PEQBand())
            peqs[band] = PEQBand(
                gain_raw=gain_raw,
                freq_raw=freq_raw,
                q_raw=q_raw,
                filter_type=filter_type,
                bypass=bypass,
            )
            self._home_view._output_strips[out_idx].set_peq_active(
                self._state.outputs[out_idx].peq_active
            )
        self._thread.request_peq_band(
            channel, band, gain_raw, freq_raw, q_raw, filter_type, bypass
        )

    def _on_detail_peq_channel_bypass(self, channel: int, bypass: bool) -> None:
        out_idx = channel - 4
        if 0 <= out_idx < len(self._state.outputs):
            self._state.outputs[out_idx].peq_channel_bypass = bypass
            self._home_view._output_strips[out_idx].set_peq_active(
                self._state.outputs[out_idx].peq_active
            )
        self._thread.request_peq_channel_bypass(channel, bypass)

    def _on_detail_xover_changed(
        self, channel: int, hp_freq: int, hp_slope: int, lp_freq: int, lp_slope: int
    ) -> None:
        out_idx = channel - 4
        if 0 <= out_idx < len(self._state.outputs):
            xo = self._state.outputs[out_idx].crossover
            xo.hipass_freq = hp_freq
            xo.hipass_slope = hp_slope
            xo.lopass_freq = lp_freq
            xo.lopass_slope = lp_slope
            self._home_view._output_strips[out_idx].set_xover_active(
                self._state.outputs[out_idx].xover_active
            )
        if hp_slope != 0:
            self._thread.request_hipass(channel, hp_freq, hp_slope)
        if lp_slope != 0:
            self._thread.request_lopass(channel, lp_freq, lp_slope)

    def _on_name_changed(self, channel: int, name: str) -> None:
        self._state.set_field(channel, "name", name)
        self._thread.request_channel_name(channel, name)
        strips = self._home_view._all_strips()
        if 0 <= channel < len(strips):
            strips[channel].set_title(name)

    def _on_route_changed(self, output_idx: int, input_mask: int) -> None:
        if output_idx < 0 or output_idx >= len(self._state.outputs):
            return
        self._state.outputs[output_idx].routing_mask = input_mask
        self._thread.request_matrix_route(0x04 + output_idx, input_mask)

    def _apply_strip_gain(self, channel: int, raw: int) -> None:
        strips = self._home_view._all_strips()
        if 0 <= channel < len(strips):
            strips[channel].set_gain_silent(raw)

    def _apply_strip_toggle(self, channel: int, feature: str, checked: bool) -> None:
        strips = self._home_view._all_strips()
        if 0 <= channel < len(strips):
            strips[channel].set_toggle_silent(feature, checked)

    # --- Channel linking ---

    def _on_channel_linking(self) -> None:
        """Open the channel-linking dialog (creating it on first use)."""
        if self._linking_dialog is None:
            self._linking_dialog = ChannelLinkingDialog(self, self._state)
            self._linking_dialog.applyRequested.connect(self._apply_channel_links)
        else:
            self._linking_dialog.refresh(self._state)
        self._linking_dialog.show()
        self._linking_dialog.raise_()
        self._linking_dialog.activateWindow()

    def _apply_channel_links(self, new_flags: list[int]) -> None:
        """Push link changes to the device and trigger a config reload.

        Sequencing matches the protocol contract:
          1. For every *new* slave (non-zero → zero transition), declare the
             pair via prepare_link before any set_channel_link is sent.
          2. Send set_channel_link for every channel whose flags changed
             (master + slaves both need updating).
          3. Request a fresh read_config so the UI reflects what the device
             actually committed (handles silent rejections).
        """
        old_flags = self._state._link_flags_list()
        if new_flags == old_flags:
            return  # nothing changed — don't churn the device

        # Step 1: prepare_link for any new slave pair, per group.
        for group_start in (0, 4):
            new_master = self._find_new_master(
                old_flags, new_flags, group_start
            )
            if new_master is None:
                continue
            new_master_unified = group_start + new_master
            for i in range(4):
                ch = group_start + i
                # A "new slave" is a channel whose new flags are 0x00 and
                # whose old flags weren't (or whose master changed).
                was_slave = old_flags[ch] == 0x00
                is_slave = new_flags[ch] == 0x00
                if is_slave and not was_slave:
                    self._thread.request_prepare_link(new_master_unified, ch)

        # Step 2: send set_channel_link for every channel whose flags changed.
        for ch in range(8):
            if new_flags[ch] != old_flags[ch]:
                self._thread.request_channel_link(ch, new_flags[ch])

        # Step 3: refresh from the device so the UI snaps to the truth.
        self._thread.request_read_config()

    @staticmethod
    def _find_new_master(
        old_flags: list[int], new_flags: list[int], group_start: int
    ) -> int | None:
        """Return the within-group master index for the new state, or None.

        Used to look up which channel needs the prepare_link partner. The
        master is the unique channel in the group whose new flags have
        more than one bit set.
        """
        for i in range(4):
            ch = group_start + i
            f = new_flags[ch]
            if f and (f & (f - 1)) != 0:
                # f has more than one bit set → this is a master.
                return i
        return None

    # --- Theme menu ---

    def _build_theme_menu(self, parent_menu: QMenu) -> None:
        """Add a "Theme" submenu with System / Light / Dark choices.

        The choice is persisted via QSettings inside the theme manager, so
        the next launch reflects whatever the user picked here.
        """
        theme_menu = parent_menu.addMenu("Theme")
        group = QActionGroup(self)
        group.setExclusive(True)

        def _add(label: str, pref: str) -> None:
            act = theme_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(theme_manager.preference == pref)
            act.triggered.connect(lambda _checked, p=pref: theme_manager.set_user_preference(p))
            group.addAction(act)

        _add("System", "system")
        _add("Light", "light")
        _add("Dark", "dark")

    # --- Lifecycle ---

    def closeEvent(self, event) -> None:
        self._thread.request_stop()
        self._thread.wait(2000)
        event.accept()
