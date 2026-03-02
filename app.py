#!/usr/bin/env python3
"""
app.py - basic desktop MP3 player (PyQt6)
Drop-in for /home/timothy/Documents/project_mp3/app.py

Features:
- Scan a music folder (default: /home/timothy/Music) in background and build a nested tree
- Collapsible tree (folders and files). Files appear alongside folders at the same level.
- Playlist on the right (reorderable via drag & drop)
- Play / Pause / Stop / Next / Previous
- Progress slider and time label
- "Now Playing" label
- Rescan button and folder chooser (saves chosen folder in config.json)
- Caches library to data/library.json

-newest update fixes the code so that songs in music dir doesn't crash the app
"""
import os
import sys
import subprocess
import random
from functools import partial
from PyQt6.QtWidgets import (
    QApplication, QWidget, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QSlider, QHBoxLayout, QVBoxLayout, QFileDialog, QMessageBox, QCheckBox,
    QSplitter, QSizePolicy, QFrame, QStyle, QStackedWidget, QFormLayout, QLineEdit, QAbstractItemView,
    QMenu, QMainWindow, QMenuBar, QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QDialogButtonBox,
    QComboBox, QGroupBox, QTabWidget)
import signal
import datetime
import random
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl, QPoint, QSize
from PyQt6.QtGui import QIcon, QFont, QPixmap, QImage, QCursor, QColor, QAction, QPainter, QBrush, QPen
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from config import load_config, save_config
from metadata import ScannerThread, MetadataManager, PROJECT_DIR, create_library_snapshot
from database_logic import DatabaseManager
from pathlib import Path
import musicbrainzngs

# Initialize MusicBrainz
musicbrainzngs.set_useragent("MP3VibePlayer", "0.1", "https://github.com/specstx/project_mp3_vibe")

DEFAULT_MUSIC_PATH = str(Path.home() / "Music")
# ------------------------
# Background scanner thread
# ------------------------

class YinYangRatingWidget(QWidget):
    rating_saved = pyqtSignal(str, float) # New signal with path and rating
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.num_icons = 5
        self.icons = []
        self.current_rating = 0.0  # 0 to 5 in 0.5 steps
        self.half_icon = QPixmap(str(PROJECT_DIR / "Image" / "half_yin.png"))
        self.full_icon = QPixmap(str(PROJECT_DIR / "Image" / "whole_yin.png"))
        self.empty_icon = QPixmap(str(PROJECT_DIR / "Image" / "empty_yin.png"))
#comment for nothing
        layout = QHBoxLayout()
        layout.setSpacing(2)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        for i in range(self.num_icons):
            lbl = QLabel()
            lbl.setPixmap(self.empty_icon)
            lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            lbl.setMouseTracking(True)  # ensure hover events arrive without pressing
            lbl.mouseMoveEvent = self._make_hover_handler(i)
            lbl.mousePressEvent = self._make_click_handler(i)
            # restore normal icons on leave
            lbl.enterEvent = (lambda ev, idx=i: self._update_icons(hover_index=idx, hover_half=False))
            lbl.leaveEvent = (lambda ev: self._update_icons())
            self.icons.append(lbl)
            layout.addWidget(lbl)

        # initialize visual state immediately
        self._update_icons()
    def load_rating(self, abs_path, rel_path=None):
        self._current_abs_path = abs_path
        self._current_rel_path = rel_path or abs_path
        self.current_rating = MetadataManager.load_rating(abs_path) 
        self._update_icons()

    def _update_icons(self, hover_index=None, hover_half=False):
        for i, lbl in enumerate(self.icons):
            if hover_index is not None:
                if i < hover_index:
                    lbl.setPixmap(self.full_icon)
                elif i == hover_index:
                    lbl.setPixmap(self.half_icon if hover_half else self.full_icon)
                else:
                    lbl.setPixmap(self.empty_icon)
            else:
                if i < int(self.current_rating):
                    lbl.setPixmap(self.full_icon)
                elif i < self.current_rating:
                    lbl.setPixmap(self.half_icon)
                else:
                    lbl.setPixmap(self.empty_icon)

    def _make_hover_handler(self, index):
        def handler(event):
            x = event.position().x()
            lbl = self.icons[index]
            hover_half = x < lbl.width() / 2
            self._update_icons(hover_index=index, hover_half=hover_half)
        return handler

    def _make_click_handler(self, index):
        """Creates a closure function to handle clicks on the rating icons."""
        
        def handler(event):
            if event.button() != Qt.MouseButton.LeftButton:
                return
            
            x = event.position().x()
            lbl = self.icons[index]
            half = x < lbl.width() / 2
            
            self.current_rating = index + 0.5 if half else index + 1
            self._update_icons()

            abs_path = getattr(self, "_current_abs_path", None)
            rel_path = getattr(self, "_current_rel_path", None)
            
            # Call MetadataManager to save the new rating
            if abs_path and MetadataManager.save_rating(abs_path, self.current_rating, rel_path=rel_path):
                self.rating_saved.emit(rel_path, self.current_rating) # Emit signal with relative path
            else:
                # If save fails, revert the icons and show a message
                self.current_rating = MetadataManager.load_rating(abs_path) 
                self._update_icons()
                QMessageBox.warning(self, "Error", "Failed to save rating. Check console for details.")
        
        return handler
        
        
        
        
    
    #comments too
# ------------------------
# Utility functions
# ------------------------
class CustomTreeWidgetItem(QTreeWidgetItem):
    """
    A custom QTreeWidgetItem that overrides the sorting logic for specific columns.
    """
    def __lt__(self, other):
        sort_column = self.treeWidget().sortColumn()
        
        # In-place column index for "Track #" is 2
        if sort_column == 2:
            try:
                # Pre-process the string to handle "X/Y" format, then convert to int
                my_text = self.text(sort_column).split('/')[0]
                other_text = other.text(sort_column).split('/')[0]
                my_num = int(my_text)
                other_num = int(other_text)
                return my_num < other_num
            except (ValueError, TypeError):
                # If conversion fails for any reason, fallback to default string comparison
                return super().__lt__(other)
        
        # For all other columns, use the default comparison
        return super().__lt__(other)

class TagFixerThread(QThread):
    finished = pyqtSignal(int, int) # successful_fixes, failed_fixes

    def __init__(self, tags_to_fix, music_path):
        super().__init__()
        self.tags_to_fix = tags_to_fix
        self.music_path = music_path

    def run(self):
        successful = 0
        failed = 0
        log_entries = []
        for rel_path, new_value in self.tags_to_fix:
            abs_path = os.path.join(self.music_path, rel_path)
            if MetadataManager.save_tags(abs_path, {'tracknumber': new_value}, rel_path=rel_path):
                successful += 1
            else:
                failed += 1
                log_entries.append(f"{datetime.datetime.now()} - FAILED Track Fix: {rel_path}")
        
        if log_entries:
            with open("audit_log.txt", "a") as f:
                f.write("\n".join(log_entries) + "\n")
                
        self.finished.emit(successful, failed)


class YearFixerThread(QThread):
    finished = pyqtSignal(int, int) # successful_fixes, failed_fixes

    def __init__(self, years_to_fix, music_path):
        super().__init__()
        self.years_to_fix = years_to_fix
        self.music_path = music_path

    def run(self):
        successful = 0
        failed = 0
        log_entries = []
        for rel_path, new_value in self.years_to_fix:
            abs_path = os.path.join(self.music_path, rel_path)
            if MetadataManager.save_tags(abs_path, {'date': new_value}, rel_path=rel_path):
                successful += 1
            else:
                failed += 1
                log_entries.append(f"{datetime.datetime.now()} - FAILED Year Fix: {rel_path}")

        if log_entries:
            with open("audit_log.txt", "a") as f:
                f.write("\n".join(log_entries) + "\n")

        self.finished.emit(successful, failed)


class ClickableSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.orientation() == Qt.Orientation.Horizontal:
                value = event.position().x() / self.width()
            else: # Vertical
                value = (self.height() - event.position().y()) / self.height()
            
            new_val = int(value * (self.maximum() - self.minimum()) + self.minimum())
            self.setValue(new_val)
            self.sliderReleased.emit() # trigger existing handler
        super().mousePressEvent(event)

# ------------------------
# Custom Volume Control
# ------------------------
class VolumeControlWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.audio_output = None
        
        self.icon_label = QLabel()
        self.icon_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.icon_label.setFixedSize(24, 24)

        # --- Popup Slider ---
        self.slider_popup = QWidget(self, Qt.WindowType.Popup)
        self.slider_popup.setFixedSize(24, 100)
        popup_layout = QVBoxLayout()
        popup_layout.setContentsMargins(0, 5, 0, 5)
        self.slider_popup.setLayout(popup_layout)

        self.volume_slider = ClickableSlider(Qt.Orientation.Vertical)
        self.volume_slider.setRange(0, 100)
        popup_layout.addWidget(self.volume_slider)
        
        # --- Main Layout ---
        layout = QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.icon_label)
        self.setLayout(layout)

        # Connect mouse events using a timer to differentiate single/double clicks
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.toggle_mute)
        self.icon_label.mousePressEvent = self.icon_mouse_press
        self.icon_label.mouseDoubleClickEvent = self.icon_mouse_double_click

    def setAudioOutput(self, audio_output):
        self.audio_output = audio_output
        self.audio_output.volumeChanged.connect(self.update_from_audio_output)
        self.audio_output.mutedChanged.connect(self.update_from_audio_output)
        self.volume_slider.valueChanged.connect(self.set_volume_from_slider)
        self.update_from_audio_output() # Initial setup

    def set_volume_from_slider(self, value):
        if self.audio_output:
            # Perceptual volume: cubic mapping feels more natural to human ears
            perceptual_volume = (value / 100.0) ** 3
            self.audio_output.setVolume(perceptual_volume)

    def update_from_audio_output(self):
        if not self.audio_output:
            return
            
        # Update slider position (reverse the cubic mapping)
        vol = self.audio_output.volume()
        slider_val = int((vol ** (1/3.0)) * 100)
        
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(slider_val)
        self.volume_slider.blockSignals(False)

        # Update icon
        style = self.style()
        if self.audio_output.isMuted() or self.audio_output.volume() == 0:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
        elif self.audio_output.volume() < 0.5:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        else:
            # NOTE: Using SP_MediaVolume for high volume too.
            # A dedicated high-volume icon is not standard in QStyle.
            icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        
        self.icon_label.setPixmap(icon.pixmap(22, 22)) # 22x22 for padding

    def icon_mouse_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._timer.start(QApplication.doubleClickInterval())

    def icon_mouse_double_click(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._timer.stop()
            self.show_slider()

    def toggle_mute(self):
        if self.audio_output:
            self.audio_output.setMuted(not self.audio_output.isMuted())

    def show_slider(self):
        # Position the popup right above the icon
        point = self.mapToGlobal(self.rect().topLeft())
        self.slider_popup.move(point.x(), point.y() - self.slider_popup.height())
        self.slider_popup.show()

# --- Sovereign: TreePopulationThread needs to use the relative path logic ---
class TreePopulationThread(QThread):
    finished = pyqtSignal(dict)

    def __init__(self, music_path):
        super().__init__()
        self.music_path = music_path

    def run(self):
        # Fetch only songs that are currently 'Present' on the located drive
        songs = DatabaseManager.get_present_songs()
        
        hierarchy = {}
        for s in songs:
            g, ar, al = getattr(s, "genre", None) or "Unknown", getattr(s, "artist", None) or "Unknown", getattr(s, "album", None) or "Unknown"
            
            if g not in hierarchy: hierarchy[g] = {}
            if ar not in hierarchy[g]: hierarchy[g][ar] = {}
            if al not in hierarchy[g][ar]: hierarchy[g][ar][al] = []
            
            hierarchy[g][ar][al].append(s)
            
        # Sort tracks within each album
        for g in hierarchy:
            for ar in hierarchy[g]:
                for al in hierarchy[g][ar]:
                    hierarchy[g][ar][al].sort(key=self.track_sort_key)
                    
        self.finished.emit(hierarchy)

    def track_sort_key(self, song):
        try:
            track_str = str(getattr(song, 'ext_1', '0') or '0')
            track_part = track_str.split('/')[0]
            return int(track_part)
        except (ValueError, TypeError):
            return 0

class ExtendedTagsDialog(QDialog):
    def __init__(self, abs_path, rel_path, parent=None):
        super().__init__(parent)
        self.abs_path = abs_path
        self.rel_path = rel_path
        self.setWindowTitle(f"Extended Tags: {Path(rel_path).name}")
        self.resize(500, 400)
        
        self.layout = QVBoxLayout(self)
        
        # Table for tags
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Tag Key", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.layout.addWidget(self.table)
        
        # Load tags
        self.tags = MetadataManager.get_extended_tags(abs_path)
        self.populate_table()
        
        # Buttons
        self.btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.btn_box.accepted.connect(self.save_and_close)
        self.btn_box.rejected.connect(self.reject)
        self.layout.addWidget(self.btn_box)

    def populate_table(self):
        self.table.setRowCount(len(self.tags))
        for i, (key, value) in enumerate(sorted(self.tags.items())):
            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable) # Key is read-only
            self.table.setItem(i, 0, key_item)
            self.table.setItem(i, 1, QTableWidgetItem(str(value)))

    def save_and_close(self):
        new_tags = {}
        for i in range(self.table.rowCount()):
            key = self.table.item(i, 0).text()
            val = self.table.item(i, 1).text()
            new_tags[key] = val
            
        if MetadataManager.save_extended_tags(self.abs_path, new_tags, rel_path=self.rel_path):
            self.accept()
        else:
            QMessageBox.critical(self, "Error", "Failed to save extended tags.")

class EqualizerWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setObjectName("Equalizer")
        self.setFixedHeight(120)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("10-Band Equalizer")
        title.setStyleSheet("font-weight: bold; color: #FFC107;")
        header.addWidget(title)
        
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Flat", "Rock", "Pop", "Jazz", "Classical", "Vibe"])
        self.preset_combo.setFixedWidth(80)
        header.addWidget(self.preset_combo)
        
        self.on_off = QCheckBox("On")
        self.on_off.setChecked(True)
        header.addWidget(self.on_off)
        layout.addLayout(header)
        
        # Sliders
        slider_row = QHBoxLayout()
        self.sliders = []
        bands = ["32", "64", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
        
        for band in bands:
            v_box = QVBoxLayout()
            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(-12, 12)
            slider.setValue(0)
            slider.setFixedHeight(60)
            self.sliders.append(slider)
            
            lbl = QLabel(band)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 8px; color: #A78BFA;")
            
            v_box.addWidget(slider)
            v_box.addWidget(lbl)
            slider_row.addLayout(v_box)
            
        layout.addLayout(slider_row)

class VisualizerWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        self.setFixedHeight(100)
        self.setStyleSheet("background-color: black;")
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.is_active = False
        
        self.bars = 32
        self.heights = [0] * self.bars

    def start(self):
        self.is_active = True
        self.timer.start(50) # 20 FPS

    def stop(self):
        self.is_active = False
        self.timer.stop()
        self.heights = [0] * self.bars
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w = self.width()
        h = self.height()
        bar_w = w / self.bars
        
        for i in range(self.bars):
            if self.is_active:
                # Random "vibe" simulation
                target = random.randint(5, h - 5)
                # Smooth movement
                self.heights[i] = self.heights[i] * 0.6 + target * 0.4
            else:
                self.heights[i] = max(0, self.heights[i] - 5)

            # Gradient color from violet to amber
            color = QColor("#A78BFA") # Violet
            if self.heights[i] > h * 0.7:
                color = QColor("#FFC107") # Amber for peaks
            
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            
            painter.drawRect(int(i * bar_w), int(h - self.heights[i]), int(bar_w - 2), int(self.heights[i]))

class CaseConversionDialog(QDialog):
    def __init__(self, current_tags, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Case Conversion")
        self.resize(350, 250)
        self.result_tags = None
        
        layout = QVBoxLayout(self)
        
        # Rule selection
        self.rule_combo = QComboBox()
        self.rule_combo.addItems([
            "Title Case (Every Word Capitalized)",
            "Sentence case (First word capitalized)",
            "UPPERCASE",
            "lowercase",
            "Trim Whitespace ($trim)"
        ])
        layout.addWidget(QLabel("Conversion Rule:"))
        layout.addWidget(self.rule_combo)
        
        # Tag selection (Checkboxes)
        layout.addWidget(QLabel("Apply to:"))
        self.check_boxes = {}
        for tag in ["artist", "title", "album", "genre"]:
            cb = QCheckBox(tag.capitalize())
            cb.setChecked(True)
            self.check_boxes[tag] = cb
            layout.addWidget(cb)
            
        # Preview
        self.preview_label = QLabel("<i>Select a rule to see preview</i>")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        
        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.apply_rule)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        
        self.current_tags = current_tags
        self.rule_combo.currentIndexChanged.connect(self.update_preview)
        self.update_preview()

    def update_preview(self):
        rule = self.rule_combo.currentText()
        test_val = "the BEATLES - abbey ROAD"
        preview = self.transform_text(test_val, rule)
        self.preview_label.setText(f"Preview: <b>{preview}</b>")

    def transform_text(self, text, rule):
        if not text: return ""
        if "Title Case" in rule:
            return text.title()
        elif "Sentence case" in rule:
            return text.capitalize()
        elif "UPPERCASE" in rule:
            return text.upper()
        elif "lowercase" in rule:
            return text.lower()
        elif "Trim" in rule:
            return text.strip()
        return text

    def apply_rule(self):
        rule = self.rule_combo.currentText()
        self.result_tags = self.current_tags.copy()
        
        for tag, cb in self.check_boxes.items():
            if cb.isChecked():
                old_val = self.result_tags.get(tag, "")
                self.result_tags[tag] = self.transform_text(old_val, rule)
        self.accept()

class CharReplacementDialog(QDialog):
    def __init__(self, current_tags, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Character Replacement")
        self.resize(350, 300)
        self.result_tags = None
        
        layout = QVBoxLayout(self)
        
        # Replacement inputs
        grid = QFormLayout()
        self.replace_input = QLineEdit("_")
        self.with_input = QLineEdit(" ")
        grid.addRow("Replace:", self.replace_input)
        grid.addRow("With:", self.with_input)
        layout.addLayout(grid)
        
        # Tag selection
        layout.addWidget(QLabel("Apply to:"))
        self.check_boxes = {}
        for tag in ["artist", "title", "album", "genre"]:
            cb = QCheckBox(tag.capitalize())
            cb.setChecked(True)
            self.check_boxes[tag] = cb
            layout.addWidget(cb)
            
        # Preview
        self.preview_label = QLabel("Preview: <b>...</b>")
        layout.addWidget(self.preview_label)
        
        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.apply_replacement)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        
        self.current_tags = current_tags
        self.replace_input.textChanged.connect(self.update_preview)
        self.with_input.textChanged.connect(self.update_preview)
        self.update_preview()

    def update_preview(self):
        old = self.replace_input.text()
        new = self.with_input.text()
        test_val = "Artist_-_Song_Title"
        preview = test_val.replace(old, new) if old else test_val
        self.preview_label.setText(f"Preview: <b>{preview}</b>")

    def apply_replacement(self):
        old = self.replace_input.text()
        new = self.with_input.text()
        if not old:
            self.reject()
            return
            
        self.result_tags = self.current_tags.copy()
        for tag, cb in self.check_boxes.items():
            if cb.isChecked():
                val = self.result_tags.get(tag, "")
                self.result_tags[tag] = val.replace(old, new)
        self.accept()

class MusicBrainzLookupDialog(QDialog):
    def __init__(self, current_tags, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MusicBrainz Metadata Lookup")
        self.resize(700, 500)
        self.result_tags = None
        self.current_tags = current_tags
        
        layout = QVBoxLayout(self)
        
        # Search Inputs
        search_row = QHBoxLayout()
        self.artist_input = QLineEdit(current_tags.get('artist', ''))
        self.title_input = QLineEdit(current_tags.get('title', ''))
        search_row.addWidget(QLabel("Artist:"))
        search_row.addWidget(self.artist_input)
        search_row.addWidget(QLabel("Title:"))
        search_row.addWidget(self.title_input)
        
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.perform_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)
        
        # Results Table
        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(["Score", "Title", "Artist", "Album / Release"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.itemSelectionChanged.connect(self.update_preview)
        layout.addWidget(self.results_table)
        
        # Comparison Preview
        self.preview_box = QGroupBox("Comparison Preview (Current vs. New)")
        preview_layout = QFormLayout(self.preview_box)
        self.comp_labels = {}
        for tag in ["Artist", "Title", "Album", "Year", "Genre"]:
            lbl = QLabel("---")
            lbl.setStyleSheet("color: #00E676;") # Green for new data
            self.comp_labels[tag] = lbl
            preview_layout.addRow(f"{tag}:", lbl)
        layout.addWidget(self.preview_box)
        
        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.apply_btn = btns.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_btn.setEnabled(False)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        
        self.search_results = []

    def perform_search(self):
        artist = self.artist_input.text().strip()
        title = self.title_input.text().strip()
        
        if not artist and not title: return
        
        try:
            # Search recording
            query = f'recording:"{title}" AND artist:"{artist}"'
            result = musicbrainzngs.search_recordings(query=query, limit=15)
            self.search_results = result.get('recording-list', [])
            
            self.results_table.setRowCount(len(self.search_results))
            for i, rec in enumerate(self.search_results):
                score = rec.get('ext:score', '0')
                title = rec.get('title', 'Unknown')
                artist = rec.get('artist-credit-phrase', 'Unknown')
                # Album info is under 'release-list'
                releases = rec.get('release-list', [])
                album = releases[0].get('title', 'N/A') if releases else "N/A"
                
                self.results_table.setItem(i, 0, QTableWidgetItem(score))
                self.results_table.setItem(i, 1, QTableWidgetItem(title))
                self.results_table.setItem(i, 2, QTableWidgetItem(artist))
                self.results_table.setItem(i, 3, QTableWidgetItem(album))
                
        except Exception as e:
            QMessageBox.critical(self, "Search Error", f"MusicBrainz search failed: {e}")

    def update_preview(self):
        row = self.results_table.currentRow()
        if row < 0: return
        
        rec = self.search_results[row]
        releases = rec.get('release-list', [])
        rel = releases[0] if releases else {}
        
        new_data = {
            "Artist": rec.get('artist-credit-phrase', 'Unknown'),
            "Title": rec.get('title', 'Unknown'),
            "Album": rel.get('title', 'N/A'),
            "Year": rel.get('date', 'N/A')[:4] if rel.get('date') else 'N/A',
            "Genre": "N/A" # MusicBrainz genres are complex, often omitted in basic search
        }
        
        for tag, lbl in self.comp_labels.items():
            curr = self.current_tags.get(tag.lower(), "---")
            lbl.setText(f"{curr}  →  {new_data[tag]}")
            
        self.apply_btn.setEnabled(True)
        # Store for the apply action
        self.result_tags = {
            "artist": new_data["Artist"],
            "title": new_data["Title"],
            "album": new_data["Album"],
            "date": new_data["Year"]
        }

class AdvancedStatsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sovereign Insights - Advanced Metrics")
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # 1. Heavy Rotation Tab
        self.rotation_tab = QWidget()
        self.rotation_layout = QVBoxLayout(self.rotation_tab)
        self.rotation_table = QTableWidget(0, 4)
        self.rotation_table.setHorizontalHeaderLabels(["Artist", "Title", "Actual Time Played", "Plays"])
        self.rotation_table.horizontalHeader().setStretchLastSection(True)
        self.rotation_layout.addWidget(self.rotation_table)
        self.tabs.addTab(self.rotation_tab, "Heavy Rotation")
        
        # 2. Stickiness Tab
        self.stick_tab = QWidget()
        self.stick_layout = QVBoxLayout(self.stick_tab)
        self.stick_table = QTableWidget(0, 3)
        self.stick_table.setHorizontalHeaderLabels(["Artist", "Title", "Completion Rate (%)"])
        self.stick_table.horizontalHeader().setStretchLastSection(True)
        self.stick_layout.addWidget(self.stick_table)
        self.tabs.addTab(self.stick_tab, "Stickiness (No-Skip)")
        
        # 3. Trends Tab
        self.trend_tab = QWidget()
        self.trend_layout = QVBoxLayout(self.trend_tab)
        self.trend_table = QTableWidget(0, 2)
        self.trend_table.setHorizontalHeaderLabels(["Artist", "Plays (Last 30 Days)"])
        self.trend_table.horizontalHeader().setStretchLastSection(True)
        self.trend_layout.addWidget(self.trend_table)
        self.tabs.addTab(self.trend_tab, "Recent Trends")
        
        self.load_data()

    def _format_time(self, seconds):
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}h {mins}m {secs}s"
        return f"{mins}m {secs}s"

    def load_data(self):
        # Rotation
        top_tracks = DatabaseManager.get_top_tracks_by_playtime()
        self.rotation_table.setRowCount(len(top_tracks))
        for i, row in enumerate(top_tracks):
            self.rotation_table.setItem(i, 0, QTableWidgetItem(row['artist']))
            self.rotation_table.setItem(i, 1, QTableWidgetItem(row['title']))
            self.rotation_table.setItem(i, 2, QTableWidgetItem(self._format_time(row['total_resided'])))
            self.rotation_table.setItem(i, 3, QTableWidgetItem(str(row['play_count'])))
            
        # Stickiness
        sticky = DatabaseManager.get_track_stickiness()
        self.stick_table.setRowCount(len(sticky))
        for i, row in enumerate(sticky):
            self.stick_table.setItem(i, 0, QTableWidgetItem(row['artist']))
            self.stick_table.setItem(i, 1, QTableWidgetItem(row['title']))
            self.stick_table.setItem(i, 2, QTableWidgetItem(f"{row['stickiness']:.1f}%"))
            
        # Trends
        trends = DatabaseManager.get_recent_trends()
        self.trend_table.setRowCount(len(trends))
        for i, row in enumerate(trends):
            self.trend_table.setItem(i, 0, QTableWidgetItem(row['artist']))
            self.trend_table.setItem(i, 1, QTableWidgetItem(str(row['plays'])))

# ------------------------
# Main Window
# ------------------------
class MP3Player(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MP3 Player")
        self.setWindowIcon(QIcon(str(PROJECT_DIR / "Image" / "mp3.png")))
        self.resize(1000, 600)

        # config
        self.cfg = load_config()
        self.music_path = self.cfg.get("music_path", DEFAULT_MUSIC_PATH)

        # internal state
        self.playlist_queue = []  # list of dicts: {'path': fullpath, 'title': filename}
        self.current_index = -1
        self.current_mp3_path = None
        self._is_populating = False
        self._play_counted = False  # Track if current song has been counted for metrics
        
        # Play Session Tracking
        self._current_session_path = None
        self._current_session_start_pos = 0 
        self._current_session_max_pos = 0 # Track furthest point reached in song
        self._current_session_accumulated_ms = 0 # Track total time resided (seek-proof)
        self._current_session_last_pos = 0 # Reference for delta calculation

        # Color constants
        self._COLOR_OFF_WHITE = QColor("#E0E0E0")
        self._COLOR_AMBER_GOLD = QColor("#FFC107")
        self._COLOR_GREEN = QColor("#00E676")
        self._COLOR_BLUE = QColor("#3C83F6")
        self._COLOR_VIOLET = QColor("#A78BFA")
        self._COLOR_DIM_BLUE = QColor("#4A6D9C")
        self._COLOR_DIM_VIOLET = QColor("#7A6FAC")
        self._COLOR_BG_DARK_CHARCOAL = QColor("#1C1C1C")
        self._COLOR_BG_PURE_BLACK = QColor("#000000")

        self._snapshot_is_dirty = False # New flag for library snapshot optimization
        self.scanner_thread = None
        self.fixer_thread = None
        self.year_fixer_thread = None
        self._tree_state_to_restore = None

        # Media player
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.player.playbackStateChanged.connect(self.on_playback_state_changed)

        # Custom volume control
        self.volume_control = VolumeControlWidget()
        self.volume_control.setAudioOutput(self.audio_output)

        # Equalizer & Visualizer (Placeholders)
        self.equalizer_widget = EqualizerWidget()
        self.visualizer_widget = VisualizerWidget()
        self.equalizer_widget.hide() # Hidden by default
        self.visualizer_widget.hide() # Hidden by default

        # Menu Bar
        self.init_menubar()

        # UI pieces
        self.tree = QTreeWidget()
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels(["Title", "Artist", "Track #", "Length", "Rating", "Year", "Comment"])
        self.tree.setRootIsDecorated(False)  # Remove the expander triangles
        self.tree.setAlternatingRowColors(True)  # Classic list view look
        # Set custom alternating row colors via stylesheet
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                alternate-background-color: {self._COLOR_BG_DARK_CHARCOAL.name()};
                background-color: {self._COLOR_BG_PURE_BLACK.name()};
            }}
        """)
        self.tree.setIndentation(0)  # Kill all staggered indentation
        self.tree.setSortingEnabled(True)
        self.tree.header().setStretchLastSection(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemDoubleClicked.connect(self.on_tree_item_double_clicked)
        self.tree.itemClicked.connect(self.on_tree_item_clicked)
        self.tree.itemExpanded.connect(self._update_hierarchy_item_color)
        self.tree.itemCollapsed.connect(self._update_hierarchy_item_color)
        
        self.playlist_widget = QTreeWidget()
        self.playlist_widget.setColumnCount(7)
        self.playlist_widget.setHeaderLabels(["Title", "Artist", "Duration", "Track #", "Comment", "Genre", "Year"])
        self.playlist_widget.header().setSectionsMovable(True)
        self.playlist_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.playlist_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.playlist_widget.setAlternatingRowColors(True)
        self.playlist_widget.setRootIsDecorated(False)
        self.playlist_widget.setIndentation(0)
        self.playlist_widget.setUniformRowHeights(True)

        # connect model's rowsMoved to update playlist order when drag-drop reorder happens
        self.playlist_widget.model().rowsMoved.connect(self.on_playlist_rows_moved)

        # connect double-click and single-click signals
        self.playlist_widget.itemDoubleClicked.connect(self.on_playlist_item_double_clicked)
        self.playlist_widget.itemClicked.connect(self.on_playlist_item_clicked)
        self.playlist_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_widget.customContextMenuRequested.connect(self.show_playlist_context_menu)

        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)

        # Stacked widget for playlist and tag editor
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.playlist_widget)

        # Tag editor
        self.tag_editor_widget = QWidget()
        self.tag_editor_layout = QFormLayout()
        self.tag_editor_widget.setLayout(self.tag_editor_layout)

        self.tag_fields = {
            "artist": QLineEdit(),
            "title": QLineEdit(),
            "albumartist": QLineEdit(),
            "tracknumber": QLineEdit(),
            "album": QLineEdit(),
            "genre": QLineEdit(),
        }

        display_labels = {
            "artist": "Artist",
            "title": "Title",
            "albumartist": "Album Artist",
            "tracknumber": "Track #",
            "album": "Album",
            "genre": "Genre",
        }

        for tag_name, display_name in display_labels.items():
            widget = self.tag_fields[tag_name]
            self.tag_editor_layout.addRow(display_name, widget)

        # Album Art and Rating (display only for now)
        self.album_art_label = QLabel("No Album Art")
        self.album_art_label.setFixedSize(150, 150) # Placeholder size
        self.album_art_label.setStyleSheet("border: 1px solid gray")
        self.tag_editor_layout.addRow("Album Art", self.album_art_label)

        # Replace rating label with interactive rating widget
        self.rating_widget = YinYangRatingWidget()
        self.tag_editor_layout.addRow("Rating", self.rating_widget)
        self.rating_widget.rating_saved.connect(self.on_rating_changed) # Connect rating changes to in-place update slot

        self.save_tags_btn = QPushButton("Save Tags")
        self.save_tags_btn.clicked.connect(self.save_tags)
        self.tag_editor_layout.addWidget(self.save_tags_btn)

        self.stacked_widget.addWidget(self.tag_editor_widget)
        self.stacked_widget.setCurrentIndex(1) # Start with tag editor view (library view)

        self.now_playing_label = QLabel("Not playing")
        self.now_playing_label.setWordWrap(False)
        self.time_label = QLabel("00:00 / 00:00")
        self.progress_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.sliderReleased.connect(self.on_seek_released)
        self.progress_slider.sliderPressed.connect(self.on_seek_pressed)
        self._seeking = False

        # control buttons
        self.play_btn = QPushButton()
        #self.play_btn.setFixedSize(70, 20)
        #self.pause_btn = QPushButton("Pause")
        #self.pause_btn.setFixedSize(70, 20)
        self.stop_btn = QPushButton()
        #self.stop_btn.setFixedSize(70, 20)
        self.prev_btn = QPushButton()
        #self.prev_btn.setFixedSize(70, 20)    
        self.next_btn = QPushButton()
        #self.next_btn.setFixedSize(70, 20)    
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.setFixedSize(70, 20)   
        #Library button bar
        self.folder_btn = QPushButton("Folder")
        self.folder_btn.setFixedSize(70, 20)   
        # View toggle button
        self.toggle_view_btn = QPushButton("View")
        self.toggle_view_btn.setFixedSize(70, 20)
        self.toggle_view_btn.clicked.connect(self.toggle_views)
        # Auto Play on double click checkbox
        self.autoplay_checkbox = QCheckBox("Auto")
        self.autoplay_checkbox.setChecked(False)  # default behavior
        self.autoplay_checkbox.setToolTip("Auto-play newly added songs")
        
        # assign built-in icons
        style = self.style()
        self.play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.stop_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.prev_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.next_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))

        # (optional) set sizes
        #for btn in (self.play_btn, self.stop_btn, self.prev_btn, self.next_btn):
        #     btn.setFixedSize(40, 30)

        # Scrolling marquee variables
        self._marquee_offset = 0
        self._marquee_text = ""
        self._marquee_timer = QTimer()
        self._marquee_timer.setInterval(180)  # update every 150ms
        self._marquee_timer.timeout.connect(self._scroll_now_playing)
        self._marquee_timer.start()


        # connect buttons
        self.play_btn.clicked.connect(self.on_play_clicked)
        #self.pause_btn.clicked.connect(self.on_pause_clicked)
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        self.prev_btn.clicked.connect(self.on_prev_clicked)
        self.next_btn.clicked.connect(self.on_next_clicked)
        self.rescan_btn.clicked.connect(self.start_scan)
        self.folder_btn.clicked.connect(self.change_library_folder)

        # Layout arrangement
        self.build_layout()

        # Restore column widths
        lib_widths = self.cfg.get('library_column_widths')
        if lib_widths:
            for i, width in enumerate(lib_widths):
                if i < self.tree.columnCount():
                    self.tree.setColumnWidth(i, width)
        
        play_widths = self.cfg.get('playlist_column_widths')
        if play_widths:
            for i, width in enumerate(play_widths):
                if i < self.playlist_widget.columnCount():
                    self.playlist_widget.setColumnWidth(i, width)

        # Stagger the initial load and scan to allow the UI to show up first
        QTimer.singleShot(100, self.initial_load_and_scan)

    def init_menubar(self):
        menubar = self.menuBar()
        
        # 1. File (Data Lifecycle)
        file_menu = menubar.addMenu("File")
        
        scan_sideshow_action = QAction("Scan SideShow", self)
        scan_sideshow_action.triggered.connect(self.scan_sideshow)
        file_menu.addAction(scan_sideshow_action)
        
        ingest_action = QAction("Ingest from Parking", self)
        ingest_action.triggered.connect(self.ingest_from_parking)
        file_menu.addAction(ingest_action)
        
        open_report_action = QAction("Open Ingestion Report", self)
        open_report_action.triggered.connect(self.file_open_ingestion_report)
        file_menu.addAction(open_report_action)
        
        add_folder_action = QAction("Add Folder to Collection", self)
        add_folder_action.triggered.connect(self.add_folder_to_collection)
        file_menu.addAction(add_folder_action)
        
        db_stats_action = QAction("Database Statistics", self)
        db_stats_action.triggered.connect(self.show_db_stats)
        file_menu.addAction(db_stats_action)
        
        prune_action = QAction("Prune Offline Tracks", self)
        prune_action.triggered.connect(self.prune_offline_tracks)
        file_menu.addAction(prune_action)
        
        clear_view_action = QAction("Clear View", self)
        clear_view_action.triggered.connect(self.clear_active_view)
        file_menu.addAction(clear_view_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 2. Edit (Surgical Metadata)
        edit_menu = menubar.addMenu("Edit")
        
        undo_action = QAction("Undo", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self.undo_tag_change)
        edit_menu.addAction(undo_action)
        
        redo_action = QAction("Redo", self)
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(self.redo_tag_change)
        edit_menu.addAction(redo_action)
        
        extended_tags_action = QAction("Extended Tags", self)
        extended_tags_action.triggered.connect(self.show_extended_tags)
        edit_menu.addAction(extended_tags_action)
        
        properties_action = QAction("Properties", self)
        properties_action.setShortcut("Alt+Return")
        properties_action.triggered.connect(self.show_file_properties)
        edit_menu.addAction(properties_action)

        # 3. Tools (Mass Operations)
        tools_menu = menubar.addMenu("Tools")
        
        case_conv_action = QAction("Case Conversion", self)
        case_conv_action.triggered.connect(self.tool_case_conversion)
        tools_menu.addAction(case_conv_action)
        
        char_replace_action = QAction("Character Replacement", self)
        char_replace_action.triggered.connect(self.tool_char_replacement)
        tools_menu.addAction(char_replace_action)
        
        autonumber_action = QAction("Autonumbering Wizard", self)
        autonumber_action.triggered.connect(self.tool_autonumbering)
        tools_menu.addAction(autonumber_action)
        
        integrity_action = QAction("Integrity Check", self)
        integrity_action.triggered.connect(self.tool_integrity_check)
        tools_menu.addAction(integrity_action)
        
        tools_menu.addSeparator()
        
        open_audit_log_action = QAction("Open Audit Log", self)
        open_audit_log_action.triggered.connect(self.tool_open_audit_log)
        tools_menu.addAction(open_audit_log_action)

        # 4. Tagger (Automated Logic)
        tagger_menu = menubar.addMenu("Tagger")
        
        musicbrainz_action = QAction("MusicBrainz Lookup", self)
        musicbrainz_action.triggered.connect(self.tagger_musicbrainz_lookup)
        tagger_menu.addAction(musicbrainz_action)
        
        cluster_action = QAction("Cluster Files", self)
        cluster_action.triggered.connect(self.tagger_cluster_files)
        tagger_menu.addAction(cluster_action)
        
        fingerprint_action = QAction("Scan Fingerprints (AcoustID)", self)
        fingerprint_action.triggered.connect(self.tagger_scan_fingerprints)
        tagger_menu.addAction(fingerprint_action)

        # 5. View (Modular UI Toggles)
        view_menu = menubar.addMenu("View")
        
        eq_action = QAction("Equalizer", self, checkable=True)
        eq_action.triggered.connect(self.toggle_equalizer)
        view_menu.addAction(eq_action)
        
        waveform_action = QAction("Waveform Viewer", self, checkable=True)
        waveform_action.triggered.connect(self.toggle_waveform)
        view_menu.addAction(waveform_action)
        
        visualizer_action = QAction("Visualizer", self, checkable=True)
        visualizer_action.triggered.connect(self.toggle_visualizer)
        view_menu.addAction(visualizer_action)
        
        view_menu.addSeparator()
        
        lib_tree_action = QAction("Library Tree / Playlist", self)
        lib_tree_action.triggered.connect(self.toggle_views)
        view_menu.addAction(lib_tree_action)

        # 6. Sync (Mirror & Backup)
        sync_menu = menubar.addMenu("Sync")
        
        audit_mirror_action = QAction("Audit Mirror", self)
        audit_mirror_action.triggered.connect(self.sync_audit_mirror)
        sync_menu.addAction(audit_mirror_action)
        
        hash_verif_action = QAction("Hash Verification", self)
        hash_verif_action.triggered.connect(self.sync_hash_verification)
        sync_menu.addAction(hash_verif_action)
        
        mirror_ext_action = QAction("Mirror to External (Sovereign Sync)", self)
        mirror_ext_action.triggered.connect(self.sync_now)
        sync_menu.addAction(mirror_ext_action)

    # --- Menu Action Stubs ---
    def scan_sideshow(self):
        """Trigger Sovereign Sync to index the library."""
        from sovereign_sync import SovereignSync
        # Pointing to the Master (SideShow) to sync to Mirror
        reply = QMessageBox.question(
            self, "Scan SideShow", 
            "Audit SideShow (Master) and sync to External (Mirror)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.now_playing_label.setText("Auditing Mirror...")
            QApplication.processEvents()
            try:
                # We can refine SovereignSync to allow 'Master -> Mirror' only runs later
                engine = SovereignSync()
                engine.run()
                QMessageBox.information(self, "Audit Complete", "Mirror sync/audit finished.")
            except Exception as e:
                QMessageBox.critical(self, "Audit Error", f"Error: {e}")
            finally:
                self.now_playing_label.setText("Ready")

    def ingest_from_parking(self):
        """Invoke the Sovereign Ingestion Engine (Parking -> Master)."""
        from sovereign_sync import SovereignIngest, SovereignSync
        
        reply = QMessageBox.question(
            self, "Sovereign Ingestion", 
            "Start Ingestion from Parking to SideShow (Master)?<br><br>"
            "Processed files will be moved to <b>processed_trashcan</b>.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.now_playing_label.setText("Ingesting from Parking...")
            QApplication.processEvents()
            
            try:
                # 1. Run Ingestion
                ingest_engine = SovereignIngest()
                ingest_engine.run()
                
                # 2. Ask if we should mirror the changes immediately
                mirror_reply = QMessageBox.question(
                    self, "Ingestion Complete",
                    "Ingestion finished. Check <b>ingestion_report.txt</b> for details.<br><br>"
                    "Would you like to <b>Mirror</b> these changes to the External drive now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if mirror_reply == QMessageBox.StandardButton.Yes:
                    self.now_playing_label.setText("Mirroring to External...")
                    sync_engine = SovereignSync()
                    sync_engine.run_mirror()
                    QMessageBox.information(self, "Sync Complete", "Mirroring finished.")
                
                # 3. Always trigger a rescan to show new files in UI
                self.start_scan()
                
            except Exception as e:
                QMessageBox.critical(self, "Ingestion Error", f"An error occurred: {e}")
            finally:
                self.now_playing_label.setText("Ready")

    def add_folder_to_collection(self): pass
    
    def show_db_stats(self):
        """Displays database statistics in a formatted dialog."""
        stats = DatabaseManager.get_statistics()
        
        # Calculate human readable duration
        td = stats['total_duration']
        days = int(td // 86400)
        hours = int((td % 86400) // 3600)
        minutes = int((td % 3600) // 60)
        
        msg = (
            f"<b>Library Overview</b><br><br>"
            f"Online Tracks: {stats['online_tracks']:,}<br>"
            f"Offline Tracks: {stats['offline_tracks']:,}<br>"
            f"Total Playtime (Online): {days}d {hours}h {minutes}m<br>"
            f"Top Genre: {stats['top_genre']}<br>"
            f"Top Artist: {stats['top_artist']}<br><br>"
            f"<b>Health & Ratings (Online Only)</b><br>"
            f"Missing Metadata: {stats['missing_metadata']}<br>"
            f"Highly Rated (4.0+): {stats['top_rated_count']}"
        )
        
        box = QMessageBox(self)
        box.setWindowTitle("Database Statistics")
        box.setText(msg)
        box.setIcon(QMessageBox.Icon.Information)
        
        # Add a custom button for Advanced Stats
        adv_btn = box.addButton("Advanced Stats...", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        
        box.exec()
        
        if box.clickedButton() == adv_btn:
            dlg = AdvancedStatsDialog(self)
            dlg.exec()

    def prune_offline_tracks(self):
        """Permanently deletes songs that are marked as offline."""
        stats = DatabaseManager.get_statistics()
        offline_count = stats['offline_tracks']
        
        if offline_count == 0:
            QMessageBox.information(self, "Prune Library", "No offline tracks found to prune.")
            return

        reply = QMessageBox.warning(
            self, "Prune Offline Tracks", 
            f"Found {offline_count:,} tracks that are not on the current drive.<br><br>"
            "Are you sure you want to <b>permanently delete</b> these records and their history from the database?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            count = DatabaseManager.delete_offline_songs()
            QMessageBox.information(self, "Prune Complete", f"Successfully removed {count:,} stale records.")
            self.populate_tree() # Refresh UI

    def clear_active_view(self):
        """Clears the active playlist."""
        if self.playlist_queue:
            reply = QMessageBox.question(
                self, "Clear View", "Clear the current playlist?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.playlist_queue = []
                self.current_index = -1
                self.playlist_widget.clear()
                self.update_playlist_ui()
                self.now_playing_label.setText("Playlist Cleared")
    
    def undo_tag_change(self): pass
    def redo_tag_change(self): pass
    
    def _get_selected_rel_path(self):
        """Helper to get the relative path of the selected track in Tree or Playlist."""
        # Check Library Tree first
        item = self.tree.currentItem()
        if item:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and isinstance(data, dict) and data.get('type') == 'track':
                return data.get('path')
        
        # Check Playlist Widget
        p_item = self.playlist_widget.currentItem()
        if p_item:
            path = p_item.data(0, Qt.ItemDataRole.UserRole)
            if path:
                return path
        
        # Fallback to current playing path if nothing selected
        return self.current_mp3_path

    def show_extended_tags(self):
        """Opens the deep tag editor for the selected track."""
        rel_path = self._get_selected_rel_path()
        if not rel_path:
            QMessageBox.information(self, "Extended Tags", "Please select a track first.")
            return

        abs_path = os.path.join(self.music_path, rel_path)
        if not os.path.exists(abs_path):
            QMessageBox.critical(self, "Error", f"File not found: {rel_path}")
            return

        dlg = ExtendedTagsDialog(abs_path, rel_path, self)
        if dlg.exec():
            # If saved, refresh the UI info
            self.load_track_info(rel_path)
            self.populate_tree() # Full refresh to update grid if Genre/Artist changed
            QMessageBox.information(self, "Success", "Extended tags saved successfully.")

    def show_file_properties(self):
        """Displays technical properties for the selected track."""
        rel_path = self._get_selected_rel_path()
        if not rel_path:
            QMessageBox.information(self, "Properties", "Please select a track first.")
            return

        abs_path = os.path.join(self.music_path, rel_path)
        if not os.path.exists(abs_path):
            QMessageBox.critical(self, "Error", f"File not found: {rel_path}")
            return

        props = MetadataManager.get_technical_properties(abs_path)
        
        msg = "<b>Technical Properties</b><br><br>"
        for key, val in props.items():
            msg += f"<b>{key}:</b> {val}<br>"
        
        QMessageBox.information(self, "Track Properties", msg)
    
    def tool_case_conversion(self):
        """Applies casing rules to tags of the selected track."""
        rel_path = self._get_selected_rel_path()
        if not rel_path:
            QMessageBox.information(self, "Case Conversion", "Please select a track first.")
            return

        abs_path = os.path.join(self.music_path, rel_path)
        if not os.path.exists(abs_path):
            QMessageBox.critical(self, "Error", f"File not found: {rel_path}")
            return

        # Load current tags
        tags, _ = MetadataManager.load_tags_and_art(abs_path)
        
        dlg = CaseConversionDialog(tags, self)
        if dlg.exec():
            # If Ok, save the transformed tags
            if MetadataManager.save_tags(abs_path, dlg.result_tags, rel_path=rel_path):
                self.load_track_info(rel_path)
                self.populate_tree()
                QMessageBox.information(self, "Success", "Case conversion applied successfully.")
            else:
                QMessageBox.critical(self, "Error", "Failed to apply case conversion.")
    def tool_char_replacement(self):
        """Replaces characters/strings in tags of the selected track."""
        rel_path = self._get_selected_rel_path()
        if not rel_path:
            QMessageBox.information(self, "Character Replacement", "Please select a track first.")
            return

        abs_path = os.path.join(self.music_path, rel_path)
        if not os.path.exists(abs_path):
            QMessageBox.critical(self, "Error", f"File not found: {rel_path}")
            return

        # Load current tags
        tags, _ = MetadataManager.load_tags_and_art(abs_path)
        
        dlg = CharReplacementDialog(tags, self)
        if dlg.exec():
            # If Ok, save the transformed tags
            if MetadataManager.save_tags(abs_path, dlg.result_tags, rel_path=rel_path):
                self.load_track_info(rel_path)
                self.populate_tree()
                QMessageBox.information(self, "Success", "Character replacement applied successfully.")
            else:
                QMessageBox.critical(self, "Error", "Failed to apply character replacement.")
    def tool_autonumbering(self):
        """Sequentially re-numbers tracks in the selected album."""
        item = self.tree.currentItem()
        if not item:
            QMessageBox.information(self, "Autonumbering", "Please select an Album folder in the library tree.")
            return
            
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get('type') != 'album':
            QMessageBox.information(self, "Autonumbering", "This tool only works on Album folders.")
            return

        # Collect all tracks under this album item
        track_items = []
        for i in range(item.childCount()):
            child = item.child(i)
            c_data = child.data(0, Qt.ItemDataRole.UserRole)
            if c_data and c_data.get('type') == 'track':
                track_items.append(child)

        if not track_items:
            QMessageBox.information(self, "Autonumbering", "No tracks found in this album.")
            return

        # Show confirmation with preview
        msg = f"<b>Autonumbering Wizard</b><br><br>Album: {item.text(0)}<br><br>"
        msg += "This will re-number the following tracks sequentially (1, 2, 3...):<br><br>"
        for i, t_item in enumerate(track_items, 1):
            msg += f"{i}. {t_item.text(0)}<br>"
        
        reply = QMessageBox.question(
            self, "Autonumbering", msg,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        
        if reply == QMessageBox.StandardButton.Ok:
            self.now_playing_label.setText("Autonumbering Album...")
            QApplication.processEvents()
            
            success_count = 0
            for i, t_item in enumerate(track_items, 1):
                rel_path = t_item.data(0, Qt.ItemDataRole.UserRole).get('path')
                abs_path = os.path.join(self.music_path, rel_path)
                
                # Save only the tracknumber
                if MetadataManager.save_tags(abs_path, {'tracknumber': str(i)}, rel_path=rel_path):
                    success_count += 1
            
            self.populate_tree()
            QMessageBox.information(self, "Success", f"Successfully re-numbered {success_count} tracks.")
            self.now_playing_label.setText("Ready")
    def tool_integrity_check(self):
        """Audits the library for missing metadata and logs details."""
        songs = DatabaseManager.get_present_songs()
        if not songs:
            QMessageBox.information(self, "Integrity Check", "No online songs found to audit.")
            return

        self.now_playing_label.setText("Auditing Library Metadata...")
        QApplication.processEvents()

        unhealthy_count = 0
        log_entries = [f"\n--- METADATA AUDIT: {datetime.datetime.now()} ---"]
        
        for song in songs:
            missing = MetadataManager.get_missing_tags(song)
            if missing:
                unhealthy_count += 1
                tags_str = ", ".join(missing)
                log_entries.append(f"MISSING [{tags_str}]: {song.file_path}")

        if unhealthy_count > 0:
            with open("audit_log.txt", "a") as f:
                f.write("\n".join(log_entries) + "\n")
            
            msg = (
                f"<b>Integrity Check Complete</b><br><br>"
                f"Found {unhealthy_count:,} tracks with missing metadata.<br><br>"
                f"Details have been logged to <b>audit_log.txt</b>."
            )
            QMessageBox.warning(self, "Integrity Check", msg)
        else:
            QMessageBox.information(self, "Integrity Check", "Metadata Audit passed! No missing tags found.")
        
        self.now_playing_label.setText("Ready")

    def tool_open_audit_log(self):
        """Opens the audit_log.txt file in the system default editor."""
        log_path = os.path.join(PROJECT_DIR, "audit_log.txt")
        if os.path.exists(log_path):
            subprocess.run(["xdg-open", log_path])
        else:
            QMessageBox.information(self, "Audit Log", "No audit log found.")

    def file_open_ingestion_report(self):
        """Opens the ingestion_report.txt file in the system default editor."""
        # Find the parking folder from SovereignSync defaults
        from sovereign_sync import DEFAULT_SOURCE
        report_path = os.path.join(DEFAULT_SOURCE, "ingestion_report.txt")
        if os.path.exists(report_path):
            subprocess.run(["xdg-open", report_path])
        else:
            QMessageBox.information(self, "Ingestion Report", "No ingestion report found.")

    def tagger_musicbrainz_lookup(self):
        """Fetches metadata from MusicBrainz for the selected track."""
        rel_path = self._get_selected_rel_path()
        if not rel_path:
            QMessageBox.information(self, "MusicBrainz Lookup", "Please select a track first.")
            return

        abs_path = os.path.join(self.music_path, rel_path)
        if not os.path.exists(abs_path):
            QMessageBox.critical(self, "Error", f"File not found: {rel_path}")
            return

        # Load current tags
        tags, _ = MetadataManager.load_tags_and_art(abs_path)
        
        dlg = MusicBrainzLookupDialog(tags, self)
        if dlg.exec():
            # Strict Confirmation Box
            new_data = dlg.result_tags
            msg = (
                f"<b>Confirm Tag Update</b><br><br>"
                f"Are you sure you want to overwrite tags for:<br><i>{Path(rel_path).name}</i><br><br>"
                f"<b>Artist:</b> {new_data['artist']}<br>"
                f"<b>Title:</b> {new_data['title']}<br>"
                f"<b>Album:</b> {new_data['album']}<br>"
                f"<b>Year:</b> {new_data['date']}"
            )
            
            confirm = QMessageBox.question(
                self, "MusicBrainz Confirmation", msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if confirm == QMessageBox.StandardButton.Yes:
                if MetadataManager.save_tags(abs_path, new_data, rel_path=rel_path):
                    self.load_track_info(rel_path)
                    self.populate_tree()
                    QMessageBox.information(self, "Success", "Metadata updated from MusicBrainz.")
                else:
                    QMessageBox.critical(self, "Error", "Failed to save tags.")

    def tagger_cluster_files(self): pass
    def tagger_scan_fingerprints(self): pass
    
    def toggle_equalizer(self, checked):
        if checked:
            self.equalizer_widget.show()
        else:
            self.equalizer_widget.hide()

    def toggle_waveform(self, checked): pass

    def toggle_visualizer(self, checked):
        if checked:
            self.visualizer_widget.show()
            # Start animation only if playing
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.visualizer_widget.start()
        else:
            self.visualizer_widget.stop()
            self.visualizer_widget.hide()
    
    def sync_audit_mirror(self): pass
    def sync_hash_verification(self): pass

    def sync_now(self):
        """Invoke the Sovereign Sync Engine."""
        from sovereign_sync import SovereignSync
        
        # We can confirm with user first as per the rule
        reply = QMessageBox.question(
            self, "Sovereign Sync", 
            "Start Sovereign Sync (Parking -> Master -> Mirror)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.now_playing_label.setText("Syncing...")
            QApplication.processEvents()
            
            try:
                # Initialize engine with defaults
                engine = SovereignSync()
                
                # Pre-check mirror drive existence
                if not engine.mirror.exists():
                    QMessageBox.warning(self, "Mirror Drive Missing", f"The Mirror drive was not found at:<br><br><b>{engine.mirror}</b><br><br>Please plug it in and try again.")
                    return

                engine.run()
                QMessageBox.information(self, "Sync Complete", "Sovereign Sync finished successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Sync Error", f"An error occurred during sync: {e}")
            finally:
                self.now_playing_label.setText("Ready")

    def _mark_snapshot_dirty(self):
        self._snapshot_is_dirty = True
        print("Snapshot marked as dirty.") # For debugging

    def update_library_snapshot(self, force_update=False, snapshot=None):
        """
        Updates the stored library snapshot in config.json if forced or if the snapshot is dirty.
        If a snapshot dict is provided, it uses that instead of re-scanning.
        """
        if force_update or self._snapshot_is_dirty:
            print("Updating library snapshot...")
            if snapshot:
                current_snapshot = snapshot
            else:
                current_snapshot = create_library_snapshot(self.music_path)
            
            self.cfg['library_snapshot'] = current_snapshot
            save_config(self.cfg)
            self._snapshot_is_dirty = False
            print("Library snapshot updated.")
        else:
            print("Snapshot not dirty, skipping update.")

    def initial_load_and_scan(self):
        """
        Populates the UI with existing DB data for a fast startup,
        then starts a background scan to prune and update the library.
        """
        # Step 0: Check if scan is needed
        saved_snapshot = self.cfg.get('library_snapshot')
        current_snapshot = create_library_snapshot(self.music_path)

        if saved_snapshot and saved_snapshot == current_snapshot:
            print("Library unchanged, skipping background scan.")
            # Ensure scanner_thread is ready for manual rescans
            self.scanner_thread = ScannerThread(self.music_path)
            self.scanner_thread.finished.connect(self.on_scan_finished)
            self.scanner_thread.progress.connect(self.on_scan_progress)
            
            # Step 1: Populate the tree immediately with current DB data
            print("Performing initial library load from database...")
            # Restore state if available (fallback to old expanded_paths if tree_state is missing)
            tree_state = self.cfg.get('tree_state', self.cfg.get('expanded_paths', []))
            self.populate_tree(tree_state)
            self.rescan_btn.setEnabled(True)
            self.now_playing_label.setText("Ready")
            return
        else:
            print("Library changed or no previous snapshot, initiating background scan.")
            # Step 1: Populate the tree immediately with current DB data
            print("Performing initial library load from database...")
            # Restore state if available
            tree_state = self.cfg.get('tree_state', self.cfg.get('expanded_paths', []))
            self.populate_tree(tree_state)
            
            # Step 2: Start the automatic background scan
            print("Starting automatic background scan to update and prune library...")
            # Use QTimer to ensure this runs AFTER the initial UI has had a chance to breathe
            QTimer.singleShot(500, lambda: self.start_scan(background=True))

    def build_layout(self):
        # Main layout container
        main_container = QWidget()
        self.setCentralWidget(main_container)
        main_layout = QHBoxLayout(main_container)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(0)

        # Left-hand tree
        main_layout.addWidget(self.tree)

        # -----------------------------
        # Right-hand panel layout
        # -----------------------------
        right_v = QVBoxLayout()
        right_v.setContentsMargins(5, 5, 5, 5)
        right_v.setSpacing(10)

        # --- Row 1: Now Playing label with scrolling ---
        self.now_playing_label.setMinimumHeight(30)
        self.now_playing_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right_v.addWidget(self.now_playing_label)

        # Add Visualizer and Equalizer here
        right_v.addWidget(self.visualizer_widget)
        right_v.addWidget(self.equalizer_widget)

        # --- Row 2: Control row ---
        control_row = QHBoxLayout()
        control_row.setSpacing(0)

        # Left: Current time label
        self.current_time_label = QLabel("00:00")
        self.current_time_label.setFixedWidth(60)
        self.current_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        control_row.addWidget(self.current_time_label)

        # Spacer before button group
        control_row.addStretch(1)

        # Center: Button group
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)  # preserve small gaps
        for btn in (self.play_btn, self.prev_btn, self.stop_btn, self.next_btn):
            btn_row.addWidget(btn)
        btn_container = QFrame()
        btn_container.setLayout(btn_row)
        control_row.addWidget(btn_container)

        # Spacer after button group
        control_row.addStretch(1)

        # Right: Total time label and Volume Control
        self.total_time_label = QLabel("00:00")
        self.total_time_label.setFixedWidth(60)
        self.total_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        control_row.addWidget(self.total_time_label)
        control_row.addWidget(self.volume_control)


        right_v.addLayout(control_row)

        # --- Row 3: Progress slider ---
        self.progress_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right_v.addWidget(self.progress_slider)

        # --- Row 4: Playlist/Tag Editor (expandable) ---
        self.stacked_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_v.addWidget(self.stacked_widget)

        # --- Row 5: Library controls at bottom ---
        lib_controls_row = QHBoxLayout()
        lib_controls_row.setSpacing(10)
        self.library_label = QLabel("Lib:")
        lib_controls_row.insertWidget(0, self.library_label)
        lib_controls_row.addWidget(self.rescan_btn)
        lib_controls_row.addWidget(self.folder_btn)
        lib_controls_row.addWidget(self.toggle_view_btn)

        # ✔ Add checkbox here
        lib_controls_row.addWidget(self.autoplay_checkbox)

        lib_controls_row.addStretch(1)
        right_v.addLayout(lib_controls_row)
        # Right panel frame
        right_frame = QFrame()
        right_frame.setLayout(right_v)
        right_frame.setMinimumWidth(320)
        right_frame.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        # Create a stacked widget for the left pane (library + playlist)
        self.left_stacked = QStackedWidget()
        self.left_stacked.addWidget(self.tree)             # index 0 → library
        self.left_stacked.addWidget(self.playlist_widget)  # index 1 → playlist
        self.left_stacked.setCurrentIndex(0)  # Start showing library

        # Splitter between left stacked (library/playlist) and right frame
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.left_stacked)
        splitter.addWidget(right_frame)
        splitter.setSizes([680, 320])

        # Add splitter to main layout
        main_layout.addWidget(splitter)

    def _build_tree_from_songs(self, songs, music_path):
        tree = {}
        for song in songs:
            try:
                rel_path = os.path.relpath(song.file_path, music_path)
                parts = list(Path(rel_path).parts)
                filename = parts.pop()
                node = tree
                for part in parts:
                    node = node.setdefault(part, {})
                node.setdefault('Unsorted', []).append(filename)
            except Exception:
                continue
        return tree

    # ------------------------
    # Scanning
    # ------------------------
    def start_scan(self, background=True):
        if not os.path.isdir(self.music_path):
            QMessageBox.warning(self, "Music folder not found", f"Folder not found: {self.music_path}")
            return
        
        # Prevent multiple scanner threads
        if self.scanner_thread and self.scanner_thread.isRunning():
            return

        self.rescan_btn.setEnabled(False)
        self.now_playing_label.setText("Preparing Scan...")
        print("UI: Preparing Scan...")
        QApplication.processEvents()

        # start thread
        self.scanner_thread = ScannerThread(self.music_path)
        self.scanner_thread.finished.connect(self.on_scan_finished)
        self.scanner_thread.progress.connect(self.on_scan_progress)
        
        if background:
            self.scanner_thread.start()
        else:
            # blocking run (rare)
            self.scanner_thread.run()
            # run() emits finished which calls on_scan_finished

    def on_scan_progress(self, status):
        self.now_playing_label.setText(status)

    def on_scan_finished(self, tree, tags_to_fix, years_to_fix, snapshot):
        self.library_tree = tree
        # CacheManager.save_library_cache(tree) # No longer needed, ScannerThread saves to DB
        self.populate_tree()
        self.rescan_btn.setEnabled(True)
        self.now_playing_label.setText("Ready")
        self.update_library_snapshot(force_update=True, snapshot=snapshot)

        if tags_to_fix:
            reply = QMessageBox.question(
                self,
                "Clean Tags",
                f"Found {len(tags_to_fix)} tracks with 'funky' track numbers. Clean them up now?",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Ok
            )
            if reply == QMessageBox.StandardButton.Ok:
                self._apply_tag_fixes(tags_to_fix)
        
        if years_to_fix:
            reply = QMessageBox.question(
                self,
                "Clean Year Tags",
                f"Found {len(years_to_fix)} tracks with invalid year formats. Clean them up now?",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Ok
            )
            if reply == QMessageBox.StandardButton.Ok:
                self._apply_year_fixes(years_to_fix)


    def _apply_tag_fixes(self, tags_to_fix):
        """Starts a background thread to apply track number fixes."""
        self.now_playing_label.setText(f"Fixing {len(tags_to_fix)} tags...")
        self.fixer_thread = TagFixerThread(tags_to_fix, self.music_path)
        self.fixer_thread.finished.connect(self._on_tag_fix_finished)
        self.fixer_thread.start()

    def _on_tag_fix_finished(self, successful, failed):
        """Handles the completion of the TagFixerThread."""
        self.now_playing_label.setText("Tag fixing complete.")
        msg = f"Successfully fixed {successful} tags.\nFailed to fix {failed} tags."
        if failed > 0:
            msg += "\n\nSee audit_log.txt for a list of failed files."
        
        QMessageBox.information(self, "Tag Fix Complete", msg)
        # The database is now in sync with the file tags, but the view is not.
        # A full populate is needed to show the corrected numbers.
        self.populate_tree()
        # The files have been modified, so we need a new snapshot.
        self.update_library_snapshot(force_update=True)

    def _apply_year_fixes(self, years_to_fix):
        """Starts a background thread to apply year fixes."""
        self.now_playing_label.setText(f"Fixing {len(years_to_fix)} year tags...")
        self.year_fixer_thread = YearFixerThread(years_to_fix, self.music_path)
        self.year_fixer_thread.finished.connect(self._on_year_fix_finished)
        self.year_fixer_thread.start()

    def _on_year_fix_finished(self, successful, failed):
        """Handles the completion of the YearFixerThread."""
        self.now_playing_label.setText("Year tag fixing complete.")
        msg = f"Successfully fixed {successful} year tags.\nFailed to fix {failed} year tags."
        if failed > 0:
            msg += "\n\nSee audit_log.txt for a list of failed files."

        QMessageBox.information(self, "Year Fix Complete", msg)
        # The database is now in sync with the file tags, but the view is not.
        # A full populate is needed to show the corrected numbers.
        self.populate_tree()
        # The files have been modified, so we need a new snapshot.
        self.update_library_snapshot(force_update=True)


    def get_item_path(self, item):
        path = []
        temp_item = item
        while temp_item is not None:
            text = ""
            if temp_item.text(0):
                text = temp_item.text(0)
            elif temp_item.text(1):
                text = temp_item.text(1)
            elif temp_item.text(2):
                text = temp_item.text(2)
            
            if text:
                path.insert(0, text)
            
            temp_item = temp_item.parent()
        return tuple(path)

    def save_tree_state(self):
        state = {
            'expanded_paths': [],
            'top_item_path': None
        }
        # 1. Capture expanded paths
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item.isExpanded():
                state['expanded_paths'].append(self.get_item_path(item))
            iterator += 1
            
        # 2. Capture top visible item
        top_item = self.tree.itemAt(0, 0)
        if top_item:
            state['top_item_path'] = self.get_item_path(top_item)
            
        return state

    def restore_tree_state(self, state):
        if not state:
            return
            
        # Handle if state is just a list (backward compatibility for old expansion-only logic)
        if isinstance(state, list):
            state = {'expanded_paths': state, 'top_item_path': None}
            
        expanded_paths = state.get('expanded_paths', [])
        top_item_path = state.get('top_item_path')
        
        # 1. Restore expansion states
        if expanded_paths:
            # Convert paths to tuples for comparison
            exp_set = set(tuple(p) for p in expanded_paths)
            iterator = QTreeWidgetItemIterator(self.tree)
            while iterator.value():
                item = iterator.value()
                if self.get_item_path(item) in exp_set:
                    item.setExpanded(True)
                iterator += 1
                
        # 2. Restore scroll position (Scroll target item to top)
        if top_item_path:
            target_item = self._find_item_by_path(top_item_path)
            if target_item:
                self.tree.scrollToItem(target_item, QAbstractItemView.ScrollHint.PositionAtTop)

    def _format_duration(self, seconds):
        """Converts seconds into MM:SS string."""
        if seconds is None:
            return "00:00"
        secs = int(seconds)
        mins = secs // 60
        secs %= 60
        return f"{mins:02d}:{secs:02d}"

    def track_sort_key(self, song):
        """Helper function to safely extract a sortable integer from a track number tag."""
        try:
            # Get the track number string from ext_1, default to '0'
            track_str = str(getattr(song, 'ext_1', '0') or '0')
            # Handle cases like '7/12' by taking the part before the '/'
            track_part = track_str.split('/')[0]
            # Try to convert to an integer
            return int(track_part)
        except (ValueError, TypeError):
            # If conversion fails (e.g., for 'A1'), return 0.
            # This will group all non-numeric tracks at the beginning.
            return 0

    # ------------------------
    # Tree population
    # ------------------------
    def populate_tree(self, expanded_paths=None):
        if self._is_populating:
            return
        self._is_populating = True
        self._tree_state_to_restore = expanded_paths
        self.tree.clear()
        self.tree.setHeaderLabels(["Title", "Artist", "Track #", "Length", "Rating", "Year", "Comment"])
        
        # SOVEREIGN: We only populate with 'Present' songs, but history is kept
        self.population_thread = TreePopulationThread(self.music_path)
        self.population_thread.finished.connect(self._on_tree_population_finished)
        self.population_thread.start()

    def _on_tree_population_finished(self, hierarchy):
        # Disable updates and sorting during bulk population for speed
        self.tree.setUpdatesEnabled(False)
        self.tree.setSortingEnabled(False)
        
        try:
            for genre, artists in sorted(hierarchy.items()):
                g_item = CustomTreeWidgetItem(self.tree, [genre])
                g_item.setFirstColumnSpanned(True)
                g_item.setForeground(0, self._COLOR_AMBER_GOLD)
                g_item.setData(0, Qt.ItemDataRole.UserRole, {'type': 'genre'})
                
                for artist, albums in sorted(artists.items()):
                    ar_item = CustomTreeWidgetItem(g_item, [artist])
                    ar_item.setFirstColumnSpanned(True)
                    ar_item.setForeground(0, self._COLOR_DIM_BLUE)
                    ar_item.setData(0, Qt.ItemDataRole.UserRole, {'type': 'artist'})
                    # Keep artist level collapsed by default
                    ar_item.setExpanded(False)
                    
                    for album, songs in sorted(albums.items()):
                        al_item = CustomTreeWidgetItem(ar_item, [album])
                        al_item.setFirstColumnSpanned(True)
                        al_item.setForeground(0, self._COLOR_DIM_VIOLET)
                        al_item.setData(0, Qt.ItemDataRole.UserRole, {'type': 'album'})
                        # Automatically expand album level so tracks are visible when artist is opened
                        al_item.setExpanded(True)
                        
                        # Sort songs within album once
                        sorted_songs = sorted(songs, key=self.track_sort_key)
                        
                        for i, s in enumerate(sorted_songs):
                            # Process events less frequently (every 500 tracks) to reduce overhead
                            if i % 500 == 0:
                                QApplication.processEvents()
                                
                            filename = os.path.basename(s.file_path)
                            t_item = CustomTreeWidgetItem(al_item, [
                                getattr(s, 'title', '') or filename,
                                getattr(s, 'artist', ''),
                                str(getattr(s, 'ext_1', '') or ''),
                                self._format_duration(getattr(s, 'duration', 0.0)),
                                str(getattr(s, 'rating', '0.0')),
                                str(getattr(s, 'year', '') or ''),
                                getattr(s, 'comment', '') or ''
                            ])
                            t_item.setData(0, Qt.ItemDataRole.UserRole, {'path': str(s.file_path), 'type': 'track'})
                            t_item.setForeground(0, self._COLOR_OFF_WHITE)
            
            # Restore state if requested
            if self._tree_state_to_restore:
                self.restore_tree_state(self._tree_state_to_restore)
                self._tree_state_to_restore = None

        finally:
            # Re-enable updates and sorting
            self.tree.setUpdatesEnabled(True)
            self.tree.setSortingEnabled(True)
            # Force A-Z sorting on the Genre/Title column (column 0)
            self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
            self._is_populating = False

    def _update_hierarchy_item_color(self, item):
        """
        Dynamically updates the text color of a hierarchy item based on its type and expanded state.
        """
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        item_type = item_data.get('type') if item_data else None

        if item_type == 'track':
            # Tracks always remain off-white, no dynamic change here
            return

        if item.isExpanded():
            if item_type == 'genre':
                item.setForeground(0, self._COLOR_GREEN)
            elif item_type == 'artist':
                item.setForeground(0, self._COLOR_BLUE)
            elif item_type == 'album':
                item.setForeground(0, self._COLOR_VIOLET)
        else:
            # Collapsed items revert to their respective "dim" colors
            if item_type == 'genre':
                item.setForeground(0, self._COLOR_AMBER_GOLD)
            elif item_type == 'artist':
                item.setForeground(0, self._COLOR_DIM_BLUE)
            elif item_type == 'album':
                item.setForeground(0, self._COLOR_DIM_VIOLET)

    

    # ------------------------
    # Tree interactions
    # ------------------------
    def on_tree_item_clicked(self, item, col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data.get('type') == 'track':
            self.load_track_info(data.get('path'))

    def _find_item_by_path(self, path_tuple):
        """Iterates through the tree to find an item matching a hierarchy path tuple."""
        if not path_tuple:
            return None
        # Convert path_tuple to tuple if it came from JSON as a list
        path_tuple = tuple(path_tuple)
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if self.get_item_path(item) == path_tuple:
                return item
            iterator += 1
        return None

    def _find_track_item_by_path(self, file_path):
        """Iterates through the tree to find the track item matching a file path."""
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            item_data = item.data(0, Qt.ItemDataRole.UserRole)
            if item_data and item_data.get('type') == 'track' and item_data.get('path') == file_path:
                return item
            iterator += 1
        return None

    def on_rating_changed(self, path, new_rating):
        """Slot to handle in-place update of a track's rating."""
        item = self._find_track_item_by_path(path)
        if item:
            # Column 4 is "Rating" based on ["Title", "Artist", "Track #", "Length", "Rating", "Year", "Comment"]
            item.setText(4, str(new_rating))
            self._mark_snapshot_dirty()
        # folders just expand/collapse on double click (default behavior)
    
    # app.py: Inside the MP3Player class

    def load_track_info(self, rel_path):
        """Load tags, album art, and rating for any track"""
        # Fix: QPixmap and Qt must be imported here to be available in the 'else' block and for scaling
        from PyQt6.QtGui import QPixmap 
        from PyQt6.QtCore import Qt 
        
        if not rel_path:
            return
            
        abs_path = os.path.join(self.music_path, rel_path)
        self.current_mp3_path = rel_path
        
        # Call MetadataManager to get tags and art data
        tags, art_data = MetadataManager.load_tags_and_art(abs_path)

        # Tags (Update the QLineEdit widgets)
        for tag, widget in self.tag_fields.items():
            widget.setText(tags.get(tag, ""))

        # Album Art
        if art_data:
            pixmap = QPixmap()
            pixmap.loadFromData(art_data)
            self.album_art_label.setPixmap(
                pixmap.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            # This handles the case where no album art is found
            self.album_art_label.setText("No Album Art")
            self.album_art_label.setPixmap(QPixmap())
        
        # Rating 
        if hasattr(self, "rating_widget"):
            self.rating_widget.load_rating(abs_path, rel_path=rel_path)
    def on_tree_item_double_clicked(self, item, col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data.get('type') == 'track':
            rel_path = data.get('path')
            abs_path = os.path.join(self.music_path, rel_path)
            
            if self.autoplay_checkbox.isChecked():
                # Single File Player mode: play directly without adding to playlist
                # 1. Clear current index symbol from playlist
                self.current_index = -1
                self.update_playlist_ui()
                
                # 2. Play the file
                title = data.get('title') or os.path.basename(rel_path)
                self.now_playing_label.setText(f"Playing: {title}")
                self._marquee_text = f"Playing: {title}"
                self._marquee_offset = 0

                # SOVEREIGN: Record session
                self._record_current_session()
                self._current_session_path = rel_path
                self._current_session_max_pos = 0
                self._play_counted = False

                self.player.setSource(QUrl.fromLocalFile(abs_path))
                self.player.play()
                
                # Load metadata info
                self.load_track_info(rel_path)
            else:
                # Normal mode: Add to playlist
                # Retrieve the full song object to get the correct title
                song = DatabaseManager.get_song_by_path(rel_path)
                title = getattr(song, 'title', None) or os.path.basename(rel_path) # Use filename as fallback

                self.add_to_playlist(rel_path, title)

    def show_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
            
        data = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu()
        
        if data and data.get('type') == 'track':
            path = data.get('path')
            
            queue_next_act = QAction("Queue Next", self)
            queue_next_act.triggered.connect(lambda: self.queue_next_from_tree(item))
            menu.addAction(queue_next_act)
            
            refresh_act = QAction("Refresh Metadata", self)
            refresh_act.triggered.connect(lambda: self.refresh_metadata(item))
            menu.addAction(refresh_act)
            
            open_loc_act = QAction("Open File Location", self)
            open_loc_act.triggered.connect(lambda: self.open_file_location(path))
            menu.addAction(open_loc_act)
            
            copy_tags_act = QAction("Copy Tags to Clipboard", self)
            copy_tags_act.triggered.connect(lambda: self.copy_tags_to_clipboard(path))
            menu.addAction(copy_tags_act)
            
        elif data:
            label = "Add All"
            node_type = data.get('type')
            if node_type == 'album': label = "Add Album"
            elif node_type == 'artist': label = "Add Artist"
            elif node_type == 'genre': label = "Add Genre"
            
            add_all_act = QAction(label, self)
            add_all_act.triggered.connect(lambda: self.recursive_add_to_playlist(item))
            menu.addAction(add_all_act)
            
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def queue_next_from_tree(self, item):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get('type') != 'track':
            return
        path = data.get('path')
        song = DatabaseManager.get_song_by_path(path)
        
        if not song:
            title = data.get('title') or os.path.basename(path)
            artist = duration = track = comment = genre = year = ""
        else:
            title = song.title or os.path.basename(path)
            artist = song.artist or ""
            duration = song.length_display or ""
            track = str(song.ext_1 or "")
            comment = song.comment or ""
            genre = song.genre or ""
            year = str(song.year or "")

        insert_idx = self.current_index + 1
        itm = QTreeWidgetItem([title, artist, duration, track, comment, genre, year])
        itm.setData(0, Qt.ItemDataRole.UserRole, str(path))
        self.playlist_widget.insertTopLevelItem(insert_idx, itm)
        self.playlist_queue.insert(insert_idx, {'path': str(path), 'title': title})
        
        if self.current_index == -1 and len(self.playlist_queue) == 1:
            self.play_index(0)
        self.update_playlist_ui()

    def recursive_add_to_playlist(self, parent_item):
        def _add_recursive(item):
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get('type') == 'track':
                path = data.get('path')
                song = DatabaseManager.get_song_by_path(path)
                title = getattr(song, 'title', None) or os.path.basename(path)
                self.add_to_playlist(str(path), title)
            for i in range(item.childCount()):
                _add_recursive(item.child(i))
        _add_recursive(parent_item)

    def refresh_metadata(self, item):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get('type') != 'track':
            return
        rel_path = data.get('path')
        abs_path = os.path.join(self.music_path, rel_path)
        if hasattr(self, 'scanner_thread') and self.scanner_thread.isRunning():
            QMessageBox.information(self, "Scanner Busy", "Cannot refresh metadata while a scan is in progress.")
            return
            
        # Re-read metadata
        tags, art_data = MetadataManager.load_tags_and_art(abs_path)
        # Update DB
        song = DatabaseManager.get_song_by_path(rel_path)
        if song:
            song.title = tags.get('title', song.title)
            song.artist = tags.get('artist', song.artist)
            song.album = tags.get('album', song.album)
            song.ext_1 = tags.get('tracknumber', song.ext_1)
            DatabaseManager.add_song(song)
            
            # Update tree item
            item.setText(0, song.title or os.path.basename(path))
            item.setText(1, song.artist or "")
            item.setText(2, str(song.ext_1 or ""))
            item.setText(3, song.length_display)
            item.setText(4, str(song.rating))
            item.setText(5, str(song.year or ""))
            item.setText(6, song.comment or "")
        
        if self.current_mp3_path == str(path):
            self.load_track_info(str(path))
            
    def open_file_location(self, rel_path):
        if not rel_path: return
        abs_path = os.path.join(self.music_path, rel_path)
        folder = os.path.dirname(abs_path)
        if os.path.exists(folder):
            # Use xdg-open for Linux portability
            subprocess.run(["xdg-open", folder])

    def copy_tags_to_clipboard(self, rel_path):
        if not rel_path: return
        abs_path = os.path.join(self.music_path, rel_path)
        tags, _ = MetadataManager.load_tags_and_art(abs_path)
        if tags:
            tag_text = "\n".join([f"{k.capitalize()}: {v}" for k, v in tags.items() if v])
            QApplication.clipboard().setText(tag_text)

    def show_playlist_context_menu(self, pos):
        selected_items = self.playlist_widget.selectedItems()
        if not selected_items:
            return
        menu = QMenu()
        
        remove_act = QAction("Remove Selected", self)
        remove_act.triggered.connect(self.remove_selected_from_playlist)
        menu.addAction(remove_act)
        
        if len(selected_items) == 1:
            item = selected_items[0]
            path = item.data(0, Qt.ItemDataRole.UserRole)
            row = self.playlist_widget.indexOfTopLevelItem(item)
            
            if row != self.current_index + 1:
                move_next_act = QAction("Queue Next", self)
                move_next_act.triggered.connect(lambda: self.move_to_queue_next(item))
                menu.addAction(move_next_act)
            
            jump_act = QAction("Jump to Library", self)
            jump_act.triggered.connect(lambda: self.jump_to_library(path))
            menu.addAction(jump_act)
            
            open_loc_act = QAction("Open File Location", self)
            open_loc_act.triggered.connect(lambda: self.open_file_location(path))
            menu.addAction(open_loc_act)
            
            copy_tags_act = QAction("Copy Tags to Clipboard", self)
            copy_tags_act.triggered.connect(lambda: self.copy_tags_to_clipboard(path))
            menu.addAction(copy_tags_act)

            menu.addSeparator()
            
            move_top_act = QAction("Move to Top", self)
            move_top_act.triggered.connect(lambda: self.move_to_top(item))
            menu.addAction(move_top_act)
            
            move_bottom_act = QAction("Move to Bottom", self)
            move_bottom_act.triggered.connect(lambda: self.move_to_bottom(item))
            menu.addAction(move_bottom_act)

        menu.addSeparator()
        
        shuffle_all_act = QAction("Full Shuffle Playlist", self)
        shuffle_all_act.triggered.connect(self.shuffle_playlist)
        menu.addAction(shuffle_all_act)
        
        shuffle_rem_act = QAction("Randomize Remaining", self)
        shuffle_rem_act.triggered.connect(self.shuffle_remaining)
        menu.addAction(shuffle_rem_act)
        
        remove_played_act = QAction("Remove Already Played", self)
        remove_played_act.triggered.connect(self.remove_played_tracks)
        menu.addAction(remove_played_act)

        menu.exec(self.playlist_widget.viewport().mapToGlobal(pos))

    def remove_selected_from_playlist(self):
        selected_items = self.playlist_widget.selectedItems()
        if not selected_items: return
        indices = sorted([self.playlist_widget.indexOfTopLevelItem(it) for it in selected_items], reverse=True)
        for idx in indices:
            if idx == self.current_index:
                self.current_index = -1
                self.player.stop()
                self.now_playing_label.setText("Not playing")
            elif idx < self.current_index:
                self.current_index -= 1
            self.playlist_widget.takeTopLevelItem(idx)
            if 0 <= idx < len(self.playlist_queue):
                self.playlist_queue.pop(idx)
        self.update_playlist_ui()

    def move_to_queue_next(self, item):
        old_idx = self.playlist_widget.indexOfTopLevelItem(item)
        new_idx = self.current_index + 1
        if old_idx == new_idx or new_idx >= self.playlist_widget.topLevelItemCount(): return
        
        entry = self.playlist_queue.pop(old_idx)
        self.playlist_queue.insert(new_idx, entry)
        it = self.playlist_widget.takeTopLevelItem(old_idx)
        self.playlist_widget.insertTopLevelItem(new_idx, it)
        
        # Re-sync current_index
        cur_path = self.player.source().toLocalFile()
        if cur_path:
            for i, e in enumerate(self.playlist_queue):
                if e['path'] == cur_path:
                    self.current_index = i
                    break
        self.update_playlist_ui()

    def jump_to_library(self, path):
        item = self._find_track_item_by_path(path)
        if item:
            self.tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtTop)
            self.tree.setCurrentItem(item)

    def move_to_top(self, item):
        old_idx = self.playlist_widget.indexOfTopLevelItem(item)
        if old_idx == 0: return
        entry = self.playlist_queue.pop(old_idx)
        self.playlist_queue.insert(0, entry)
        it = self.playlist_widget.takeTopLevelItem(old_idx)
        self.playlist_widget.insertTopLevelItem(0, it)
        # Re-sync current_index
        cur_path = self.player.source().toLocalFile()
        if cur_path:
            for i, e in enumerate(self.playlist_queue):
                if e['path'] == cur_path:
                    self.current_index = i
                    break
        self.update_playlist_ui()

    def move_to_bottom(self, item):
        old_idx = self.playlist_widget.indexOfTopLevelItem(item)
        last_idx = self.playlist_widget.topLevelItemCount() - 1
        if old_idx == last_idx: return
        entry = self.playlist_queue.pop(old_idx)
        self.playlist_queue.append(entry)
        it = self.playlist_widget.takeTopLevelItem(old_idx)
        self.playlist_widget.addTopLevelItem(it)
        # Re-sync current_index
        cur_path = self.player.source().toLocalFile()
        if cur_path:
            for i, e in enumerate(self.playlist_queue):
                if e['path'] == cur_path:
                    self.current_index = i
                    break
        self.update_playlist_ui()

    def shuffle_playlist(self):
        random.shuffle(self.playlist_queue)
        self.current_index = -1
        # Find new current_index
        cur_path = self.player.source().toLocalFile()
        if cur_path:
            for i, e in enumerate(self.playlist_queue):
                if e['path'] == cur_path:
                    self.current_index = i
                    break
        self._rebuild_playlist_widget()

    def shuffle_remaining(self):
        if self.current_index + 1 < len(self.playlist_queue):
            remaining = self.playlist_queue[self.current_index+1:]
            random.shuffle(remaining)
            self.playlist_queue[self.current_index+1:] = remaining
            self._rebuild_playlist_widget()

    def remove_played_tracks(self):
        if self.current_index <= 0: return
        # Remove tracks from 0 to current_index - 1
        for _ in range(self.current_index):
            self.playlist_queue.pop(0)
            self.playlist_widget.takeTopLevelItem(0)
        self.current_index = 0
        self.update_playlist_ui()

    def _rebuild_playlist_widget(self):
        self.playlist_widget.clear()
        for entry in self.playlist_queue:
            path = entry['path']
            song = DatabaseManager.get_song_by_path(path)
            if not song:
                title = entry['title']
                artist = duration = track = comment = genre = year = ""
            else:
                title = song.title or entry['title']
                artist = song.artist or ""
                duration = song.length_display or ""
                track = str(song.ext_1 or "")
                comment = song.comment or ""
                genre = song.genre or ""
                year = str(song.year or "")

            itm = QTreeWidgetItem([title, artist, duration, track, comment, genre, year])
            itm.setData(0, Qt.ItemDataRole.UserRole, path)
            self.playlist_widget.addTopLevelItem(itm)
        self.update_playlist_ui()


    # ------------------------
    # Playlist handling
    # ------------------------
    def add_to_playlist(self, fullpath, title=None):
        song = DatabaseManager.get_song_by_path(fullpath)
        if not song:
            title = title or os.path.basename(fullpath)
            artist = duration = track = comment = genre = year = ""
        else:
            title = song.title or os.path.basename(fullpath)
            artist = song.artist or ""
            duration = song.length_display or ""
            track = str(song.ext_1 or "")
            comment = song.comment or ""
            genre = song.genre or ""
            year = str(song.year or "")

        itm = QTreeWidgetItem([title, artist, duration, track, comment, genre, year])
        itm.setData(0, Qt.ItemDataRole.UserRole, fullpath)
        self.playlist_widget.addTopLevelItem(itm)
        
        self.playlist_queue.append({'path': fullpath, 'title': title})
        # if first item, start playback
        if len(self.playlist_queue) == 1:
            self.play_index(0)

    def on_playlist_item_double_clicked(self, item):
        idx = self.playlist_widget.indexOfTopLevelItem(item)
        self.play_index(idx)
        # load tags, album art, rating for selected track
        self.load_track_info(item.data(0, Qt.ItemDataRole.UserRole))
        
    def on_playlist_item_clicked(self, item):
        """Load tag info when a playlist item is single-clicked."""
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.load_track_info(path)

    def on_playlist_rows_moved(self, parent, start, end, destination, row):
        # Store currently playing track path
        curpath = None
        if 0 <= self.current_index < len(self.playlist_queue):
            curpath = self.playlist_queue[self.current_index]['path']

        # Rebuild queue from widget items
        new_queue = []
        for i in range(self.playlist_widget.topLevelItemCount()):
            it = self.playlist_widget.topLevelItem(i)
            path = it.data(0, Qt.ItemDataRole.UserRole)
            text = it.text(0)
            # Strip symbol if present
            if text.startswith("▶ "):
                text = text[2:]
            new_queue.append({'path': path, 'title': text})

        self.playlist_queue = new_queue

        # Update current_index to match the path
        self.current_index = -1
        if curpath:
            for i, e in enumerate(self.playlist_queue):
                if e['path'] == curpath:
                    self.current_index = i
                    break

        self.update_playlist_ui()

    def update_playlist_ui(self):
        # visually mark current track
        for i in range(self.playlist_widget.topLevelItemCount()):
            it = self.playlist_widget.topLevelItem(i)
            if i >= len(self.playlist_queue): 
                continue
                
            text = self.playlist_queue[i]['title']
            if i == self.current_index:
                text = f"▶ {text}"
                # Always load tag info for this track
                self.load_track_info(self.playlist_queue[i]['path'])
                for col in range(self.playlist_widget.columnCount()):
                    it.setBackground(col, QColor(0, 120, 215, 150)) # Highlight color
                    font = it.font(col)
                    font.setBold(True)
                    it.setFont(col, font)
            else:
                for col in range(self.playlist_widget.columnCount()):
                    it.setData(col, Qt.ItemDataRole.BackgroundRole, None)
                    font = it.font(col)
                    font.setBold(False)
                    it.setFont(col, font)
            it.setText(0, text)

    # ------------------------
    # Playback controls
    # ------------------------
    def play_index(self, idx):
        if idx < 0 or idx >= len(self.playlist_queue):
            return
            
        # Record the session of the song that is currently ending
        self._record_current_session()

        entry = self.playlist_queue[idx]
        self.current_index = idx
        path = entry['path']
        self.now_playing_label.setText(f"Playing: {entry['title']}")
        self._marquee_text = f"Playing: {entry['title']}"
        self._marquee_offset = 0
        self._play_counted = False # Reset for the new track
        
        # Start new session tracking
        self._current_session_path = path
        self._current_session_max_pos = 0
        self._current_session_accumulated_ms = 0
        self._current_session_last_pos = 0
        
        abs_path = os.path.join(self.music_path, path)
        self.player.setSource(QUrl.fromLocalFile(abs_path))
        self.player.play()
        self.update_playlist_ui()

    def _record_current_session(self):
        """Writes the current play session details to the database play_log."""
        if not self._current_session_path:
            return

        duration_ms = self.player.duration()
        if duration_ms <= 0:
            return

        # SOVEREIGN: Use honest 'time resided' for metrics
        played_secs = self._current_session_accumulated_ms / 1000.0
        total_secs = duration_ms / 1000.0
        
        # Dual-Check for 'Full Play':
        # 1. Did they reach the 90% mark (max_pos)?
        # 2. Did they actually listen to at least 50% of the song (seek-proof)?
        was_fully_played = (
            (self._current_session_max_pos / duration_ms) >= 0.90 and
            (self._current_session_accumulated_ms / duration_ms) >= 0.50
        )
        
        # Log to detailed play_log
        DatabaseManager.log_play_event(
            self._current_session_path,
            played_secs,
            total_secs,
            was_fully_played
        )
        
        # Clean up session state
        self._current_session_path = None
        self._current_session_max_pos = 0
        self._current_session_accumulated_ms = 0
        self._current_session_last_pos = 0

    def on_play_clicked(self):
        state = self.player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            # if nothing loaded but playlist exists, play first
            if self.player.source().isEmpty() and self.playlist_queue:
                self.play_index(0)
            else:
                self.player.play()

    def on_pause_clicked(self):
        self.player.pause()

    def on_stop_clicked(self):
        self.player.stop()

    def on_prev_clicked(self):
        if self.current_index > 0:
            self.play_index(self.current_index - 1)

    def on_next_clicked(self):
        if self.current_index + 1 < len(self.playlist_queue):
            self.play_index(self.current_index + 1)

    # detect end of media and advance
    def on_media_status_changed(self, status):
        try:
            if status == QMediaPlayer.MediaStatus.EndOfMedia:
                # small delay then next
                QTimer.singleShot(50, lambda: self.play_index(self.current_index + 1))
        except Exception:
            pass

    def on_position_changed(self, pos):
        # pos in ms
        duration = self.player.duration()
        if not self._seeking and duration > 0:
            ratio = pos / duration
            self.progress_slider.setValue(int(ratio * 1000))
            
            # SOVEREIGN: Seek-Proof Accumulation
            delta = pos - self._current_session_last_pos
            if 0 < delta < 2000: # Only count normal playback, ignore seeks/jumps
                self._current_session_accumulated_ms += delta
            self._current_session_last_pos = pos

            # Update furthest point reached for history metrics
            if pos > self._current_session_max_pos:
                self._current_session_max_pos = pos

            # Play-count metric logic: Trigger at 30%
            if not self._play_counted and ratio >= 0.30:
                self._play_counted = True
                path = self.player.source().toLocalFile()
                if path:
                    # SOVEREIGN: Convert back to relative path for DB lookup
                    try:
                        rel_path = os.path.relpath(path, self.music_path)
                        DatabaseManager.increment_play_count(rel_path)
                        print(f"Metric: Play count incremented for {rel_path}")
                    except ValueError:
                        # Fallback if path isn't under music_path for some reason
                        DatabaseManager.increment_play_count(path)

        # update time label
        cur = int(pos / 1000)
        total = int(duration / 1000) if duration > 0 else 0
        self.current_time_label.setText(f"{cur//60:02d}:{cur%60:02d}")
        self.total_time_label.setText(f"{total//60:02d}:{total%60:02d}")
    
    def _scroll_now_playing(self):
        text = self._marquee_text
        label_width = self.now_playing_label.width()
        fm = self.now_playing_label.fontMetrics()
        text_width = fm.horizontalAdvance(text)

        if text_width <= label_width:
            self.now_playing_label.setText(text)
            self._marquee_offset = 0
            return

        # Shift by characters for smoothness
        # But do multiple timer ticks for smooth effect
        visible_chars = len(text)
        offset = self._marquee_offset % len(text)
        display_text = text[offset:] + "   " + text[:offset]
        self.now_playing_label.setText(display_text)

        # Increment offset slowly for smooth effect
        self._marquee_offset += 1

       
    def on_duration_changed(self, dur):
        # adjust slider (we map to 0..1000)
        if dur > 0:
            self.progress_slider.setEnabled(True)
        else:
            self.progress_slider.setEnabled(False)
    def on_playback_state_changed(self, state):
        style = self.style()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            # switch to pause icon
            self.play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self.play_btn.setToolTip("Pause")
            # Start visualizer if visible
            if self.visualizer_widget.isVisible():
                self.visualizer_widget.start()
        else:
            # switch to play icon
            self.play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.play_btn.setToolTip("Play")
            # Stop visualizer
            self.visualizer_widget.stop()

    def on_seek_pressed(self):
        self._seeking = True

    def on_seek_released(self):
        self._seeking = False
        if self.player.duration() > 0:
            val = self.progress_slider.value()
            newpos = int((val / 1000.0) * self.player.duration())
            self.player.setPosition(newpos)

    # ------------------------
    # Library folder selection
    # ------------------------
    def change_library_folder(self):
        old_music_path = self.music_path
        
        selected_folder = QFileDialog.getExistingDirectory(self, "Choose music folder", self.music_path)
        
        # Check if a folder was actually selected (not cancelled)
        if selected_folder:
            # If the selected folder is different from the current one
            if selected_folder != old_music_path:
                self.music_path = selected_folder
                self.cfg['music_path'] = self.music_path
                save_config(self.cfg)
                # A new folder was chosen, so trigger a full scan.
                # The scan's finish handler will call populate_tree.
                self.start_scan(background=True)
            else:
                # Same folder was selected, or user confirmed current folder.
                # Just refresh the view from the current DB. No scan needed.
                self.populate_tree()
        else: # User clicked cancel or closed the dialog
            # The user didn't choose anything, but still wanted a refresh of the current DB state.
            self.populate_tree()

    def toggle_views(self):
        # Swap between library (0) and playlist (1)
        current_index = self.left_stacked.currentIndex()
        self.left_stacked.setCurrentIndex(1 - current_index) 

    def closeEvent(self, event):
        """
        Overrides the close event to stop playback and ensure any running background threads are stopped.
        """
        # Record final session if still playing
        self._record_current_session()
        
        self.player.stop() # Stop any currently playing audio
        
        # Save tree expansion state and scroll position before closing
        tree_state = self.save_tree_state()
        self.cfg['tree_state'] = tree_state
        
        # Save column widths
        self.cfg['library_column_widths'] = [self.tree.columnWidth(i) for i in range(self.tree.columnCount())]
        self.cfg['playlist_column_widths'] = [self.playlist_widget.columnWidth(i) for i in range(self.playlist_widget.columnCount())]
        
        save_config(self.cfg)

        # Stop background threads
        if self.scanner_thread and self.scanner_thread.isRunning():
            self.scanner_thread.stop()
            self.scanner_thread.wait()
        
        if self.fixer_thread and self.fixer_thread.isRunning():
            self.fixer_thread.wait() # Fixers are usually fast enough to wait
            
        if self.year_fixer_thread and self.year_fixer_thread.isRunning():
            self.year_fixer_thread.wait()

        self.update_library_snapshot() # This will check if dirty and save if needed
        event.accept()

    def save_tags(self):
        if not self.current_mp3_path:
            QMessageBox.warning(self, "No MP3 Selected", "Please select an MP3 file to save tags.")
            return

        # --- Step 1: Get old and new tag data ---
        # Get old song data from DB to check for hierarchy changes
        old_song = DatabaseManager.get_song_by_path(self.current_mp3_path)
        if not old_song:
            QMessageBox.critical(self, "Error", "Could not find the song in the database to compare.")
            return
            
        # Get new data from the form fields
        new_tag_data = {tag: widget.text() for tag, widget in self.tag_fields.items()}

        # --- Step 2: Save the tags to the file and database ---
        rel_path = self.current_mp3_path
        abs_path = os.path.join(self.music_path, rel_path)
        
        if not MetadataManager.save_tags(abs_path, new_tag_data.copy(), rel_path=rel_path):
            QMessageBox.critical(self, "Error Saving Tags", f"Failed to save tags for {Path(rel_path).name}.")
            return
        
        QMessageBox.information(self, "Tags Saved", f"Tags for {Path(rel_path).name} saved successfully.")
        self._mark_snapshot_dirty()

        # --- Step 3: Decide how to update the UI ---
        hierarchy_changed = (
            old_song.genre != new_tag_data.get('genre') or
            old_song.artist != new_tag_data.get('artist') or
            old_song.album != new_tag_data.get('album')
        )

        if hierarchy_changed:
            # --- Complex Update: Hierarchy has changed ---
            print("Hierarchy changed, performing full refresh with state restoration.")
            tree_state = self.save_tree_state()
            self.populate_tree(tree_state)
        else:
            # --- Simple Update: In-place text change ---
            print("Performing in-place update.")
            item = self._find_track_item_by_path(self.current_mp3_path)
            if item:
                # Column mapping: ["Title", "Artist", "Track #", "Length", "Rating", "Year", "Comment"]
                item.setText(0, new_tag_data.get('title', ''))
                item.setText(1, new_tag_data.get('artist', ''))
                item.setText(2, new_tag_data.get('tracknumber', ''))
                # 'Length' doesn't change with tags, so we don't update it
                # 'Rating' is handled separately
                # 'Year' and 'Comment' are not in the default tag_fields, but if they were, they'd be updated here.
    
# ------------------------
# Main
# ------------------------


def main():
    # Allow Ctrl+C to stop the application gracefully
    signal.signal(signal.SIGINT, signal.SIG_DFL) 
    
    # Suppress verbose multimedia/decoder warnings
    os.environ["QT_LOGGING_RULES"] = "qt.multimedia.*=false;*.warning=false"
    
    app = QApplication(sys.argv)
    app.setApplicationName("MP3 Vibe Player")
    app.setWindowIcon(QIcon('image/mp3.png'))
    win = MP3Player()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
