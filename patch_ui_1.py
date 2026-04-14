import re

with open('mainwindow.py', 'r') as f:
    code = f.read()

# Replace the layout code for the left video side
old_video_layout = """        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        self.video_label = QLabel("Waiting for camera...")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet(
            "background-color: #11111b; border: 2px solid #45475a; "
            "border-radius: 10px; font-size: 14px; color: #585b70;"
        )
        self.video_container.addWidget(self.video_label)

        # Camera Grid (hidden by default)
        self.camera_grid_container = QWidget()
        self.camera_grid_layout = QGridLayout(self.camera_grid_container)
        self.camera_grid_layout.setSpacing(12)
        self.camera_grid_layout.setContentsMargins(12, 12, 12, 12)
        self.camera_grid_layout.setColumnStretch(0, 1)
        self.camera_grid_layout.setColumnStretch(1, 1)
        self.camera_grid_container.setStyleSheet("background-color: #11111b;")
        self._build_camera_grid()
        self.video_container.addWidget(self.camera_grid_container)

        self.camera_grid_container.hide()  # Hidden initially

        self.main_layout.addLayout(self.video_container, stretch=4)"""

new_video_layout = """        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # ── LEFT: Video/Grid Display Area ──────────────────────────────────────
        self.video_container = QWidget()
        self.video_layout = QVBoxLayout(self.video_container)
        self.video_layout.setContentsMargins(0, 0, 0, 0)
        
        # Title bar above video
        self.cam_title = QLabel("Initializing...")
        self.cam_title.setStyleSheet(\"\"\"
            font-size: 16px; font-weight: bold; color: #cdd6f4;
            background-color: #313244; padding: 8px; border-radius: 4px;
        \"\"\")
        self.cam_title.setAlignment(Qt.AlignCenter)
        self.video_layout.addWidget(self.cam_title)

        # Stack to hold Single View vs Grid View
        from PySide6.QtWidgets import QStackedWidget, QSizePolicy
        self.video_stack = QStackedWidget()
        
        # Single View Label
        self.single_video_label = QLabel("Waiting for camera...")
        self.single_video_label.setAlignment(Qt.AlignCenter)
        self.single_video_label.setStyleSheet("background-color: #11111b; color: #a6adc8; border-radius: 4px;")
        self.single_video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.single_video_label.setMinimumSize(640, 480)
        
        # Grid View Area
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setStyleSheet("QScrollArea { border: none; background-color: #11111b; }")
        
        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("background-color: #11111b;")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(10)
        
        # Dict to store the video labels for the grid (key: cam_id)
        self.grid_video_labels = {}
        
        self.grid_scroll.setWidget(self.grid_container)
        
        self.video_stack.addWidget(self.single_video_label) # Index 0
        self.video_stack.addWidget(self.grid_scroll)        # Index 1

        self.video_layout.addWidget(self.video_stack)
        self.main_layout.addWidget(self.video_container, stretch=3)"""

code = code.replace(old_video_layout, new_video_layout)

# Also rewrite the Sidebar slots list
old_sidebar = """        # Parking Slots
        self.sidebar.addWidget(self._section_label("PARKING SLOTS"))
        self.slot_status_label = QLabel("Waiting for data...")
        self.slot_status_label.setWordWrap(True)
        self.slot_status_label.setFont(QFont("Consolas", 10))
        self.sidebar.addWidget(self.slot_status_label)

        self.sidebar.addStretch()

        self.sidebar.addWidget(self._divider())

        # Detection Control
        self.sidebar.addWidget(self._section_label("DETECTION"))

        # Camera selector info
        self.cam_status_label = QLabel()
        self.cam_status_label.setWordWrap(True)
        self.cam_status_label.setStyleSheet("font-size: 11px; color: #cdd6f4;")
        self._refresh_cam_status_label()
        self.sidebar.addWidget(self.cam_status_label)"""

new_sidebar = """        # Parking Slots Info
        self.sidebar.addWidget(self._section_label("PARKING SLOTS"))
        self.slots_layout = QVBoxLayout()
        self.slots_layout.setAlignment(Qt.AlignTop)
        self.slots_widget = QWidget()
        self.slots_widget.setLayout(self.slots_layout)
        
        self.slots_scroll = QScrollArea()
        self.slots_scroll.setWidget(self.slots_widget)
        self.slots_scroll.setWidgetResizable(True)
        self.slots_scroll.setStyleSheet("QScrollArea { border: none; background-color: #1e1e2e; }")
        
        self.sidebar.addWidget(self.slots_scroll)
        self.sidebar.addStretch()

        self.sidebar.addWidget(self._divider())

        # Detection Control
        self.sidebar.addWidget(self._section_label("SELECTED CAMERA"))

        # Camera selector info
        self.cam_status_label = QLabel()
        self.cam_status_label.setWordWrap(True)
        self.cam_status_label.setStyleSheet("font-size: 11px; color: #cdd6f4;")
        self._refresh_cam_status_label()
        self.sidebar.addWidget(self.cam_status_label)"""

code = code.replace(old_sidebar, new_sidebar)

with open('mainwindow.py', 'w') as f:
    f.write(code)

