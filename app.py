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
from models import CacheManager
from functools import partial
from PyQt6.QtWidgets import (
    QApplication, QWidget, QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QSlider, QHBoxLayout, QVBoxLayout, QFileDialog, QMessageBox,
    QSplitter, QSizePolicy, QFrame, QStyle, QStackedWidget, QFormLayout, QLineEdit, QAbstractItemView,)
import signal # Add this import near the top of your file (if it's not already there)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QIcon, QFont, QPixmap, QImage, QCursor
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtGui import QIcon
from config import load_config, save_config
from metadata import ScannerThread, MetadataManager, LIB_CACHE, PROJECT_DIR
# app.py: Add these lines near the top (after imports)
from pathlib import Path
DEFAULT_MUSIC_PATH = str(Path.home() / "Music")
# ------------------------
# Background scanner thread
# ------------------------

class YinYangRatingWidget(QWidget):
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
            if path and not MetadataManager.save_rating(path, self.current_rating):
                # If save fails, revert the icons and show a message
                self.current_rating = MetadataManager.load_rating(path) 
                self._update_icons()
                QMessageBox.warning(self, "Error", "Failed to save rating. Check console for details.")
        
        return handler
    #comments too
# ------------------------
# Utility functions
# ------------------------


class ClickableSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # calculate click ratio
            value = event.position().x() / self.width()  # 0.0 to 1.0
            new_val = int(value * (self.maximum() - self.minimum()) + self.minimum())
            self.setValue(new_val)
            self.sliderReleased.emit()  # trigger existing handler
        super().mousePressEvent(event)
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

        # Media player
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.player.playbackStateChanged.connect(self.on_playback_state_changed)

        # UI pieces
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self.on_tree_item_double_clicked)
        self.tree.itemClicked.connect(self.on_tree_item_clicked)
        
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

        for label, widget in self.tag_fields.items():
            self.tag_editor_layout.addRow(label.capitalize(), widget)

        # Album Art and Rating (display only for now)
        self.album_art_label = QLabel("No Album Art")
        self.album_art_label.setFixedSize(150, 150) # Placeholder size
        self.album_art_label.setStyleSheet("border: 1px solid gray")
        self.tag_editor_layout.addRow("Album Art", self.album_art_label)

        # Replace rating label with interactive rating widget
        self.rating_widget = YinYangRatingWidget()
        self.tag_editor_layout.addRow("Rating", self.rating_widget)

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

        # load cached library or scan
        cached = CacheManager.load_library_cache()
        if cached:
            self.library_tree = cached
            self.populate_tree()
            self.rescan_btn.setEnabled(True)
            self.now_playing_label.setText("Ready")
            
            # Start a background scan (non-blocking) to find new files
            self.start_scan(background=True)
        else:
            # If no cache exists, initialize library_tree as empty and start a foreground scan
            self.library_tree = {}
            self.start_scan(background=False)

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

        # Right: Total time label
        self.total_time_label = QLabel("00:00")
        self.total_time_label.setFixedWidth(60)
        self.total_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        control_row.addWidget(self.total_time_label)

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
        self.library_label = QLabel("Library:")
        lib_controls_row.insertWidget(0, self.library_label)
        lib_controls_row.addWidget(self.rescan_btn)
        lib_controls_row.addWidget(self.folder_btn)
        lib_controls_row.addWidget(self.toggle_view_btn)
        lib_controls_row.addStretch(1)  # keep buttons left-aligned
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

    def on_scan_finished(self, tree):
        self.library_tree = tree
        CacheManager.save_library_cache(tree)
        self.populate_tree()
        self.rescan_btn.setEnabled(True)
        self.now_playing_label.setText("Ready")

    # ------------------------
    # Tree population
    # ------------------------
    def populate_tree(self):
        self.tree.clear()
        # recursively add items
        def add_node(parent, node_dict, path_prefix=""):
            if isinstance(node_dict, list):
                # Node itself is a list → create items for each file
                for t in sorted(node_dict):
                    display = t
                    fullpath = os.path.join(self.music_path, t)
                    leaf = QTreeWidgetItem(parent, [display])
                    leaf.setData(0, Qt.ItemDataRole.UserRole, {'type': 'track', 'path': fullpath, 'title': t})
                return
            

            # first, add folder children (sorted)
            for name in sorted([k for k in node_dict.keys() if k != 'Unsorted']):
                item = QTreeWidgetItem(parent, [name])
                item.setData(0, Qt.ItemDataRole.UserRole, {'type': 'folder', 'path': os.path.join(path_prefix, name)})
                add_node(item, node_dict[name], os.path.join(path_prefix, name) if path_prefix else name)

            # then, add tracks at this level
            tracks = node_dict.get('Unsorted', [])
            for t in sorted(tracks):
                display = t
                fullpath = os.path.join(self.music_path, path_prefix, t) if path_prefix else os.path.join(self.music_path, t)
                leaf = QTreeWidgetItem(parent, [display])
                leaf.setData(0, Qt.ItemDataRole.UserRole, {'type': 'track', 'path': fullpath, 'title': t})
        
        #Comment on 545 to test git 23nov25 112
        
        # top-level
        for top_key in sorted(self.library_tree.keys()):
            top_item = QTreeWidgetItem(self.tree, [top_key])
            top_item.setData(0, Qt.ItemDataRole.UserRole, {'type': 'folder', 'path': top_key})
            print(f"Top key: {top_key}, type: {type(self.library_tree[top_key])}")
            add_node(top_item, self.library_tree[top_key], top_key)
       # self.tree.expandToDepth(0)

    # ------------------------
    # Tree interactions
    # ------------------------
    def on_tree_item_clicked(self, item, col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data.get('type') == 'track':
            self.load_track_info(data.get('path'))

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
            title = data.get('title')
            self.add_to_playlist(path, title)




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
        # Grab the file path stored in the item
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            # Load tags, album art, and rating for the clicked track
            self.load_track_info(path)

    def on_playlist_item_clicked(self, item):
        """Load tag info when a playlist item is single-clicked."""
        index = self.playlist_widget.row(item)
        if 0 <= index < len(self.playlist_queue):
            self.load_track_info(self.playlist_queue[index]['path'])

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
        folder = QFileDialog.getExistingDirectory(self, "Choose music folder", self.music_path)
        if folder:
            self.music_path = folder
            self.cfg['music_path'] = self.music_path
            save_config(self.cfg)
            # clear cache and start fresh scan
            if LIB_CACHE.exists():
                try:
                    LIB_CACHE.unlink()
                except Exception:
                    pass
            self.start_scan(background=True)

    def toggle_views(self):
        # Swap between library (0) and playlist (1)
        current_index = self.left_stacked.currentIndex()
        self.left_stacked.setCurrentIndex(1 - current_index) 

    def save_tags(self):
        if not self.current_mp3_path:
            QMessageBox.warning(self, "No MP3 Selected", "Please select an MP3 file to save tags.")
            return
        
        tag_data = {tag: widget.text() for tag, widget in self.tag_fields.items()}

        if MetadataManager.save_tags(self.current_mp3_path, tag_data):
            from pathlib import Path 
            QMessageBox.information(self, "Tags Saved", f"Tags for {Path(self.current_mp3_path).name} saved successfully.")
        else:
            from pathlib import Path
            QMessageBox.critical(self, "Error Saving Tags", f"Failed to save tags for {Path(self.current_mp3_path).name}.")
    
# ------------------------
# Main
# ------------------------


def main():
    # Allow Ctrl+C to stop the application gracefully
    signal.signal(signal.SIGINT, signal.SIG_DFL) 
    
    app = QApplication(sys.argv)
    app.setApplicationName("MP3 Vibe Player")
    app.setWindowIcon(QIcon('image/mp3.png'))
    win = MP3Player()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
