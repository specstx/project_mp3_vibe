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
from functools import partial
from PyQt6.QtWidgets import (
    QApplication, QWidget, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QSlider, QHBoxLayout, QVBoxLayout, QFileDialog, QMessageBox, QCheckBox,
    QSplitter, QSizePolicy, QFrame, QStyle, QStackedWidget, QFormLayout, QLineEdit, QAbstractItemView,)
import signal
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl, QPoint
from PyQt6.QtGui import QIcon, QFont, QPixmap, QImage, QCursor, QColor
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from config import load_config, save_config
from metadata import ScannerThread, MetadataManager, PROJECT_DIR, create_library_snapshot
from database_logic import DatabaseManager
from pathlib import Path
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
    def load_rating(self, path):
        self._current_path = path
        self.current_rating = MetadataManager.load_rating(path) 
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

            path = getattr(self, "_current_path", None)
            
            # Call MetadataManager to save the new rating
            if path and MetadataManager.save_rating(path, self.current_rating):
                self.rating_saved.emit(path, self.current_rating) # Emit signal with path and new rating
            else:
                # If save fails, revert the icons and show a message
                self.current_rating = MetadataManager.load_rating(path) 
                self._update_icons()
                QMessageBox.warning(self, "Error", "Failed to save rating. Check console for details.")
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

    def __init__(self, tags_to_fix):
        super().__init__()
        self.tags_to_fix = tags_to_fix

    def run(self):
        successful = 0
        failed = 0
        for path, new_value in self.tags_to_fix:
            if MetadataManager.save_tags(path, {'tracknumber': new_value}):
                successful += 1
            else:
                failed += 1
        self.finished.emit(successful, failed)


class YearFixerThread(QThread):
    finished = pyqtSignal(int, int) # successful_fixes, failed_fixes

    def __init__(self, years_to_fix):
        super().__init__()
        self.years_to_fix = years_to_fix

    def run(self):
        successful = 0
        failed = 0
        for path, new_value in self.years_to_fix:
            if MetadataManager.save_tags(path, {'date': new_value}):
                successful += 1
            else:
                failed += 1
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

class TreePopulationThread(QThread):
    finished = pyqtSignal(dict)

    def run(self):
        # Retrieve all songs sorted by genre, artist, and album to speed up hierarchy building
        all_songs = DatabaseManager.get_all_songs_sorted()
        hierarchy = {}
        for s in all_songs:
            g, ar, al = getattr(s, 'genre', None) or "Unknown", getattr(s, 'artist', None) or "Unknown", getattr(s, 'album', None) or "Unknown"
            hierarchy.setdefault(g, {}).setdefault(ar, {}).setdefault(al, []).append(s)
        self.finished.emit(hierarchy)


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
            self.audio_output.setVolume(value / 100.0)

    def update_from_audio_output(self):
        if not self.audio_output:
            return
            
        # Update slider position
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(int(self.audio_output.volume() * 100))
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

# ------------------------
# Main Window
# ------------------------
class MP3Player(QWidget):
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
        
        self.playlist_widget = QListWidget()
        self.playlist_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        

        # connect model's rowsMoved to update playlist order when drag-drop reorder happens
        self.playlist_widget.model().rowsMoved.connect(self.on_playlist_rows_moved)

        # connect double-click and single-click signals
        self.playlist_widget.itemDoubleClicked.connect(self.on_playlist_item_double_clicked)
        self.playlist_widget.itemClicked.connect(self.on_playlist_item_clicked)  # 👈 ADD THIS LINE

        self.playlist_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
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

        # Stagger the initial load and scan to allow the UI to show up first
        QTimer.singleShot(100, self.initial_load_and_scan)

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
            # Step 1: Populate the tree immediately with current DB data
            print("Performing initial library load from database...")
            # Restore state if available (fallback to old expanded_paths if tree_state is missing)
            tree_state = self.cfg.get('tree_state', self.cfg.get('expanded_paths', []))
            self.populate_tree(tree_state)
            QApplication.processEvents() # Ensure UI is responsive
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
            QApplication.processEvents() # Ensure UI is responsive after initial populate
            
            # Step 2: Start the automatic background scan
            print("Starting automatic background scan to update and prune library...")
            self.start_scan(background=True)

    def build_layout(self):
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

        # Main layout
        main_l = QHBoxLayout()
        main_l.addWidget(splitter)
        self.setLayout(main_l)

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
        self.rescan_btn.setEnabled(False)
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
        self.fixer_thread = TagFixerThread(tags_to_fix)
        self.fixer_thread.finished.connect(self._on_tag_fix_finished)
        self.fixer_thread.start()

    def _on_tag_fix_finished(self, successful, failed):
        """Handles the completion of the TagFixerThread."""
        self.now_playing_label.setText("Tag fixing complete.")
        QMessageBox.information(
            self, 
            "Tag Fix Complete",
            f"Successfully fixed {successful} tags.\nFailed to fix {failed} tags."
        )
        # The database is now in sync with the file tags, but the view is not.
        # A full populate is needed to show the corrected numbers.
        self.populate_tree()
        # The files have been modified, so we need a new snapshot.
        self.update_library_snapshot(force_update=True)

    def _apply_year_fixes(self, years_to_fix):
        """Starts a background thread to apply year fixes."""
        self.now_playing_label.setText(f"Fixing {len(years_to_fix)} year tags...")
        self.year_fixer_thread = YearFixerThread(years_to_fix)
        self.year_fixer_thread.finished.connect(self._on_year_fix_finished)
        self.year_fixer_thread.start()

    def _on_year_fix_finished(self, successful, failed):
        """Handles the completion of the YearFixerThread."""
        self.now_playing_label.setText("Year tag fixing complete.")
        QMessageBox.information(
            self,
            "Year Fix Complete",
            f"Successfully fixed {successful} year tags.\nFailed to fix {failed} year tags."
        )
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
        
        self.population_thread = TreePopulationThread()
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

    def load_track_info(self, path):
        """Load tags, album art, and rating for any track"""
        # Fix: QPixmap and Qt must be imported here to be available in the 'else' block and for scaling
        from PyQt6.QtGui import QPixmap 
        from PyQt6.QtCore import Qt 
        
        if not path:
            return
        self.current_mp3_path = path
        
        # Call MetadataManager to get tags and art data
        tags, art_data = MetadataManager.load_tags_and_art(path)

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
            self.rating_widget._current_path = path
            self.rating_widget.load_rating(path)
    def on_tree_item_double_clicked(self, item, col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data.get('type') == 'track':
            path = data.get('path')
            
            # Retrieve the full song object to get the correct title
            song = DatabaseManager.get_song_by_path(path)
            title = getattr(song, 'title', None) or os.path.basename(path) # Use filename as fallback

            self.add_to_playlist(str(path), title)

            # If checkbox is checked, immediately play it like a playlist double-click
            if self.autoplay_checkbox.isChecked():
                # Reuse the existing playlist double-click handler
                # Find the last added playlist item
                last_index = self.playlist_widget.count() - 1
                if last_index >= 0:
                    item = self.playlist_widget.item(last_index)
                    self.on_playlist_item_double_clicked(item)


    # ------------------------
    # Playlist handling
    # ------------------------
    def add_to_playlist(self, fullpath, title=None):
        if not title:
            title = os.path.basename(fullpath)
        # create item
        itm = QListWidgetItem(title)
        itm.setData(Qt.ItemDataRole.UserRole, fullpath)
        self.playlist_widget.addItem(itm)
        self.playlist_queue.append({'path': fullpath, 'title': title})
        # if first item, start playback
        if len(self.playlist_queue) == 1:
            self.play_index(0)

    def on_playlist_item_double_clicked(self, item):
        idx = self.playlist_widget.row(item)
        self.play_index(idx)
        # load tags, album art, rating for selected track
        self.load_track_info(item.data(Qt.ItemDataRole.UserRole))
        
    def on_playlist_item_clicked(self, item):
        """Load tag info when a playlist item is single-clicked."""
        # Grab the file path stored in the item (for older approach)
        path = item.data(Qt.ItemDataRole.UserRole)

        # Or via playlist_queue
        index = self.playlist_widget.row(item)
        if 0 <= index < len(self.playlist_queue):
            path = self.playlist_queue[index]['path']

        if path:
            self.load_track_info(path)

    def on_playlist_rows_moved(self, parent, start, end, destination, row):
        # Store currently playing track path
        curpath = None
        if 0 <= self.current_index < len(self.playlist_queue):
            curpath = self.playlist_queue[self.current_index]['path']

        # Rebuild queue from widget items
        new_queue = []
        for i in range(self.playlist_widget.count()):
            it = self.playlist_widget.item(i)
            path = it.data(Qt.ItemDataRole.UserRole)
            text = it.text()
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
        for i in range(self.playlist_widget.count()):
            it = self.playlist_widget.item(i)
            text = self.playlist_queue[i]['title']  # always start fresh
            if i == self.current_index:
                text = f"▶ {text}"
                # Always load tag info for this track
                self.load_track_info(self.playlist_queue[i]['path'])
                it.setBackground(Qt.GlobalColor.blue)
                font = it.font()
                font.setBold(True)
                it.setFont(font)
            else:
                # Always load tag info for this track
                self.load_track_info(self.playlist_queue[i]['path'])
                it.setBackground(Qt.GlobalColor.transparent)
                font = it.font()
                font.setBold(False)
                it.setFont(font)
            it.setText(text)

    # ------------------------
    # Playback controls
    # ------------------------
    def play_index(self, idx):
        if idx < 0 or idx >= len(self.playlist_queue):
            return
        entry = self.playlist_queue[idx]
        self.current_index = idx
        path = entry['path']
        self.now_playing_label.setText(f"Playing: {entry['title']}")
        self._marquee_text = f"Playing: {entry['title']}"
        self._marquee_offset = 0
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        self.update_playlist_ui()

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
        if not self._seeking and self.player.duration() > 0:
            ratio = pos / self.player.duration()
            self.progress_slider.setValue(int(ratio * 1000))
        # update time label
        cur = int(pos / 1000)
        total = int(self.player.duration() / 1000) if self.player.duration() > 0 else 0
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
        else:
            # switch to play icon
            self.play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.play_btn.setToolTip("Play")

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
        self.player.stop() # Stop any currently playing audio
        
        # Save tree expansion state and scroll position before closing
        tree_state = self.save_tree_state()
        self.cfg['tree_state'] = tree_state
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
        if not MetadataManager.save_tags(self.current_mp3_path, new_tag_data.copy()): # Use copy as save_tags modifies it
            QMessageBox.critical(self, "Error Saving Tags", f"Failed to save tags for {Path(self.current_mp3_path).name}.")
            return
        
        QMessageBox.information(self, "Tags Saved", f"Tags for {Path(self.current_mp3_path).name} saved successfully.")
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
