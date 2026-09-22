import contextlib
import logging
import tkinter as tk
from tkinter import ttk
from typing import Callable, Literal

import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image, ImageTk

from anonymizer.controller.series_io import SeriesProjections
from anonymizer.controller.series_overlay import (
    LayerType,
    OCRText,
    OverlayData,
    Segmentation,
    UserRectangle,
)
from anonymizer.utils.tk_mouse import pointer_buttons
from anonymizer.utils.translate import _
from anonymizer.utils.windowing import apply_windowing
from anonymizer.view.common.ctk_safe import dispose_photo_image
from anonymizer.view.series.anatomy_overlay import (
    bgr_to_hex,
    latch_button_width_px,
    structure_button_label,
)
from anonymizer.view.series.histogram import Histogram
from anonymizer.view.series.series_overlay import render_segmentations_overlay

logger = logging.getLogger(__name__)

ProjectionMode = Literal["slice", "min", "mean", "max"]
AnnotateMode = Literal["view", "annotate"]
AnnotateTool = Literal["brush", "erase"]


class ImageViewer(ctk.CTkFrame):
    CACHE_SIZE = 50  # Maximum number of images to keep in cache
    MIN_FPS = 1
    NORMAL_FPS = 5
    MAX_FPS = 20
    PRELOAD_FRAMES = 10  # Number of frames to preload
    PLAY_BTN_SIZE = (28, 28)
    BUTTON_WIDTH = 100
    PAD = 6
    DATA_PANEL_PAD = 4
    BRUSH_RADIUS_MIN = 1
    BRUSH_RADIUS_MAX = 64
    BRUSH_RADIUS_DEFAULT = 12
    HISTOGRAM_CANVAS_WIDTH = 220
    HISTOGRAM_CANVAS_HEIGHT = 110
    SEGMENTATION_BUTTON_HEIGHT = 22
    SEGMENTATION_BUTTONS_PER_ROW = 2
    SEGMENTATION_SCROLL_MIN_HEIGHT = 80
    SEGMENTATION_SCROLL_MAX_HEIGHT = 140
    SMALL_JUMP_PERCENTAGE = 0.01  # 1% of the total images
    LARGE_JUMP_PERCENTAGE = 0.10  # 10% of the total images
    MAX_SCREEN_PERCENTAGE = 0.7  # area of current screen available for displaying image
    TEXT_BOX_COLOR_BGR = (0, 255, 0)  # green for OpenCV BGR overlays
    USER_RECT_COLOR_BGR = (255, 0, 0)  # blue for OpenCV BGR overlays
    EXCLUDE_RECT_COLOR_BGR = (255, 255, 255)  # white dotted outline for OCR exclude zones
    SEGMENTATION_COLOR_BGR = (0, 0, 255)  # red for OpenCV BGR overlays
    EXCLUDE_RECT_DASH = 8  # segment length (px) for dotted exclude outlines
    EXCLUDE_RECT_GAP = 6
    DEFAULT_WL_SENSITIVITY = 0.75  # Pixels moved per unit change in WL (affects Beta)
    DEFAULT_WW_SENSITIVITY = 0.75  # Pixels moved per unit change in WW (affects Alpha)
    ZOOM_MIN = 0.25
    ZOOM_MAX = 8.0
    ZOOM_WHEEL_FACTOR = 1.15
    PAN_MIN_VISIBLE_FRACTION = 0.1

    def __init__(
        self,
        parent,
        images: np.ndarray,
        initial_wl: float,
        initial_ww: float,
        add_to_whitelist_callback: Callable[[str], None] | None = None,
        regenerate_series_projections_callback: Callable[[], None] | None = None,
        *,
        segmentation_overlay_color: tuple[int, int, int] | None = None,
        segmentation_overlay_alpha: float = 1.0,
        on_slice_index_changed: Callable[[int], None] | None = None,
        on_wlww_changed: Callable[[float, float], None] | None = None,
        on_segmentation_toggle: Callable[[str, bool], None] | None = None,
        clear_callback: Callable[[], None] | None = None,
        on_annotate_mode_changed: Callable[[AnnotateMode], None] | None = None,
        on_annotate_stroke: Callable[[str, int, int, int, AnnotateTool], None] | None = None,
        on_annotate_stroke_end: Callable[[], None] | None = None,
        on_annotate_undo: Callable[[], None] | None = None,
        on_annotate_new_label: Callable[[], None] | None = None,
        on_annotate_import_segments: Callable[[], None] | None = None,
        on_annotate_target_changed: Callable[[str | None], None] | None = None,
        enable_interactive_editing: bool = True,
        show_playback_controls: bool = True,
        show_data_panel: bool = True,
        series_projections: SeriesProjections | None = None,
    ):
        super().__init__(master=parent)  # Call the superclass constructor
        self.parent = parent

        if images is None or images.size == 0:
            raise ValueError("ImageViewer requires a non-empty NumPy array for images.")
        if images.ndim not in [3, 4]:  # Expect (F, H, W) or (F, H, W, C)
            raise ValueError(f"Unsupported image array dimensions: {images.ndim}. Expected 3 or 4.")

        self.num_images: int = images.shape[0]
        self.images: np.ndarray = images
        self.add_to_whitelist_callback = add_to_whitelist_callback
        self.regenerate_series_projections_callback = regenerate_series_projections_callback
        self.segmentation_overlay_color = segmentation_overlay_color or self.SEGMENTATION_COLOR_BGR
        self.segmentation_overlay_alpha = min(1.0, max(0.0, segmentation_overlay_alpha))
        self.on_slice_index_changed = on_slice_index_changed
        self.on_wlww_changed = on_wlww_changed
        self.on_segmentation_toggle = on_segmentation_toggle
        self.clear_callback = clear_callback
        self.on_annotate_mode_changed = on_annotate_mode_changed
        self.on_annotate_stroke = on_annotate_stroke
        self.on_annotate_stroke_end = on_annotate_stroke_end
        self.on_annotate_undo = on_annotate_undo
        self.on_annotate_new_label = on_annotate_new_label
        self.on_annotate_import_segments = on_annotate_import_segments
        self.on_annotate_target_changed = on_annotate_target_changed
        self.enable_interactive_editing = enable_interactive_editing
        self.show_playback_controls = show_playback_controls
        self.show_data_panel = show_data_panel
        self._companion_images: np.ndarray | None = None
        self.companion_canvas: tk.Canvas | None = None
        self.companion_canvas_image_item = None
        self._companion_cache: dict[int, tuple[ImageTk.PhotoImage, Image.Image, tuple[int, int]]] = {}
        self._primary_label: tk.Label | None = None
        self._companion_label: tk.Label | None = None
        self._interaction_enabled = True
        self._startup_complete = False
        self._scrollbar_update_depth = 0
        self._scrollbar_updates_suppressed = False
        self._scroll_command: Callable[..., None] | None = None
        self._projection_mode: ProjectionMode = "slice"
        self._series_projections = series_projections
        self._projection_buttons: dict[str, ctk.CTkButton] = {}
        self._suppress_callbacks = False
        self._active_segmentation_names: set[str] = set()
        # View-mode multi-select latch set. Annotate mode uses exclusive paint-target
        # selection without permanently dropping these (so user chips stay with TS).
        self._view_latch_names: set[str] = set()
        self._segmentation_button_meta: dict[str, tuple[int, int, int]] = {}
        self._segmentation_buttons: dict[str, ctk.CTkButton] = {}
        self.segmentation_frame: ctk.CTkFrame | None = None
        self.segmentation_buttons_frame: ctk.CTkScrollableFrame | None = None
        self._segmentation_title_label: ctk.CTkLabel | None = None
        self.clear_ts_cache_button: ctk.CTkButton | None = None
        self._annotate_chrome: ctk.CTkFrame | None = None
        self._annotate_mode: AnnotateMode = "view"
        self._annotate_tool: AnnotateTool = "brush"
        self._brush_radius: int = self.BRUSH_RADIUS_DEFAULT
        self._annotate_enabled: bool = False
        self._paint_target_key: str | None = None
        self._paint_target_options: list[tuple[str, str]] = []
        self._painting: bool = False
        self._last_paint_xy: tuple[int, int] | None = None
        self._brush_cursor_id: int | None = None
        self._brush_size_label: ctk.CTkLabel | None = None
        self._view_mode_btn: ctk.CTkButton | None = None
        self._annotate_mode_btn: ctk.CTkButton | None = None
        self._brush_tool_btn: ctk.CTkButton | None = None
        self._erase_tool_btn: ctk.CTkButton | None = None
        self._annotate_tools_frame: ctk.CTkFrame | None = None
        self._new_label_btn: ctk.CTkButton | None = None
        self._import_segments_btn: ctk.CTkButton | None = None
        self._fit_btn: ctk.CTkButton | None = None
        self._segmentation_button_labels: dict[str, str] = {}
        self._last_hist_canvas_height: int | None = None
        self._last_viewport_size: tuple[int, int] | None = None
        self._segmentation_scroll_height: int = self.SEGMENTATION_SCROLL_MIN_HEIGHT
        self._viewport_fit_pending = False
        self._pending_viewport_size: tuple[int, int] | None = None
        # Zoom/pan relative to fit-to-viewport baseline (1.0 / 0,0 = fitted).
        self._zoom: float = 1.0
        self._pan_x: float = 0.0
        self._pan_y: float = 0.0
        self._panning: bool = False
        self._pan_start_xy: tuple[int, int] | None = None
        self._pan_origin: tuple[float, float] | None = None
        self._fit_pil: Image.Image | None = None
        self._fit_companion_pil: Image.Image | None = None
        # Native-resolution RGB composites (windowed + overlays) for crisp NEAREST upscale.
        self._native_pil: Image.Image | None = None
        self._native_companion_pil: Image.Image | None = None
        self._transformed_photo: ImageTk.PhotoImage | None = None
        self._transformed_companion_photo: ImageTk.PhotoImage | None = None
        self._last_install_zoom: float | None = None
        self._last_companion_install_zoom: float | None = None

        # Determine image properties from the last frame
        last_frame = images[-1]
        self.image_height: int = last_frame.shape[0]
        self.image_width: int = last_frame.shape[1]

        # --- Determine if series is high bit depth grayscale ---
        self.is_high_bit_grayscale: bool = (last_frame.ndim == 2 and last_frame.dtype != np.uint8) or (
            last_frame.ndim == 3 and last_frame.shape[-1] == 1 and last_frame.dtype != np.uint8
        )
        self.is_color: bool = last_frame.ndim == 3 and last_frame.shape[2] == 3

        logger.info(
            f"ImageViewer Init: HighBitGrayscale={self.is_high_bit_grayscale}, Color={self.is_color}, Dtype={last_frame.dtype}, Shape={images.shape}"
        )

        self.current_image_index: int = 0
        self.photo_image = None
        # Cache for loaded images: cache index: (PhotoImage, (Width, Height))
        self.image_cache: dict[int, tuple[ImageTk.PhotoImage, Image.Image, tuple[int, int]]] = {}
        self.fps: int = self.NORMAL_FPS  # Frames per second for playback
        self.playing: bool = False  # Playback state
        self.play_delay: int = int(1000 / self.fps)  # Delay in milliseconds, initial value
        self.after_id = None  # Store the ID of the 'after' call
        self.current_size: tuple[int, int] = (images.shape[2], images.shape[1])
        self.overlay_data: dict[int, OverlayData] = {}  # Store overlay data per frame
        self.propagate_overlays: bool = False
        self.active_layers: set[LayerType] = set()
        self.active_layers.add(LayerType.TEXT)
        self.active_layers.add(LayerType.USER_RECT)
        self.active_layers.add(LayerType.EXCLUDE_RECT)

        # --- User Rectangle Tracking ---
        self.temp_rect_id = None
        self.drawing_rect = False
        self.start_x = None
        self.start_y = None

        # --- Windowing: Brightness/Contrast Tracking --
        self.adjusting_wlww: bool = False
        self.adjust_start_x: int | None = None
        self.adjust_start_y: int | None = None
        # Set initial WW/WL
        self.current_wl: float = initial_wl
        self.current_ww: float = initial_ww
        self.initial_wl: float = initial_wl
        self.initial_ww: float = initial_ww
        # Derived alpha/beta for internal use with convertScaleAbs
        self._derived_alpha: float = 1.0
        self._derived_beta: int = 0
        self._update_derived_alpha_beta()  # Calculate initial derived values

        # --- Calculate Jump Amounts Dynamically ---
        self.small_jump: int = max(1, int(self.num_images * self.SMALL_JUMP_PERCENTAGE))  # Ensure at least 1
        self.large_jump: int = max(1, int(self.num_images * self.LARGE_JUMP_PERCENTAGE))

        # --- Load Button Icons ---
        # Load images and convert to Pillow Image
        play_image = Image.open("assets/icons/play.png").resize(self.PLAY_BTN_SIZE)
        pause_image = Image.open("assets/icons/pause.png").resize(self.PLAY_BTN_SIZE)

        # --- Create Play/Pause Icons as CTkImage objects ---
        self.ctk_play_icon = ctk.CTkImage(light_image=play_image, dark_image=play_image, size=self.PLAY_BTN_SIZE)
        self.ctk_pause_icon = ctk.CTkImage(light_image=pause_image, dark_image=pause_image, size=self.PLAY_BTN_SIZE)

        # --- UI Elements ---
        # Image column absorbs all slack (weight=1); RHS chrome takes its natural
        # width (weight=0), so Tk never squeezes the controls to fit a guessed size.
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        if self.show_data_panel:
            self.grid_columnconfigure(1, weight=0)

        # Black surround: the canvas is sized exactly to the pixmap and centred, so any
        # slack left over by aspect-preserving scaling reads as viewport, not as dead UI.
        self.image_frame = ctk.CTkFrame(self, fg_color="black")
        self.image_frame.grid(row=0, column=0, sticky="nsew")
        self.image_frame.grid_rowconfigure(0, weight=1)
        self.image_frame.grid_columnconfigure(0, weight=1)
        self.image_frame.bind("<Configure>", self._on_image_frame_configure)
        self._bind_slice_navigation_pointer(self.image_frame)

        self.canvas = tk.Canvas(self.image_frame, bg="black", borderwidth=0, highlightthickness=0)
        self.canvas_image_item = None
        self.canvas.grid(row=0, column=0, sticky="")

        # Scrollbar (command detached until startup completes)
        if self.num_images > 1:
            self.scrollbar = ttk.Scrollbar(self.image_frame, orient=ctk.HORIZONTAL, command=self.scroll_handler)
            self.scrollbar.grid(row=1, column=0, sticky="ew")
            self._detach_scrollbar_command()

        self.histogram: Histogram | None = None
        self.data_frame: ctk.CTkFrame | None = None
        self.control_frame: ctk.CTkFrame | None = None
        self.image_size_label: ctk.CTkLabel | None = None
        self.projection_label: ctk.CTkLabel | None = None
        self.image_number_label: ctk.CTkLabel | None = None

        if self.show_data_panel:
            # Natural size, top-aligned. Never pinned: the control row is wider than the
            # histogram, and pinning it to the histogram width clips the playback controls.
            self.data_frame = ctk.CTkFrame(self)
            self.data_frame.grid(row=0, column=1, padx=self.PAD, pady=self.PAD, sticky="n")
            self.data_frame.grid_rowconfigure(0, weight=0)
            self.data_frame.grid_rowconfigure(1, weight=0)
            self.data_frame.grid_rowconfigure(2, weight=0)
            self.data_frame.grid_columnconfigure(0, weight=1)

            self.histogram = Histogram(
                self.data_frame,
                update_callback=self._handle_histogram_update,
            )
            self.histogram.set_wlww(self.current_wl, self.current_ww, redraw=False)
            self.histogram.canvas.configure(
                width=self.HISTOGRAM_CANVAS_WIDTH,
                height=self.HISTOGRAM_CANVAS_HEIGHT,
            )
            self.histogram.grid(row=0, column=0, padx=self.DATA_PANEL_PAD, pady=self.DATA_PANEL_PAD, sticky="new")

            self.segmentation_frame = ctk.CTkFrame(self.data_frame)
            self.segmentation_frame.grid(
                row=1, column=0, padx=self.DATA_PANEL_PAD, pady=(0, self.DATA_PANEL_PAD), sticky="ew"
            )
            self.segmentation_frame.grid_rowconfigure(0, weight=0)
            self.segmentation_frame.grid_rowconfigure(1, weight=0)
            self.segmentation_frame.grid_rowconfigure(2, weight=0)
            self.segmentation_frame.grid_columnconfigure(0, weight=1)
            header = ctk.CTkFrame(self.segmentation_frame, fg_color="transparent")
            header.grid(row=0, column=0, sticky="ew", padx=self.DATA_PANEL_PAD, pady=(self.DATA_PANEL_PAD, 0))
            header.grid_columnconfigure(0, weight=1)
            self._segmentation_title_label = ctk.CTkLabel(header, text=_("Segmentation"), anchor="w")
            self._segmentation_title_label.grid(row=0, column=0, sticky="w")
            self.clear_ts_cache_button = ctk.CTkButton(
                header,
                text=_("Clear"),
                width=56,
                height=self.SEGMENTATION_BUTTON_HEIGHT,
                command=self._on_clear_clicked,
            )
            self.clear_ts_cache_button.grid(row=0, column=1, sticky="e", padx=(4, 0))
            self.clear_ts_cache_button.grid_remove()

            self._annotate_chrome = ctk.CTkFrame(self.segmentation_frame, fg_color="transparent")
            self._annotate_chrome.grid(row=1, column=0, sticky="ew", padx=self.DATA_PANEL_PAD, pady=(4, 0))
            self._annotate_chrome.grid_columnconfigure(0, weight=1)
            mode_row = ctk.CTkFrame(self._annotate_chrome, fg_color="transparent")
            mode_row.grid(row=0, column=0, sticky="ew")
            mode_row.grid_columnconfigure(4, weight=1)
            self._view_mode_btn = ctk.CTkButton(
                mode_row, text=_("View"), width=56, height=22, command=lambda: self.set_annotate_mode("view")
            )
            self._view_mode_btn.grid(row=0, column=0, padx=(0, 4))
            self._annotate_mode_btn = ctk.CTkButton(
                mode_row, text=_("Annotate"), width=72, height=22, command=lambda: self.set_annotate_mode("annotate")
            )
            self._annotate_mode_btn.grid(row=0, column=1, padx=(0, 4))
            self._new_label_btn = ctk.CTkButton(
                mode_row,
                text=_("New Segment"),
                width=96,
                height=22,
                command=self._on_new_label_clicked,
            )
            self._new_label_btn.grid(row=0, column=2, padx=(0, 4))
            self._new_label_btn.grid_remove()
            self._fit_btn = ctk.CTkButton(
                mode_row,
                text=_("Fit"),
                width=44,
                height=22,
                command=self.reset_zoom_pan,
            )
            self._fit_btn.grid(row=0, column=3, padx=(0, 4))
            self._import_segments_btn = ctk.CTkButton(
                mode_row,
                text=_("Import…"),
                width=72,
                height=22,
                command=self._on_import_segments_clicked,
            )
            self._import_segments_btn.grid(row=0, column=5, sticky="e", padx=(4, 0))
            self._annotate_tools_frame = ctk.CTkFrame(self._annotate_chrome, fg_color="transparent")
            self._annotate_tools_frame.grid(row=1, column=0, sticky="ew", pady=(4, 0))
            self._brush_tool_btn = ctk.CTkButton(
                self._annotate_tools_frame,
                text=_("Brush"),
                width=56,
                height=22,
                command=lambda: self.set_annotate_tool("brush"),
            )
            self._brush_tool_btn.grid(row=0, column=0, padx=(0, 4))
            self._erase_tool_btn = ctk.CTkButton(
                self._annotate_tools_frame,
                text=_("Erase"),
                width=56,
                height=22,
                command=lambda: self.set_annotate_tool("erase"),
            )
            self._erase_tool_btn.grid(row=0, column=1, padx=(0, 4))
            minus_btn = ctk.CTkButton(
                self._annotate_tools_frame, text="−", width=28, height=22, command=lambda: self._nudge_brush(-1)
            )
            minus_btn.grid(row=0, column=2, padx=(8, 2))
            plus_btn = ctk.CTkButton(
                self._annotate_tools_frame, text="+", width=28, height=22, command=lambda: self._nudge_brush(1)
            )
            plus_btn.grid(row=0, column=3, padx=(0, 4))
            self._brush_size_label = ctk.CTkLabel(self._annotate_tools_frame, text=f"{self._brush_radius} px")
            self._brush_size_label.grid(row=0, column=4, padx=(0, 4))
            ctk.CTkButton(
                self._annotate_tools_frame, text=_("Undo"), width=52, height=22, command=self._on_undo_clicked
            ).grid(row=0, column=5, padx=(8, 0))
            self._annotate_tools_frame.grid_remove()
            self._refresh_annotate_chrome_styles()

            self.segmentation_buttons_frame = ctk.CTkScrollableFrame(
                self.segmentation_frame,
                width=self.HISTOGRAM_CANVAS_WIDTH,
                height=self.SEGMENTATION_SCROLL_MIN_HEIGHT,
                label_text="",
            )
            self.segmentation_buttons_frame.grid(
                row=2, column=0, sticky="new", padx=self.DATA_PANEL_PAD, pady=self.DATA_PANEL_PAD
            )
            self.segmentation_buttons_frame.grid_remove()

            # Control Frame for fixed width widgets
            self.control_frame = ctk.CTkFrame(self.data_frame)
            self.control_frame.grid(
                row=2, column=0, padx=self.DATA_PANEL_PAD, pady=(0, self.DATA_PANEL_PAD), sticky="ew"
            )
            self.control_frame.grid_columnconfigure(1, weight=1)

            # Image Size Label:
            self.image_size_label = ctk.CTkLabel(self.control_frame, text="")
            self.image_size_label.grid(row=0, column=0, sticky="w", padx=self.PAD)

            self.projection_label = ctk.CTkLabel(self.control_frame, text="")
            self.projection_label.grid(row=1, column=0, sticky="w", padx=self.PAD)

            if self._series_projections is not None and self.num_images > 1:
                proj_row = ctk.CTkFrame(self.control_frame, fg_color="transparent")
                proj_row.grid(row=2, column=0, columnspan=4, sticky="w", padx=self.PAD, pady=(0, self.PAD))
                for col, (mode, label) in enumerate(
                    (("min", _("MIN")), ("mean", _("MEAN")), ("max", _("MAX")), ("slice", _("SLICE")))
                ):
                    button = ctk.CTkButton(
                        proj_row,
                        text=label,
                        width=52,
                        height=22,
                        command=lambda m=mode: self.set_projection_mode(m),  # type: ignore[arg-type]
                    )
                    button.grid(row=0, column=col, padx=(0, 4))
                    self._projection_buttons[mode] = button
                self._refresh_projection_button_styles()

            # --- Toggle Button (Play/Pause) for multi-frame series ---
            if self.num_images > 1 and self.show_playback_controls:
                self.fps_slider = ctk.CTkSlider(
                    self.control_frame,
                    width=self.BUTTON_WIDTH,
                    from_=self.MIN_FPS,
                    to=self.MAX_FPS,
                    number_of_steps=self.MAX_FPS - self.MIN_FPS,
                    orientation=ctk.HORIZONTAL,
                    command=lambda value: self.change_fps(value),
                )
                self.fps_slider.set(self.fps)
                self.fps_slider.grid(row=1, column=2, padx=self.PAD)

                self.fps_slider_label = ctk.CTkLabel(self.control_frame, text=f"{self.fps} fps")
                self.fps_slider_label.grid(row=0, column=2, padx=self.PAD)

                self.toggle_button = ctk.CTkButton(
                    self.control_frame,
                    text="",
                    image=self.ctk_play_icon,
                    width=self.PLAY_BTN_SIZE[0],
                    command=self.toggle_play,
                )
                self.toggle_button.grid(row=0, column=3, padx=self.PAD, pady=(self.PAD, 0), sticky="e")

            self.image_number_label = ctk.CTkLabel(self.control_frame, text="", font=("Courier Bold", 14))
            self.image_number_label.grid(row=1, column=3, sticky="s", padx=(0, self.PAD))
            self.apply_fixed_chrome()

        # Event binding:
        # Live resize is driven by image_frame <Configure> → fit_to_viewport().
        self.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_zoom_wheel)
        self.canvas.bind("<Command-MouseWheel>", self._on_zoom_wheel)
        self.bind("<Control-MouseWheel>", self._on_zoom_wheel)
        self.bind("<Command-MouseWheel>", self._on_zoom_wheel)
        if self.enable_interactive_editing:
            self.canvas.bind("<Button-1>", self._on_left_click)  # Left-click press
            self.canvas.bind("<B1-Motion>", self._on_left_drag)  # Left-click drag
            self.canvas.bind("<ButtonRelease-1>", self._on_left_release)  # Left-click release
            self.canvas.bind("<Motion>", self._on_canvas_motion)
        # Middle = pan; right = WW/WL (logical; Tk 8 Aqua swaps physical 2/3).
        ptr = pointer_buttons(self)
        self.canvas.bind(ptr.pan_press, self._start_pan)
        self.canvas.bind(ptr.pan_motion, self._pan_motion)
        self.canvas.bind(ptr.pan_release, self._end_pan)
        self.canvas.bind(ptr.pan_double, self._on_fit_double_click)
        self.canvas.bind(ptr.right_press, self._start_adjust_display)
        self.canvas.bind(ptr.right_motion, self._adjust_display)
        self.canvas.bind(ptr.right_release, self._end_adjust_display)
        if self.num_images > 1 and self.control_frame is not None:
            self.control_frame.bind("<MouseWheel>", self.on_mousewheel)
            self.control_frame.bind("<Control-MouseWheel>", self._on_zoom_wheel)
            self.control_frame.bind("<Command-MouseWheel>", self._on_zoom_wheel)

        # Keys: bind on widgets that can hold keyboard focus.
        # mouse_enter focuses the image canvas; CTkFrame.bind alone
        # does not receive those KeyPress events.
        if self.num_images > 1:
            self._bind_slice_navigation_keys(self)
            self._bind_slice_navigation_keys(self.canvas)
            if self.show_playback_controls:
                self.bind("<space>", self.toggle_play)
                self.canvas.bind("<space>", self.toggle_play)
        self._bind_annotate_keys(self)
        self._bind_annotate_keys(self.canvas)

        # Focus management for ImageViewer
        self.bind("<Enter>", self.mouse_enter)
        self.canvas.bind("<Enter>", self.mouse_enter)
        if self.control_frame is not None:
            self.control_frame.bind("<Enter>", self.mouse_enter)
            if self.num_images > 1:
                self._bind_slice_navigation_keys(self.control_frame)

        self.update_status()

    def _interaction_allowed(self) -> bool:
        return self._interaction_enabled

    def set_scrollbar_updates_suppressed(self, suppressed: bool) -> None:
        """Block scrollbar.set() from driving slice changes during programmatic updates."""
        self._scrollbar_updates_suppressed = suppressed

    def _detach_scrollbar_command(self) -> None:
        if not hasattr(self, "scrollbar"):
            return
        with contextlib.suppress(tk.TclError):
            self._scroll_command = self.scrollbar.cget("command")
            self.scrollbar.configure(command="")

    def _reattach_scrollbar_command(self) -> None:
        if not hasattr(self, "scrollbar") or self._scroll_command is None:
            return
        with contextlib.suppress(tk.TclError):
            self.scrollbar.configure(command=self._scroll_command)

    def schedule_initial_display(self, *, on_complete: Callable[[], None] | None = None) -> None:
        """Deferred first paint after the parent window is mapped (legacy / tests)."""

        def _run() -> None:
            self.set_display_size((self.image_width, self.image_height), refresh_histogram=True)
            self.mark_startup_complete()
            if on_complete is not None:
                on_complete()

        self.after_idle(_run)

    def set_series_projections(self, projections: SeriesProjections | None) -> None:
        self._series_projections = projections

    def set_projection_mode(self, mode: ProjectionMode) -> None:
        if mode != "slice" and self._series_projections is None:
            return
        if mode == self._projection_mode:
            return
        self._projection_mode = mode
        self._refresh_projection_button_styles()
        self.clear_cache()
        self.refresh_current_image()

    def _refresh_projection_button_styles(self) -> None:
        theme = ctk.ThemeManager.theme["CTkButton"]
        standard_fg = theme["fg_color"]
        for mode, button in self._projection_buttons.items():
            active = mode == self._projection_mode
            with contextlib.suppress(tk.TclError):
                button.configure(fg_color=("#3b8ed0" if active else standard_fg))

    def _is_projection_mode(self) -> bool:
        return self._projection_mode != "slice"

    def _display_pixels(self, frame_ndx: int) -> np.ndarray:
        if not self._is_projection_mode() or self._series_projections is None:
            return self.images[frame_ndx]
        match self._projection_mode:
            case "min":
                return self._series_projections.minimum
            case "mean":
                return self._series_projections.mean
            case "max":
                return self._series_projections.maximum
        return self.images[frame_ndx]

    def mark_startup_complete(self) -> None:
        """Enable navigation and attach scrollbar after the initial layout pass."""
        self._startup_complete = True
        self._reattach_scrollbar_command()
        if self.num_images > 1:
            self.update_scrollbar()

    def set_interaction_enabled(self, enabled: bool) -> None:
        """Enable or disable viewer navigation, windowing, and editing."""
        self._interaction_enabled = enabled
        if not enabled and self.playing:
            self._stop_playback()
        canvas_state = tk.NORMAL if enabled else tk.DISABLED
        with contextlib.suppress(tk.TclError):
            self.canvas.configure(state=canvas_state)
            if self.companion_canvas is not None:
                self.companion_canvas.configure(state=canvas_state)
        if self.control_frame is not None:
            control_state = "normal" if enabled else "disabled"
            for widget_name in ("fps_slider", "toggle_button", "fps_slider_label"):
                widget = getattr(self, widget_name, None)
                if widget is not None:
                    with contextlib.suppress(tk.TclError):
                        widget.configure(state=control_state)
        if self.histogram is not None:
            with contextlib.suppress(tk.TclError, AttributeError):
                self.histogram.canvas.configure(state=canvas_state)

    def set_slice_index_sync(self, index: int) -> None:
        """Change slice without notifying sync partners (face blur review)."""
        self._suppress_callbacks = True
        try:
            self.change_image(index)
        finally:
            self._suppress_callbacks = False

    def set_wlww_sync(self, wl: float, ww: float) -> None:
        """Apply window/level without notifying sync partners (face blur review)."""
        self._suppress_callbacks = True
        try:
            self.current_wl = wl
            self.current_ww = max(1.0, ww)
            self._update_derived_alpha_beta()
            if self.histogram is not None:
                self.histogram.set_wlww(self.current_wl, self.current_ww)
            self._companion_cache.clear()
            self.refresh_current_image()
        finally:
            self._suppress_callbacks = False

    @property
    def companion_attached(self) -> bool:
        return self.companion_canvas is not None

    def attach_companion_stack(
        self,
        images: np.ndarray,
        *,
        primary_label: str = "",
        companion_label: str = "",
    ) -> None:
        """Show a second image stack beside the primary canvas; existing controls drive both."""
        if images.shape[0] != self.num_images:
            raise ValueError(f"Companion stack length {images.shape[0]} does not match primary stack {self.num_images}")

        with contextlib.suppress(tk.TclError):
            self.update_idletasks()
        self.detach_companion_stack()
        with contextlib.suppress(tk.TclError):
            self.update_idletasks()
        self._companion_images = images
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.image_frame.grid_columnconfigure(0, weight=1)
        self.image_frame.grid_columnconfigure(1, weight=1)

        canvas_row = 0
        if primary_label or companion_label:
            if primary_label:
                self._primary_label = tk.Label(self.image_frame, text=primary_label, anchor="w")
                self._primary_label.grid(row=0, column=0, sticky="w", padx=4, pady=(0, 4))
                self._bind_slice_navigation_pointer(self._primary_label)
            if companion_label:
                self._companion_label = tk.Label(self.image_frame, text=companion_label, anchor="w")
                self._companion_label.grid(row=0, column=1, sticky="w", padx=4, pady=(0, 4))
                self._bind_slice_navigation_pointer(self._companion_label)
            canvas_row = 1
            self.image_frame.grid_rowconfigure(0, weight=0)
            self.image_frame.grid_rowconfigure(canvas_row, weight=1)
        else:
            self.image_frame.grid_rowconfigure(0, weight=1)

        self.canvas.grid(row=canvas_row, column=0, sticky="", padx=(0, 4))
        self.companion_canvas = tk.Canvas(self.image_frame, bg="black", borderwidth=0, highlightthickness=0)
        self.companion_canvas.grid(row=canvas_row, column=1, sticky="", padx=(4, 0))
        self._bind_slice_navigation_pointer(self.companion_canvas)
        self.companion_canvas.bind("<Control-MouseWheel>", self._on_zoom_wheel)
        self.companion_canvas.bind("<Command-MouseWheel>", self._on_zoom_wheel)
        ptr = pointer_buttons(self)
        self.companion_canvas.bind(ptr.pan_press, self._start_pan)
        self.companion_canvas.bind(ptr.pan_motion, self._pan_motion)
        self.companion_canvas.bind(ptr.pan_release, self._end_pan)
        self.companion_canvas.bind(ptr.pan_double, self._on_fit_double_click)

        scroll_row = canvas_row + 1
        if self.num_images > 1:
            self.scrollbar.grid(row=scroll_row, column=0, columnspan=2, sticky="ew")
            self._bind_slice_navigation_pointer(self.scrollbar)
        self._set_data_panel_visible(False)

    def _set_data_panel_visible(self, visible: bool) -> None:
        """Show or hide histogram and playback chrome (dual-pane blur review uses side-by-side canvases only)."""
        if self.data_frame is None:
            return
        with contextlib.suppress(tk.TclError):
            if visible:
                self.data_frame.grid(row=0, column=1, padx=self.PAD, pady=self.PAD, sticky="n")
                self.grid_columnconfigure(0, weight=1)
                self.apply_fixed_chrome()
            else:
                if self.playing:
                    self._stop_playback()
                self.data_frame.grid_remove()
                self.grid_columnconfigure(0, weight=1)

    def detach_companion_stack(self) -> None:
        """Remove the companion stack and restore the single-stack layout."""
        if self.companion_canvas is None and self._primary_label is None and self._companion_label is None:
            return

        with contextlib.suppress(tk.TclError):
            self.update_idletasks()

        if self.companion_canvas is not None:
            with contextlib.suppress(tk.TclError):
                self.companion_canvas.grid_remove()
                self.companion_canvas.destroy()
            self.companion_canvas = None
            self.companion_canvas_image_item = None

        for attr in ("_primary_label", "_companion_label"):
            label = getattr(self, attr)
            if label is not None:
                setattr(self, attr, None)
                with contextlib.suppress(tk.TclError):
                    label.grid_remove()
                    label.destroy()

        self._companion_images = None
        self._fit_companion_pil = None
        self._native_companion_pil = None
        dispose_photo_image(self, self._transformed_companion_photo)
        self._transformed_companion_photo = None
        self._companion_cache.clear()
        self.image_frame.grid_columnconfigure(0, weight=1)
        self.image_frame.grid_columnconfigure(1, weight=0)
        self.image_frame.grid_rowconfigure(0, weight=1)
        self.image_frame.grid_rowconfigure(1, weight=0)
        self.canvas.grid(row=0, column=0, sticky="", padx=0)
        if self.num_images > 1:
            self.scrollbar.grid(row=1, column=0, sticky="ew")
        self._set_data_panel_visible(True)

    def _load_companion_display(self, frame_ndx: int) -> None:
        if self._companion_images is None or self.companion_canvas is None:
            return
        if not (0 <= frame_ndx < self._companion_images.shape[0]):
            return

        if (
            self._zoom <= 1.0
            and frame_ndx in self._companion_cache
        ):
            cached_image, cached_pil, cached_size = self._companion_cache[frame_ndx]
            if cached_size == self.current_size:
                self._fit_companion_pil = cached_pil
                self._last_companion_install_zoom = None
                self._install_transformed_from_pil(companion=True)
                return

        image_array = self._companion_images[frame_ndx].copy()
        image_array = apply_windowing(self.current_wl, self.current_ww, image_array)
        native_pil = Image.fromarray(image_array)
        if self._native_companion_pil is not None and hasattr(self._native_companion_pil, "close"):
            with contextlib.suppress(Exception):
                self._native_companion_pil.close()
        self._native_companion_pil = native_pil.copy()
        image_pil_resized = native_pil.resize(self.current_size, Image.Resampling.LANCZOS)
        native_pil.close()
        fit_photo = ImageTk.PhotoImage(image_pil_resized)
        self._fit_companion_pil = image_pil_resized.copy()
        self._last_companion_install_zoom = None
        self._install_transformed_from_pil(companion=True)
        self._companion_cache[frame_ndx] = (fit_photo, image_pil_resized, self.current_size)
        self._manage_companion_cache()

    def update_companion_stack(self, images: np.ndarray) -> None:
        """Replace companion pixel data without rebuilding the dual-pane layout."""
        if not self.companion_attached:
            raise ValueError("Companion stack is not attached")
        if images.shape[0] != self.num_images:
            raise ValueError(f"Companion stack length {images.shape[0]} does not match primary stack {self.num_images}")
        self._companion_images = images
        self._companion_cache.clear()
        self._load_companion_display(self.current_image_index)

    def _remove_from_companion_cache(self, index: int) -> None:
        if index not in self._companion_cache:
            return
        entry = self._companion_cache.pop(index)
        photo_image = entry[0]
        dispose_photo_image(self, photo_image)
        if len(entry) > 1 and hasattr(entry[1], "close"):
            entry[1].close()

    def _manage_companion_cache(self) -> None:
        while len(self._companion_cache) > self.CACHE_SIZE:
            oldest_key = min(self._companion_cache.keys())
            self._remove_from_companion_cache(oldest_key)

    def get_current_image(self) -> np.ndarray:
        return self.images[self.current_image_index]

    def set_overlay_propagation(self, propagate: bool):
        self.propagate_overlays = propagate

    def _on_clear_clicked(self) -> None:
        if self.clear_callback is not None:
            self.clear_callback()

    def set_clear_button_present(self, present: bool) -> None:
        if self.clear_ts_cache_button is None:
            return
        if present:
            self.clear_ts_cache_button.grid()
        else:
            self.clear_ts_cache_button.grid_remove()
        self.apply_fixed_chrome()

    def get_active_segmentation_names(self) -> set[str]:
        return set(self._active_segmentation_names)

    def clear_active_segmentations(self) -> None:
        self._active_segmentation_names.clear()
        self._view_latch_names.clear()
        self._refresh_segmentation_button_styles()

    def remember_view_latch(self, name: str) -> None:
        """Keep ``name`` in the View-mode latch set (e.g. newly created user segment)."""
        if name in self._segmentation_button_meta or name.startswith("user:"):
            self._view_latch_names.add(name)

    def set_segmentation_title(self, *, mode: str | None = None) -> None:
        """Set panel title to ``Segmentation`` or ``Segmentation [3 mm]`` when mode is known."""
        if self._segmentation_title_label is None:
            return
        if mode:
            from anonymizer.controller.ai.tseg.config import segmentation_mode_display

            text = f"{_('Segmentation')} [{segmentation_mode_display(mode)}]"
        else:
            text = _("Segmentation")
        self._segmentation_title_label.configure(text=text)

    def set_segmentation_structures(
        self,
        items: list[tuple[str, tuple[int, int, int]]],
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Rebuild latch buttons. ``items`` are (key, color_bgr) in display order.

        Keys are TS structure names or ``user:<id>`` for custom ROI labels.
        """
        if self.segmentation_buttons_frame is None:
            return
        for child in self.segmentation_buttons_frame.winfo_children():
            child.destroy()
        self._segmentation_buttons.clear()
        self._segmentation_button_meta = {name: color for name, color in items}
        self._segmentation_button_labels = dict(labels or {})
        still_active = {name for name in self._active_segmentation_names if name in self._segmentation_button_meta}
        self._active_segmentation_names = still_active
        self._view_latch_names = {name for name in self._view_latch_names if name in self._segmentation_button_meta}
        if self._annotate_mode == "view":
            # View latch tracks the multi-select set shown on chips.
            self._view_latch_names = set(still_active)
        per_row = self.SEGMENTATION_BUTTONS_PER_ROW
        for col in range(per_row):
            with contextlib.suppress(tk.TclError):
                self.segmentation_buttons_frame.grid_columnconfigure(col, weight=0)
        for index, (name, _color_bgr) in enumerate(items):
            label = self._segmentation_button_labels.get(name) or structure_button_label(name)
            row, col = divmod(index, per_row)
            button = ctk.CTkButton(
                self.segmentation_buttons_frame,
                text=label,
                width=latch_button_width_px(label),
                height=self.SEGMENTATION_BUTTON_HEIGHT,
                anchor="center",
                command=lambda n=name: self._toggle_segmentation_structure(n),
            )
            button.grid(row=row, column=col, sticky="w", padx=2, pady=2)
            self._segmentation_buttons[name] = button
        self._refresh_segmentation_button_styles()
        self.apply_fixed_chrome()

    def reveal_segmentation_button(self, name: str) -> None:
        """Scroll the segment latch list so ``name`` is visible."""
        button = self._segmentation_buttons.get(name)
        frame = self.segmentation_buttons_frame
        if button is None or frame is None:
            return
        with contextlib.suppress(tk.TclError):
            frame.update_idletasks()
            canvas = getattr(frame, "_parent_canvas", None)
            if canvas is not None:
                # User labels are listed first — scroll to top when revealing a new one.
                if name.startswith("user:"):
                    canvas.yview_moveto(0.0)
                else:
                    canvas.yview_moveto(1.0)
            else:
                button.focus_set()

    def _paint_key_for_button(self, name: str) -> str:
        if name.startswith("user:"):
            return name
        return f"ts:{name}"

    def _toggle_segmentation_structure(self, name: str) -> None:
        if name not in self._segmentation_button_meta:
            return
        if self._annotate_mode == "annotate":
            self._select_annotate_segment(name)
            return
        active = name not in self._active_segmentation_names
        if active:
            self._active_segmentation_names.add(name)
            self._view_latch_names.add(name)
        else:
            self._active_segmentation_names.discard(name)
            self._view_latch_names.discard(name)
        self._refresh_segmentation_button_styles()
        if self.on_segmentation_toggle is not None:
            self.on_segmentation_toggle(name, active)

    def _select_annotate_segment(self, name: str) -> None:
        """Exclusive paint-target selection in Annotate mode (radio behavior)."""
        paint_key = self._paint_key_for_button(name)
        previous_active = set(self._active_segmentation_names)
        # Snapshot View latches before collapsing to the paint target.
        if not self._view_latch_names:
            self._view_latch_names = set(previous_active)
        self._view_latch_names.add(name)
        # One selected chip for painting; View latch set is restored on leaving Annotate.
        self._active_segmentation_names = {name}
        self.set_paint_target(paint_key)
        self._refresh_segmentation_button_styles()
        if self.on_segmentation_toggle is None:
            return
        for old in previous_active - self._active_segmentation_names:
            self.on_segmentation_toggle(old, False)
        for new in self._active_segmentation_names - previous_active:
            self.on_segmentation_toggle(new, True)

    def _refresh_segmentation_button_styles(self) -> None:
        theme = ctk.ThemeManager.theme["CTkButton"]
        standard_fg = theme["fg_color"]
        standard_hover = theme["hover_color"]
        for name, button in self._segmentation_buttons.items():
            color_bgr = self._segmentation_button_meta[name]
            outline_hex = bgr_to_hex(color_bgr)
            if self._annotate_mode == "annotate":
                selected = self._paint_target_key == self._paint_key_for_button(name)
            else:
                selected = name in self._active_segmentation_names
            if selected:
                button.configure(
                    fg_color="#ffffff",
                    hover_color="#f0f0f0",
                    border_color=outline_hex,
                    border_width=2,
                    text_color="#000000",
                )
            else:
                button.configure(
                    fg_color=standard_fg,
                    hover_color=standard_hover,
                    border_color=standard_fg,
                    border_width=0,
                    text_color="#ffffff",
                )

    def set_annotate_enabled(self, enabled: bool) -> None:
        """Enable Annotate mode when mask geometry / volume grid exists."""
        self._annotate_enabled = bool(enabled)
        if not enabled and self._annotate_mode == "annotate":
            self.set_annotate_mode("view")
        if self._annotate_mode_btn is not None:
            state = "normal" if enabled else "disabled"
            with contextlib.suppress(tk.TclError):
                self._annotate_mode_btn.configure(state=state)
        if self._import_segments_btn is not None:
            state = "normal" if enabled else "disabled"
            with contextlib.suppress(tk.TclError):
                self._import_segments_btn.configure(state=state)
        self.apply_fixed_chrome()

    def get_annotate_mode(self) -> AnnotateMode:
        return self._annotate_mode

    def set_annotate_mode(self, mode: AnnotateMode) -> None:
        if mode == "annotate" and not self._annotate_enabled:
            return
        if mode == self._annotate_mode:
            self._refresh_annotate_chrome_styles()
            return
        previous_mode = self._annotate_mode
        self._annotate_mode = mode
        self._painting = False
        self._last_paint_xy = None
        self._clear_brush_cursor()
        if mode == "annotate":
            # Preserve View multi-select; exclusive paint selection is temporary.
            self._view_latch_names = set(self._active_segmentation_names) | self._view_latch_names
            if self._annotate_tools_frame is not None:
                self._annotate_tools_frame.grid()
            if self._new_label_btn is not None:
                self._new_label_btn.grid()
            self.canvas.config(cursor="none")
            if self._paint_target_key is None:
                if self._active_segmentation_names:
                    first = sorted(self._active_segmentation_names)[0]
                    self._select_annotate_segment(first)
                elif self._segmentation_button_meta:
                    first = next(iter(self._segmentation_button_meta))
                    self._select_annotate_segment(first)
            else:
                key = self._paint_target_key
                if key.startswith("ts:"):
                    self._select_annotate_segment(key.split(":", 1)[1])
                elif key.startswith("user:"):
                    self._select_annotate_segment(key)
        else:
            if self._annotate_tools_frame is not None:
                self._annotate_tools_frame.grid_remove()
            if self._new_label_btn is not None:
                self._new_label_btn.grid_remove()
            self.canvas.config(cursor="")
            if previous_mode == "annotate":
                self._restore_view_latches()
        self._refresh_annotate_chrome_styles()
        self._refresh_segmentation_button_styles()
        if self.on_annotate_mode_changed is not None:
            self.on_annotate_mode_changed(mode)

    def _restore_view_latches(self) -> None:
        """Re-apply View multi-select after leaving Annotate (keeps user chips with TS)."""
        desired = {n for n in self._view_latch_names if n in self._segmentation_button_meta}
        if self._paint_target_key:
            if self._paint_target_key.startswith("user:"):
                desired.add(self._paint_target_key)
            elif self._paint_target_key.startswith("ts:"):
                desired.add(self._paint_target_key.split(":", 1)[1])
        previous = set(self._active_segmentation_names)
        self._active_segmentation_names = desired
        self._view_latch_names = set(desired)
        self._refresh_segmentation_button_styles()
        if self.on_segmentation_toggle is None:
            return
        for old in previous - desired:
            self.on_segmentation_toggle(old, False)
        for new in desired - previous:
            self.on_segmentation_toggle(new, True)

    def set_annotate_tool(self, tool: AnnotateTool) -> None:
        self._annotate_tool = tool
        self._refresh_annotate_chrome_styles()

    def set_brush_radius(self, radius: int) -> None:
        self._brush_radius = max(self.BRUSH_RADIUS_MIN, min(self.BRUSH_RADIUS_MAX, int(radius)))
        if self._brush_size_label is not None:
            self._brush_size_label.configure(text=f"{self._brush_radius} px")

    def _nudge_brush(self, delta: int) -> None:
        self.set_brush_radius(self._brush_radius + delta)

    def set_paint_targets(self, options: list[tuple[str, str]], *, active_key: str | None = None) -> None:
        """``options`` are (key, display_label). Keys: ``user:<id>`` or ``ts:<name>``."""
        self._paint_target_options = list(options)
        if active_key is not None:
            self.set_paint_target(active_key)
        elif self._paint_target_key and any(k == self._paint_target_key for k, _ in options):
            self.set_paint_target(self._paint_target_key)
        elif options:
            self.set_paint_target(options[0][0])
        else:
            self._paint_target_key = None

    def set_paint_target(self, key: str | None) -> None:
        self._paint_target_key = key
        self._refresh_segmentation_button_styles()
        if self.on_annotate_target_changed is not None:
            self.on_annotate_target_changed(key)

    def get_paint_target_key(self) -> str | None:
        return self._paint_target_key

    def _refresh_annotate_chrome_styles(self) -> None:
        theme = ctk.ThemeManager.theme["CTkButton"]
        active_fg = theme.get("fg_color", ("#3a7ebf", "#1f538d"))
        idle_fg = ("gray70", "gray30")
        if self._view_mode_btn is not None:
            self._view_mode_btn.configure(
                fg_color=active_fg if self._annotate_mode == "view" else idle_fg
            )
        if self._annotate_mode_btn is not None:
            self._annotate_mode_btn.configure(
                fg_color=active_fg if self._annotate_mode == "annotate" else idle_fg
            )
        if self._brush_tool_btn is not None:
            self._brush_tool_btn.configure(
                fg_color=active_fg if self._annotate_tool == "brush" else idle_fg
            )
        if self._erase_tool_btn is not None:
            self._erase_tool_btn.configure(
                fg_color=active_fg if self._annotate_tool == "erase" else idle_fg
            )

    def _bind_annotate_keys(self, widget) -> None:
        widget.bind("<Escape>", self._on_annotate_escape)
        widget.bind("<Control-z>", self._on_undo_clicked)
        widget.bind("<Command-z>", self._on_undo_clicked)
        widget.bind("<KeyPress-b>", lambda e: self.set_annotate_tool("brush"))
        widget.bind("<KeyPress-B>", lambda e: self.set_annotate_tool("brush"))
        widget.bind("<KeyPress-e>", lambda e: self.set_annotate_tool("erase"))
        widget.bind("<KeyPress-E>", lambda e: self.set_annotate_tool("erase"))
        widget.bind("<bracketleft>", lambda e: self._nudge_brush(-1))
        widget.bind("<bracketright>", lambda e: self._nudge_brush(1))
        widget.bind("<KeyPress-f>", self._on_fit_key)
        widget.bind("<KeyPress-F>", self._on_fit_key)
        for digit in range(1, 10):
            widget.bind(f"<KeyPress-{digit}>", lambda e, d=digit: self._select_paint_target_by_index(d - 1))

    def _select_paint_target_by_index(self, index: int) -> None:
        if self._annotate_mode != "annotate":
            return
        keys = list(self._segmentation_button_meta.keys())
        if 0 <= index < len(keys):
            self._select_annotate_segment(keys[index])

    def _on_annotate_escape(self, event=None):
        if self._annotate_mode != "annotate":
            return
        if self._painting:
            self._painting = False
            self._last_paint_xy = None
            if self.on_annotate_stroke_end is not None:
                self.on_annotate_stroke_end()
            return
        self.set_annotate_mode("view")

    def _on_undo_clicked(self, event=None):
        if self.on_annotate_undo is not None:
            self.on_annotate_undo()

    def _on_new_label_clicked(self) -> None:
        if self.on_annotate_new_label is not None:
            self.on_annotate_new_label()

    def _on_import_segments_clicked(self) -> None:
        if self.on_annotate_import_segments is not None:
            self.on_annotate_import_segments()

    def _clear_brush_cursor(self) -> None:
        if self._brush_cursor_id is not None:
            with contextlib.suppress(tk.TclError):
                self.canvas.delete(self._brush_cursor_id)
            self._brush_cursor_id = None

    def _draw_brush_cursor(self, x_view: int, y_view: int) -> None:
        self._clear_brush_cursor()
        if self._annotate_mode != "annotate":
            return
        scale_x = (self.current_size[0] / max(1, self.images.shape[2])) * self._zoom
        r_view = max(2, int(self._brush_radius * scale_x))
        self._brush_cursor_id = self.canvas.create_oval(
            x_view - r_view,
            y_view - r_view,
            x_view + r_view,
            y_view + r_view,
            outline="cyan",
            width=1,
        )

    def _on_canvas_motion(self, event) -> None:
        if self._annotate_mode != "annotate" or self._painting:
            return
        self._draw_brush_cursor(int(event.x), int(event.y))

    def _on_left_drag(self, event) -> None:
        if self._panning:
            self._pan_motion(event)
            return
        if self._annotate_mode == "annotate":
            self._paint_at_event(event)
            return
        self.draw_box(event)

    def _on_left_release(self, event) -> None:
        if self._panning:
            self._end_pan(event)
            return
        if self._annotate_mode == "annotate":
            if self._painting:
                self._painting = False
                self._last_paint_xy = None
                if self.on_annotate_stroke_end is not None:
                    self.on_annotate_stroke_end()
            self._draw_brush_cursor(int(event.x), int(event.y))
            return
        self.end_drawing_user_rect(event)

    def _paint_at_event(self, event) -> None:
        if self._paint_target_key is None or self.on_annotate_stroke is None:
            return
        x_img, y_img = self._view_to_image_coords(int(event.x), int(event.y))
        if self._last_paint_xy is not None:
            # Stamp along path with spacing ≤ radius/2
            x0, y0 = self._last_paint_xy
            dx, dy = x_img - x0, y_img - y0
            dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
            step = max(1.0, self._brush_radius / 2.0)
            n = int(dist / step) + 1
            for i in range(1, n + 1):
                t = i / n
                xi = int(x0 + dx * t)
                yi = int(y0 + dy * t)
                self.on_annotate_stroke(
                    self._paint_target_key, yi, xi, self._brush_radius, self._annotate_tool
                )
        else:
            self.on_annotate_stroke(
                self._paint_target_key, y_img, x_img, self._brush_radius, self._annotate_tool
            )
        self._last_paint_xy = (x_img, y_img)
        self._draw_brush_cursor(int(event.x), int(event.y))

    def set_text_overlay_data(self, frame_index: int, data: list[OCRText]):
        # Creates new text overlay if one doesn't exist yet:
        if frame_index not in self.overlay_data:
            self.overlay_data[frame_index] = OverlayData()

        self.overlay_data[frame_index].ocr_texts = data
        self.remove_from_cache(frame_index)
        if frame_index == self.current_image_index:
            self.load_and_display_image(frame_index)

    def clear_text_overlays(self) -> None:
        """Remove OCR text overlays from every frame and refresh the current view."""
        for overlay in self.overlay_data.values():
            overlay.ocr_texts = []
        self.remove_from_cache(self.current_image_index)
        self.load_and_display_image(self.current_image_index)

    def get_text_overlay_data(self, frame_index: int) -> list[OCRText] | None:
        """Retrieves the text overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            return None
        return self.overlay_data[frame_index].ocr_texts

    def set_segmentation_overlay_data(self, frame_index: int, data: list[Segmentation]):
        if frame_index not in self.overlay_data:
            self.overlay_data[frame_index] = OverlayData()
        self.overlay_data[frame_index].segmentations = data
        if frame_index == self.current_image_index:  # update display
            self.remove_from_cache(frame_index)  # force re-rendering
            self.load_and_display_image(self.current_image_index)

    def set_segmentation_overlays(self, overlays: dict[int, list[Segmentation]]) -> None:
        """Apply segmentation overlays for many frames with a single refresh.

        Only invalidates touched frames (not the whole series cache) so brush
        strokes stay responsive at high zoom.
        """
        touched: set[int] = set()
        for frame_index, segmentations in overlays.items():
            if frame_index not in self.overlay_data:
                self.overlay_data[frame_index] = OverlayData()
            self.overlay_data[frame_index].segmentations = segmentations
            touched.add(frame_index)
        for frame_index in touched:
            self.remove_from_cache(frame_index)
        self.load_and_display_image(self.current_image_index)

    def get_segmentation_overlay_data(self, frame_index: int) -> list[Segmentation] | None:
        """Retrieves the segmentation overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            return None
        return self.overlay_data[frame_index].segmentations

    def set_user_rectangle_overlay_data(self, frame_index: int, data: list[UserRectangle]):
        """Sets the user rectangle overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            self.overlay_data[frame_index] = OverlayData()
        self.overlay_data[frame_index].user_rects = data
        if frame_index == self.current_image_index:  # update display
            self.remove_from_cache(frame_index)  # force re-rendering
            self.load_and_display_image(self.current_image_index)

    def get_user_rectangle_overlay_data(self, frame_index: int) -> list[UserRectangle] | None:
        """Retrieves the user rectangle overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            return None
        return self.overlay_data[frame_index].user_rects

    def set_exclude_rectangle_overlay_data(self, frame_index: int, data: list[UserRectangle]):
        """Sets OCR-exclude rectangle overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            self.overlay_data[frame_index] = OverlayData()
        self.overlay_data[frame_index].exclude_rects = data
        if frame_index == self.current_image_index:
            self.remove_from_cache(frame_index)
            self.load_and_display_image(self.current_image_index)

    def get_exclude_rectangle_overlay_data(self, frame_index: int) -> list[UserRectangle] | None:
        """Retrieves OCR-exclude rectangle overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            return None
        return self.overlay_data[frame_index].exclude_rects

    def _image_to_view_coords(self, x: int, y: int) -> tuple[int, int]:
        """Converts image coordinates to view (canvas) coordinates."""
        image_width = self.images.shape[2]
        image_height = self.images.shape[1]
        scale_x = self.current_size[0] / image_width
        scale_y = self.current_size[1] / image_height
        fit_x = x * scale_x
        fit_y = y * scale_y
        return int(fit_x * self._zoom + self._pan_x), int(fit_y * self._zoom + self._pan_y)

    def _view_to_image_coords(self, x: int, y: int) -> tuple[int, int]:
        """Converts view (canvas) coordinates to image coordinates."""
        image_width = self.images.shape[2]
        image_height = self.images.shape[1]
        scale_x = self.current_size[0] / image_width
        scale_y = self.current_size[1] / image_height
        if scale_x == 0 or scale_y == 0 or self._zoom == 0:
            return x, y
        fit_x = (x - self._pan_x) / self._zoom
        fit_y = (y - self._pan_y) / self._zoom
        return int(fit_x / scale_x), int(fit_y / scale_y)

    def _zoomed_display_size(self) -> tuple[int, int]:
        return (
            max(1, int(round(self.current_size[0] * self._zoom))),
            max(1, int(round(self.current_size[1] * self._zoom))),
        )

    def _clamp_pan(self) -> None:
        zw, zh = self._zoomed_display_size()
        cw, ch = self.current_size
        frac = self.PAN_MIN_VISIBLE_FRACTION
        self._pan_x = min(self._pan_x, cw * (1.0 - frac))
        self._pan_x = max(self._pan_x, cw * frac - zw)
        self._pan_y = min(self._pan_y, ch * (1.0 - frac))
        self._pan_y = max(self._pan_y, ch * frac - zh)

    def reset_zoom_pan(self, event=None) -> None:
        """Reset zoom/pan to fit-to-viewport identity."""
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._last_install_zoom = None
        self._last_companion_install_zoom = None
        self._refresh_viewport_transform()

    def _on_fit_key(self, event=None):
        self.reset_zoom_pan()
        return "break"

    def _on_fit_double_click(self, event=None):
        self.reset_zoom_pan()
        return "break"

    def _event_has_ctrl_or_cmd(self, event) -> bool:
        state = int(getattr(event, "state", 0) or 0)
        # Control=0x4; Command on Aqua often 0x8 (Mod1) or 0x100000.
        return bool(state & 0x4) or bool(state & 0x8) or bool(state & 0x100000)

    def _event_has_shift(self, event) -> bool:
        return bool(int(getattr(event, "state", 0) or 0) & 0x1)

    def _zoom_at_canvas(self, canvas_x: float, canvas_y: float, factor: float) -> None:
        fit_x = (canvas_x - self._pan_x) / self._zoom if self._zoom else canvas_x
        fit_y = (canvas_y - self._pan_y) / self._zoom if self._zoom else canvas_y
        new_zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, self._zoom * factor))
        self._zoom = new_zoom
        self._pan_x = canvas_x - fit_x * new_zoom
        self._pan_y = canvas_y - fit_y * new_zoom
        self._clamp_pan()
        # Magnification needs the native composite; rebuild if we only have a fit cache hit.
        if self._zoom > 1.0 and self._native_pil is None:
            self._last_install_zoom = None
            self.load_and_display_image(self.current_image_index)
            return
        self._last_install_zoom = None
        self._last_companion_install_zoom = None
        self._refresh_viewport_transform()

    def _on_zoom_wheel(self, event):
        if not self._interaction_allowed():
            return "break"
        factor = self.ZOOM_WHEEL_FACTOR if event.delta > 0 else 1.0 / self.ZOOM_WHEEL_FACTOR
        self._zoom_at_canvas(float(event.x), float(event.y), factor)
        if self._annotate_mode == "annotate":
            self._draw_brush_cursor(int(event.x), int(event.y))
        return "break"

    def _start_pan(self, event) -> None:
        if not self._interaction_allowed():
            return
        if self.drawing_rect or self.adjusting_wlww:
            return
        self._panning = True
        self._pan_start_xy = (int(event.x), int(event.y))
        self._pan_origin = (self._pan_x, self._pan_y)
        self.canvas.config(cursor="hand2")

    def _pan_motion(self, event) -> None:
        if not self._panning or self._pan_start_xy is None or self._pan_origin is None:
            return
        dx = int(event.x) - self._pan_start_xy[0]
        dy = int(event.y) - self._pan_start_xy[1]
        self._pan_x = self._pan_origin[0] + dx
        self._pan_y = self._pan_origin[1] + dy
        self._clamp_pan()
        self._refresh_viewport_transform()

    def _end_pan(self, event=None) -> None:
        if not self._panning:
            return
        self._panning = False
        self._pan_start_xy = None
        self._pan_origin = None
        if self._annotate_mode == "annotate":
            self.canvas.config(cursor="none")
        else:
            self.canvas.config(cursor="")

    def _viewport_source_pil(self, *, companion: bool = False) -> Image.Image | None:
        """PIL used for the current zoom: native when magnifying, fit otherwise."""
        if companion:
            if self._zoom > 1.0 and self._native_companion_pil is not None:
                return self._native_companion_pil
            return self._fit_companion_pil
        if self._zoom > 1.0 and self._native_pil is not None:
            return self._native_pil
        return self._fit_pil

    def _photo_from_source_pil(self, source_pil: Image.Image) -> ImageTk.PhotoImage:
        """Build the on-canvas PhotoImage.

        Magnification uses NEAREST from the source (preferably native) so 1px
        segment outlines stay crisp. Fit / shrink keeps LANCZOS.
        """
        zw, zh = self._zoomed_display_size()
        src_w, src_h = source_pil.size
        if abs(self._zoom - 1.0) < 1e-6 and (src_w, src_h) == self.current_size:
            return ImageTk.PhotoImage(source_pil)
        upscaling = zw > src_w or zh > src_h or self._zoom > 1.0
        resampling = Image.Resampling.NEAREST if upscaling else Image.Resampling.LANCZOS
        resized = source_pil.resize((zw, zh), resampling)
        photo = ImageTk.PhotoImage(resized)
        resized.close()
        return photo

    def _install_transformed_from_pil(self, fit_pil: Image.Image | None = None, *, companion: bool = False) -> None:
        """Place zoom/pan transform on canvas. ``fit_pil`` kept for API; source chosen by zoom."""
        canvas = self.companion_canvas if companion else self.canvas
        if canvas is None:
            return
        source = self._viewport_source_pil(companion=companion)
        if source is None:
            source = fit_pil
        if source is None:
            return
        item = self.companion_canvas_image_item if companion else self.canvas_image_item
        existing = self._transformed_companion_photo if companion else self._transformed_photo
        last_zoom_attr = "_last_companion_install_zoom" if companion else "_last_install_zoom"
        last_zoom = getattr(self, last_zoom_attr, None)
        if existing is not None and item is not None and last_zoom is not None and abs(last_zoom - self._zoom) < 1e-6:
            with contextlib.suppress(tk.TclError):
                canvas.coords(item, self._pan_x, self._pan_y)
                return

        photo = self._photo_from_source_pil(source)
        if companion:
            dispose_photo_image(self, self._transformed_companion_photo)
            self._transformed_companion_photo = photo
            self._last_companion_install_zoom = self._zoom
            self.companion_canvas.image = photo  # type: ignore[attr-defined]
            if self.companion_canvas_image_item is not None:
                with contextlib.suppress(tk.TclError):
                    self.companion_canvas.itemconfig(self.companion_canvas_image_item, image=photo)
                    self.companion_canvas.coords(self.companion_canvas_image_item, self._pan_x, self._pan_y)
                    return
            self.companion_canvas_image_item = self.companion_canvas.create_image(
                self._pan_x, self._pan_y, anchor="nw", image=photo
            )
            return
        dispose_photo_image(self, self._transformed_photo)
        self._transformed_photo = photo
        self._last_install_zoom = self._zoom
        self.photo_image = photo
        self.canvas.image = photo  # type: ignore[attr-defined]
        if self.canvas_image_item is not None:
            with contextlib.suppress(tk.TclError):
                self.canvas.itemconfig(self.canvas_image_item, image=photo)
                self.canvas.coords(self.canvas_image_item, self._pan_x, self._pan_y)
                return
        self.canvas_image_item = self.canvas.create_image(
            self._pan_x, self._pan_y, anchor="nw", image=photo
        )

    def _refresh_viewport_transform(self) -> None:
        """Re-place cached pixmaps with current zoom/pan (no re-windowing)."""
        if self._viewport_source_pil(companion=False) is not None:
            self._install_transformed_from_pil(companion=False)
        if self._viewport_source_pil(companion=True) is not None:
            self._install_transformed_from_pil(companion=True)
        self.update_status()

    def _screen_canvas_budget(self) -> tuple[int, int]:
        """Return max drawable (width, height) from screen budget and visible chrome."""
        max_width = int(self.winfo_screenwidth() * self.MAX_SCREEN_PERCENTAGE)
        max_height = int(self.winfo_screenheight() * self.MAX_SCREEN_PERCENTAGE)
        if self.companion_attached:
            max_width = max(1, (max_width - 8) // 2)
        with contextlib.suppress(tk.TclError):
            self.update_idletasks()
        label_reserve = 0
        for label in (self._primary_label, self._companion_label):
            if label is not None:
                height = label.winfo_height()
                if height > 1:
                    label_reserve = max(label_reserve, height + 4)
        if label_reserve:
            max_height = max(1, max_height - label_reserve)
        if self.num_images > 1 and hasattr(self, "scrollbar"):
            scroll_height = self.scrollbar.winfo_height()
            if scroll_height > 1:
                max_height = max(1, max_height - scroll_height)
        return max_width, max_height

    def viewport_size(self) -> tuple[int, int]:
        """Space available to one image canvas inside the image column."""
        self.update_idletasks()
        frame_w = max(self.image_frame.winfo_width(), 1)
        frame_h = max(self.image_frame.winfo_height(), 1)
        if frame_w <= 1 or frame_h <= 1:
            return 1, 1
        scroll_h = self.scrollbar.winfo_height() if self.num_images > 1 and hasattr(self, "scrollbar") else 0
        label_h = 0
        if self._primary_label is not None and self._primary_label.winfo_ismapped():
            label_h = self._primary_label.winfo_height() + 4
        usable_h = max(1, frame_h - scroll_h - label_h)
        if self.companion_attached:
            col_w = max(1, (frame_w - 8) // 2)
            return col_w, usable_h
        return frame_w, usable_h

    def _viewport_fits_native(self, max_width: int, max_height: int) -> bool:
        """True when the viewport can show the full native frame without scaling."""
        return max_width >= self.image_width and max_height >= self.image_height

    def _snap_to_native_if_grid_rounding(
        self,
        max_width: int,
        max_height: int,
        scaled_size: tuple[int, int],
    ) -> tuple[int, int]:
        """Use native pixels when the viewport can hold them (no upscale)."""
        if self._viewport_fits_native(max_width, max_height):
            return self.image_width, self.image_height
        return scaled_size

    def _resolve_display_size(
        self,
        max_width: int,
        max_height: int,
        *,
        allow_upscale: bool = False,
    ) -> tuple[int, int] | None:
        """Aspect-preserving display size for a viewport (never above native by default)."""
        if max_width <= 1 or max_height <= 1:
            return None
        scaled = self._calculate_scaled_size(max_width, max_height, allow_upscale=allow_upscale)
        if allow_upscale:
            return scaled
        return self._snap_to_native_if_grid_rounding(max_width, max_height, scaled)

    def view_matches_actual(self) -> bool:
        """True when on-screen pixels match native DICOM frame dimensions."""
        return self.current_size == (self.image_width, self.image_height)

    def _dimensions_label_width(self) -> int:
        """Pixels needed for the widest dimensions text this series can show.

        Reserve width for the largest upscale the viewport can reach so the RHS does
        not shift as the digit count changes while scaling.
        """
        if self.image_size_label is None:
            return 0
        max_w, max_h = self._screen_canvas_budget()
        upscale_w, upscale_h = self._calculate_scaled_size(max_w, max_h, allow_upscale=True)
        widest = _("View[{vw}x{vh}] Actual[{aw}x{ah}]").format(
            vw=upscale_w,
            vh=upscale_h,
            aw=self.image_width,
            ah=self.image_height,
        )
        with contextlib.suppress(tk.TclError, AttributeError):
            return int(self.image_size_label.cget("font").measure(widest)) + 4
        return 0

    def _viewport_from_frame_event(self, frame_width: int, frame_height: int) -> tuple[int, int]:
        """Map an image_frame Configure event to the canvas viewport."""
        scroll_h = self.scrollbar.winfo_height() if self.num_images > 1 and hasattr(self, "scrollbar") else 0
        label_h = 0
        if self._primary_label is not None and self._primary_label.winfo_ismapped():
            label_h = self._primary_label.winfo_height() + 4
        usable_h = max(1, frame_height - scroll_h - label_h)
        if self.companion_attached:
            col_w = max(1, (frame_width - 8) // 2)
            return col_w, usable_h
        return frame_width, usable_h

    def _request_viewport_fit(self, viewport: tuple[int, int] | None = None) -> None:
        """Coalesce rapid image_frame Configure events (never cancel-and-re-arm)."""
        if viewport is not None:
            self._pending_viewport_size = viewport
        if self._viewport_fit_pending:
            return
        self._viewport_fit_pending = True

        def _run() -> None:
            self._viewport_fit_pending = False
            pending_viewport = self._pending_viewport_size
            self._pending_viewport_size = None
            with contextlib.suppress(tk.TclError):
                if pending_viewport is not None:
                    self.fit_to_viewport(viewport=pending_viewport)
                else:
                    self.fit_to_viewport()

        self.after_idle(_run)

    def _on_image_frame_configure(self, event: tk.Event) -> None:
        """Repaint when the image column changes size (V18-style geometry coupling)."""
        if event.widget is not self.image_frame:
            return
        if not self._startup_complete:
            return
        if event.width <= 1 or event.height <= 1:
            return
        self._request_viewport_fit(self._viewport_from_frame_event(event.width, event.height))

    def _rhs_children(self) -> tuple[ctk.CTkBaseClass | ctk.CTkFrame, ...]:
        """Mapped RHS chrome widgets, top to bottom."""
        children = (self.histogram, self.segmentation_frame, self.control_frame)
        return tuple(child for child in children if child is not None and child.winfo_ismapped())

    def apply_fixed_chrome(self, *, refresh_histogram: bool = False, reserve_segmentation_chrome: bool = False) -> None:
        """Apply the RHS widgets' declared sizes. Never called from image resize.

        The panel itself is deliberately left at its natural size: Tk sums the children,
        which is the only measurement guaranteed to fit them.
        """
        if self.data_frame is None or self.histogram is None:
            return
        show_segmentation = (
            bool(self._segmentation_button_meta)
            or reserve_segmentation_chrome
            or bool(self._annotate_enabled)
        )
        with contextlib.suppress(tk.TclError):
            self.histogram.canvas.configure(
                width=self.HISTOGRAM_CANVAS_WIDTH,
                height=self.HISTOGRAM_CANVAS_HEIGHT,
            )
            if self._last_hist_canvas_height != self.HISTOGRAM_CANVAS_HEIGHT:
                self._last_hist_canvas_height = self.HISTOGRAM_CANVAS_HEIGHT
                if refresh_histogram:
                    self.histogram.refresh_display()
            if self.segmentation_buttons_frame is not None:
                if show_segmentation:
                    self._segmentation_scroll_height = self.SEGMENTATION_SCROLL_MAX_HEIGHT
                    if self.segmentation_frame is not None:
                        self.segmentation_frame.grid()
                    self.segmentation_buttons_frame.grid()
                    self.segmentation_buttons_frame.configure(
                        width=self.HISTOGRAM_CANVAS_WIDTH,
                        height=self._segmentation_scroll_height,
                    )
                else:
                    self._segmentation_scroll_height = 0
                    self.segmentation_buttons_frame.grid_remove()
                    if self.segmentation_frame is not None:
                        self.segmentation_frame.grid_remove()
            if self.image_size_label is not None:
                label_width = self._dimensions_label_width()
                if label_width > 0:
                    self.image_size_label.configure(width=label_width)
            if self.control_frame is not None:
                self.control_frame.grid(row=2, column=0, sticky="ew")
            self.update_idletasks()

    def chrome_fully_visible(self) -> bool:
        """True when every RHS widget fits inside the panel on both axes."""
        if self.data_frame is None or self.control_frame is None:
            return False
        self.update_idletasks()
        panel_w = self.data_frame.winfo_width()
        panel_h = self.data_frame.winfo_height()
        if panel_w <= 1 or panel_h <= 1:
            return False
        # Requested sizes, not allocated: a clipped child still reports the allocated size.
        return all(
            child.winfo_x() + child.winfo_reqwidth() <= panel_w + 2
            and child.winfo_y() + child.winfo_reqheight() <= panel_h + 2
            for child in self._rhs_children()
        )

    def set_display_size(self, size: tuple[int, int], *, refresh_histogram: bool = False) -> bool:
        """Resize canvases to ``size`` and repaint if changed. Does not touch RHS chrome."""
        if size[0] <= 0 or size[1] <= 0:
            return False
        if size == self.current_size and self.canvas_image_item is not None:
            # Ensure widget geometry matches the fit size; no pixel reload needed.
            self.canvas.config(width=size[0], height=size[1])
            if self.companion_canvas is not None:
                self.companion_canvas.config(width=size[0], height=size[1])
            self.update_idletasks()
            return False
        old_w, old_h = self.current_size
        self.current_size = size
        if old_w > 0 and old_h > 0 and (size[0] != old_w or size[1] != old_h):
            self._pan_x *= size[0] / old_w
            self._pan_y *= size[1] / old_h
            self._clamp_pan()
        self.canvas.config(width=size[0], height=size[1])
        if self.companion_canvas is not None:
            self.companion_canvas.config(width=size[0], height=size[1])
        self._companion_cache.clear()
        self.load_and_display_image(self.current_image_index)
        if self.histogram is not None and not self.companion_attached:
            self.histogram.update_image(self._display_pixels(self.current_image_index))
            if refresh_histogram:
                self.histogram.refresh_display()
        self.update_status()
        return True

    def fit_to_viewport(
        self,
        *,
        force: bool = False,
        viewport: tuple[int, int] | None = None,
        refresh_histogram: bool = False,
        fill_viewport: bool = True,
    ) -> bool:
        """Fit the canvas to the image column, preserving aspect ratio.

        When ``fill_viewport`` is True the image scales up to fill the viewport (including
        past native). Startup uses ``fill_viewport=False`` so the first paint stays 1:1
        when the window already fits the native frame.
        """
        max_width, max_height = viewport if viewport is not None else self.viewport_size()
        if max_width <= 1 or max_height <= 1:
            max_width, max_height = self._screen_canvas_budget()
        new_size = self._resolve_display_size(max_width, max_height, allow_upscale=fill_viewport)
        if new_size is None:
            return False
        viewport_size = (max_width, max_height)
        if (
            not force
            and viewport_size == self._last_viewport_size
            and new_size == self.current_size
            and self.canvas_image_item is not None
        ):
            return False
        self._last_viewport_size = viewport_size
        if not force and new_size == self.current_size and self.canvas_image_item is not None:
            return False
        return self.set_display_size(new_size, refresh_histogram=refresh_histogram)

    def _calculate_scaled_size(
        self,
        max_width: int,
        max_height: int,
        *,
        allow_upscale: bool = True,
    ) -> tuple[int, int]:
        """Calculates the scaled size to fit within max dimensions, preserving aspect ratio."""
        if not allow_upscale and self.image_width <= max_width and self.image_height <= max_height:
            return self.image_width, self.image_height

        aspect_ratio = self.image_width / self.image_height
        if self.image_width / max_width > self.image_height / max_height:
            new_width = max_width
            new_height = int(new_width / aspect_ratio)
        else:
            new_height = max_height
            new_width = int(new_height * aspect_ratio)
        return new_width, new_height

    def toggle_layer(self, layer_name: LayerType, is_active: bool):
        if is_active:
            self.active_layers.add(layer_name)
        else:
            self.active_layers.discard(layer_name)
        self.load_and_display_image(self.current_image_index)

    def refresh_current_image(self):
        self.remove_from_cache(self.current_image_index)  # Use the method that closes PIL image
        self._companion_cache.clear()
        self.load_and_display_image(self.current_image_index)

    def mouse_enter(self, event):
        logger.debug("mouse_enter")
        self.canvas.focus_set()

    def _bind_slice_navigation_pointer(self, widget: tk.Misc) -> None:
        """Scroll wheel and keyboard slice navigation when the pointer is over a widget."""
        widget.bind("<MouseWheel>", self.on_mousewheel)
        widget.bind("<Enter>", self.mouse_enter)
        if self.num_images > 1:
            self._bind_slice_navigation_keys(widget)

    def _bind_slice_navigation_keys(self, widget: tk.Misc) -> None:
        """Arrow / page keys change the current slice (same mapping as scrollbar)."""
        widget.bind("<Left>", self.prev_image)
        widget.bind("<Right>", self.next_image)
        widget.bind("<Up>", self.change_image_up)
        widget.bind("<Down>", self.change_image_down)
        widget.bind("<Prior>", self.change_image_prior)
        widget.bind("<Next>", self.change_image_next)
        widget.bind("<Home>", self.change_image_home)
        widget.bind("<End>", self.change_image_end)

    def _handle_histogram_update(self, wl: float, ww: float):
        """Callback function called by Histogram widget when WL/WW changes interactively."""
        logger.debug(f"Received WL/WW update from histogram: WL={wl:.1f}, WW={ww:.1f}")
        wl_changed = abs(wl - self.current_wl) > 0.01
        ww_clamped = max(1.0, ww)
        ww_changed = abs(ww_clamped - self.current_ww) > 0.01

        if wl_changed or ww_changed:
            self.current_wl = wl
            self.current_ww = ww_clamped
            self.refresh_current_image()

    def get_dimensions_text(self) -> str:
        # View = on-screen pixel dimensions (current_size); Actual = native DICOM frame size.
        zoom_pct = int(round(self._zoom * 100))
        base = _("View[{vw}x{vh}] Actual[{aw}x{ah}]").format(
            vw=self.current_size[0],
            vh=self.current_size[1],
            aw=self.images.shape[2],
            ah=self.images.shape[1],
        )
        if abs(self._zoom - 1.0) < 1e-3:
            return base
        return f"{base}  Zoom {zoom_pct}%"

    def update_status(self):
        if self.projection_label is not None:
            self.projection_label.configure(text=self.get_projection_label())
        if self.image_number_label is not None:
            self.image_number_label.configure(text=f"{self.current_image_index + 1}/{self.num_images}")
        if self.image_size_label is not None:
            self.image_size_label.configure(text=self.get_dimensions_text())

    def get_projection_label(self) -> str:
        if self.companion_attached:
            return ""
        if self._is_projection_mode():
            match self._projection_mode:
                case "min":
                    return _("MIN PROJECTION")
                case "mean":
                    return _("MEAN PROJECTION")
                case "max":
                    return _("MAX PROJECTION")
        return ""

    @classmethod
    def _draw_dotted_rectangle(
        cls,
        image: np.ndarray,
        pt1: tuple[int, int],
        pt2: tuple[int, int],
        color: tuple[int, int, int],
        *,
        thickness: int = 2,
        dash: int | None = None,
        gap: int | None = None,
    ) -> None:
        """Draw a hollow dotted rectangle (no fill) onto an OpenCV BGR overlay."""
        x1, y1 = pt1
        x2, y2 = pt2
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        dash_len = dash if dash is not None else cls.EXCLUDE_RECT_DASH
        gap_len = gap if gap is not None else cls.EXCLUDE_RECT_GAP
        segment = max(1, dash_len)
        space = max(1, gap_len)

        def _dash_line(ax: int, ay: int, bx: int, by: int) -> None:
            length = int(np.hypot(bx - ax, by - ay))
            if length <= 0:
                return
            for start in range(0, length + 1, segment + space):
                end = min(start + segment, length)
                t0 = start / length
                t1 = end / length
                p0 = (int(round(ax + (bx - ax) * t0)), int(round(ay + (by - ay) * t0)))
                p1 = (int(round(ax + (bx - ax) * t1)), int(round(ay + (by - ay) * t1)))
                cv2.line(image, p0, p1, color, thickness, lineType=cv2.LINE_AA)

        _dash_line(x1, y1, x2, y1)
        _dash_line(x2, y1, x2, y2)
        _dash_line(x2, y2, x1, y2)
        _dash_line(x1, y2, x1, y1)

    def _render_overlays(self, frame_ndx: int) -> np.ndarray:
        """Renders all active overlays for specified frame."""
        if self.images is None or not (0 <= frame_ndx < self.num_images):
            return np.zeros((1, 1, 3), dtype=np.uint8)

        frame_height, frame_width = self.images[frame_ndx].shape[:2]
        combined_overlay = np.zeros((frame_height, frame_width, 3), dtype=np.uint8)
        if frame_ndx not in self.overlay_data:
            return combined_overlay

        overlay_data: OverlayData = self.overlay_data[frame_ndx]

        for layer_name in self.active_layers:
            match layer_name:
                case LayerType.TEXT:
                    if overlay_data.ocr_texts:
                        for text_data in overlay_data.ocr_texts:
                            x1, y1, x2, y2 = text_data.get_bounding_box()
                            cv2.rectangle(
                                combined_overlay,
                                (x1, y1),
                                (x2, y2),
                                self.TEXT_BOX_COLOR_BGR,
                                2,
                            )

                case LayerType.USER_RECT:
                    if overlay_data.user_rects:
                        for rect in overlay_data.user_rects:
                            x1, y1, x2, y2 = rect.get_bounding_box()
                            cv2.rectangle(
                                combined_overlay,
                                (x1, y1),
                                (x2, y2),
                                self.USER_RECT_COLOR_BGR,
                                2,
                            )

                case LayerType.EXCLUDE_RECT:
                    if overlay_data.exclude_rects:
                        for rect in overlay_data.exclude_rects:
                            x1, y1, x2, y2 = rect.get_bounding_box()
                            self._draw_dotted_rectangle(
                                combined_overlay,
                                (x1, y1),
                                (x2, y2),
                                self.EXCLUDE_RECT_COLOR_BGR,
                                thickness=2,
                            )

                case LayerType.SEGMENTATIONS:
                    if overlay_data.segmentations:
                        seg_layer = render_segmentations_overlay(
                            frame_height,
                            frame_width,
                            overlay_data.segmentations,
                            default_color_bgr=self.segmentation_overlay_color,
                        )
                        # Combine with other layers already drawn on combined_overlay.
                        mask = seg_layer.max(axis=2) > 0
                        combined_overlay[mask] = seg_layer[mask]

                case _:
                    logger.warning("Rendering not implemented for layer type: %s", layer_name)

        return combined_overlay

    def _composite_overlay(self, image_array: np.ndarray, rendered_overlay: np.ndarray) -> np.ndarray:
        if not np.any(rendered_overlay):
            return image_array
        mask = rendered_overlay.max(axis=2) > 0
        if not np.any(mask):
            return image_array
        if self.segmentation_overlay_alpha >= 1.0:
            # Opaque replace — never cv2.add (adds CT intensity into outline colors and
            # shifts hues, e.g. liver orange ↔ yellow on bright parenchyma).
            composited = image_array.copy()
            composited[mask] = rendered_overlay[mask]
            return composited

        blended = image_array.astype(np.float32)
        overlay = rendered_overlay.astype(np.float32)
        alpha = self.segmentation_overlay_alpha
        blended[mask] = blended[mask] * (1.0 - alpha) + overlay[mask] * alpha
        return np.clip(blended, 0, 255).astype(np.uint8)

    def _opencv_frame(self, image_array: np.ndarray) -> np.ndarray:
        """Convert series-buffer pixels to BGR for OpenCV overlay compositing."""
        if self.is_color and image_array.ndim == 3 and image_array.shape[-1] == 3:
            return cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
        return image_array

    def _pil_frame(self, image_array: np.ndarray) -> np.ndarray:
        """Convert OpenCV BGR composited frames to RGB for PIL/Tk.

        ``apply_windowing`` returns BGR for grayscale CT; overlays are drawn in BGR.
        Without this conversion, red overlays appear blue/purple on mono series.
        """
        if image_array.ndim == 3 and image_array.shape[-1] == 3:
            return cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB)
        return image_array

    def _frame_has_composited_overlay(self, frame_ndx: int) -> bool:
        if frame_ndx not in self.overlay_data:
            return False
        overlay = self.overlay_data[frame_ndx]
        return bool(overlay.ocr_texts or overlay.segmentations or overlay.user_rects or overlay.exclude_rects)

    def _install_canvas_image(self, photo_image: ImageTk.PhotoImage) -> None:
        """Show a pixmap on the canvas without delete/recreate flicker when the item already exists."""
        self.photo_image = photo_image
        self.canvas.image = photo_image  # type: ignore[attr-defined]
        if self.canvas_image_item is not None:
            with contextlib.suppress(tk.TclError):
                self.canvas.itemconfig(self.canvas_image_item, image=photo_image)
                self.canvas.coords(self.canvas_image_item, self._pan_x, self._pan_y)
                return
        self.canvas_image_item = self.canvas.create_image(
            self._pan_x, self._pan_y, anchor="nw", image=photo_image
        )

    def load_and_display_image(self, frame_ndx: int):
        logger.debug(f"Loading and displaying image at index: {frame_ndx}")
        if not (0 <= frame_ndx < self.num_images) or self.images is None:
            logger.error(f"Invalid frame index: {frame_ndx}")
            return

        display_pixels = self._display_pixels(frame_ndx)
        use_cache = not self._is_projection_mode()
        # Fit-sized cache is LANCZOS-softened — never use it when magnifying.
        can_use_fit_cache = use_cache and self._zoom <= 1.0

        # Use Cache (skip when overlays must be composited — cache stores pre-overlay pixels).
        if (
            can_use_fit_cache
            and frame_ndx in self.image_cache
            and not self._frame_has_composited_overlay(frame_ndx)
        ):
            cached_image, cached_pil, cached_size = self.image_cache[frame_ndx]
            if cached_size == self.current_size:
                self._fit_pil = cached_pil
                self._last_install_zoom = None
                self._install_transformed_from_pil(companion=False)
                if self.current_image_index != frame_ndx and self.histogram is not None and not self.companion_attached:
                    self.histogram.update_image(display_pixels)
                self.current_image_index = frame_ndx
                self._load_companion_display(frame_ndx)
                self.update_scrollbar()
                self.update_status()
                return

        if self.current_image_index != frame_ndx and self.histogram is not None and not self.companion_attached:
            self.histogram.update_image(display_pixels)

        image_array = apply_windowing(self.current_wl, self.current_ww, display_pixels.copy())
        if self.is_color:
            image_array = self._opencv_frame(image_array)
        if not self._is_projection_mode():
            rendered_overlay = self._render_overlays(frame_ndx)
            image_array = self._composite_overlay(image_array, rendered_overlay)

        # Native RGB composite — source of truth for crisp NEAREST magnification.
        native_pil = Image.fromarray(self._pil_frame(image_array))
        if self._native_pil is not None and hasattr(self._native_pil, "close"):
            with contextlib.suppress(Exception):
                self._native_pil.close()
        self._native_pil = native_pil.copy()
        del image_array

        # Fit pixmap for zoom==1 and for returning to fit without full recompute.
        image_pil_resized = native_pil.resize(self.current_size, Image.Resampling.LANCZOS)
        native_pil.close()
        self.current_size = image_pil_resized.size
        if self._fit_pil is not None and hasattr(self._fit_pil, "close"):
            with contextlib.suppress(Exception):
                # Don't close if it's the same object still referenced by cache.
                if self._fit_pil is not image_pil_resized and not any(
                    entry[1] is self._fit_pil for entry in self.image_cache.values()
                ):
                    self._fit_pil.close()
        self._fit_pil = image_pil_resized.copy()
        self._last_install_zoom = None
        self._install_transformed_from_pil(companion=False)

        # Caching: Store BOTH PhotoImage & resized PIL.Image (slice frames only)
        if not self._is_projection_mode():
            fit_photo = ImageTk.PhotoImage(image_pil_resized)
            self.add_to_cache(frame_ndx, fit_photo, image_pil_resized)
        self.current_image_index = frame_ndx
        self._load_companion_display(frame_ndx)
        if self.num_images > 1:
            self.update_scrollbar()
        self.update_status()

    # Cache functions:
    def add_to_cache(self, index, photo_image, pil_image):  # Modified signature
        """Adds the PhotoImage, PIL Image and its size to the cache."""
        self.image_cache[index] = (photo_image, pil_image, self.current_size)  # Store PIL image
        if len(self.image_cache) > self.CACHE_SIZE:
            self.manage_cache()

    def remove_from_cache(self, index):
        if index not in self.image_cache:
            logger.debug(f"index: {index} not in image_cache")
            return
        photo_image, pil_image, __ = self.image_cache.pop(index)
        dispose_photo_image(self, photo_image)
        if hasattr(pil_image, "close"):
            pil_image.close()

    def manage_cache(self):
        """Manages the cache, removing the oldest entry if it's full."""
        while len(self.image_cache) > self.CACHE_SIZE:
            oldest_key = min(self.image_cache.keys())
            self.remove_from_cache(oldest_key)

    def clear_cache(self):
        """Clear cached PhotoImage / PIL entries on the main thread."""
        for __, (photo_image, pil_image, *__) in list(self.image_cache.items()):
            dispose_photo_image(self, photo_image)
            if hasattr(pil_image, "close"):
                pil_image.close()

        self.image_cache.clear()
        for index in list(self._companion_cache):
            self._remove_from_companion_cache(index)

    def release_resources(self) -> None:
        """Cancel playback and drop pixel caches without destroying widgets."""
        if self.histogram is not None:
            self.histogram.release_resources()
        if self.after_id:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self.after_id)
            self.after_id = None
        self.playing = False
        self.detach_companion_stack()
        self.clear_cache()
        dispose_photo_image(self, self.photo_image)
        dispose_photo_image(self, self._transformed_photo)
        dispose_photo_image(self, self._transformed_companion_photo)
        self._transformed_photo = None
        self._transformed_companion_photo = None
        self._fit_pil = None
        self._fit_companion_pil = None
        self._native_pil = None
        self._native_companion_pil = None
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        with contextlib.suppress(tk.TclError, AttributeError):
            if self.canvas_image_item is not None:
                self.canvas.delete(self.canvas_image_item)
                self.canvas_image_item = None
            if self.companion_canvas is not None and self.companion_canvas_image_item is not None:
                self.companion_canvas.delete(self.companion_canvas_image_item)
                self.companion_canvas_image_item = None
        self.photo_image = None
        with contextlib.suppress(AttributeError):
            self.canvas.image = None  # type: ignore[attr-defined]
        with contextlib.suppress(AttributeError):
            if self.companion_canvas is not None:
                self.companion_canvas.image = None  # type: ignore[attr-defined]
        self.images = None  # type: ignore[assignment]
        self._companion_images = None
        self.overlay_data.clear()

    # ImageView Event Handlers:
    def on_mousewheel(self, event):
        if not self._interaction_allowed():
            return
        if self._event_has_ctrl_or_cmd(event):
            return self._on_zoom_wheel(event)
        if self._annotate_mode == "annotate":
            # Plain wheel still nudges brush; Shift+wheel scrolls slices (Ctrl+wheel zooms).
            if not self._event_has_shift(event):
                delta = 1 if event.delta > 0 else -1
                self._nudge_brush(delta)
                self._draw_brush_cursor(int(getattr(event, "x", 0)), int(getattr(event, "y", 0)))
                return
        if event.delta > 0:
            self.change_image(self.current_image_index - 1)
        else:
            self.change_image(self.current_image_index + 1)

    def prev_image(self, event):
        self.change_image(self.current_image_index - 1)

    def next_image(self, event):
        self.change_image(self.current_image_index + 1)

    def change_image(self, new_index):
        if not self._startup_complete or not self._interaction_allowed() or self.images is None:
            return
        if 0 <= new_index < self.num_images:
            previous_index = self.current_image_index
            self.load_and_display_image(new_index)
            if not self._suppress_callbacks and self.on_slice_index_changed is not None and new_index != previous_index:
                self.on_slice_index_changed(new_index)

    def change_image_home(self, event):
        self.change_image(0)

    def change_image_end(self, event):
        self.change_image(self.num_images - 1)

    def change_image_next(self, event):
        self.change_image(self.current_image_index + self.large_jump)

    def change_image_prior(self, event):
        self.change_image(self.current_image_index - self.large_jump)

    def change_image_up(self, event):
        self.change_image(self.current_image_index + self.small_jump)

    def change_image_down(self, event):
        self.change_image(self.current_image_index - self.small_jump)

    def update_scrollbar(self):
        if not hasattr(self, "scrollbar") or self.num_images <= 1:
            return
        start = self.current_image_index / self.num_images
        end = (self.current_image_index + 1) / self.num_images
        self._scrollbar_update_depth += 1
        try:
            self.scrollbar.set(start, end)
        finally:
            self._scrollbar_update_depth -= 1

    def scroll_handler(self, *args):
        if not self._startup_complete:
            return
        if self._scrollbar_updates_suppressed or self._scrollbar_update_depth > 0:
            return
        if not self._interaction_allowed():
            return
        command = args[0]
        if command == "moveto":
            position = float(args[1])
            new_index = int(position * self.num_images)
            self.change_image(new_index)
        elif command == "scroll":
            value, unit = float(args[1]), args[2]
            if unit == "units":
                self.change_image(self.current_image_index + int(value))
            elif unit == "pages":
                self.change_image(self.current_image_index + int(value * self.num_images * 0.1))

    def change_fps(self, value):
        self.fps = int(value)
        self.play_delay = int(1000 / self.fps)
        if hasattr(self, "fps_slider_label"):
            self.fps_slider_label.configure(text=f"{self.fps} fps")
        if self.playing and self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = self.after(self.play_delay, self.play_loop)

    def _stop_playback(self) -> None:
        self.playing = False
        if hasattr(self, "toggle_button"):
            with contextlib.suppress(tk.TclError):
                self.toggle_button.configure(image=self.ctk_play_icon)
        if self.after_id:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self.after_id)
            self.after_id = None

    def toggle_play(self, event=None):
        if not self._interaction_allowed():
            return
        self.playing = not self.playing
        if self.playing:
            if hasattr(self, "toggle_button"):
                self.toggle_button.configure(image=self.ctk_pause_icon)
            self.play_loop()
        else:
            self._stop_playback()

    def play_loop(self):
        if self.playing:
            self.next_image(None)
            self.update_status()
            if self.current_image_index == self.num_images - 1:
                self.current_image_index = 0  # Loop back to the start
            self.after_id = self.after(self.play_delay, self.play_loop)

    def _find_hit_object(self, x_view: int, y_view: int, objects: list) -> int | None:
        """
        Checks if view coordinates hit any object in the list with a get_bounding_box method.

        Args:
            x_view: The x-coordinate in view space.
            y_view: The y-coordinate in view space.
            objects: A list of objects (e.g., OCRText, Rectangle) that have
                     a get_bounding_box() method returning (x1, y1, x2, y2)
                     in *image* coordinates.

        Returns:
            Index of hit object in list otherwise None
        """
        if not objects:
            return None

        for index, obj in enumerate(objects):
            try:
                x1_img, y1_img, x2_img, y2_img = obj.get_bounding_box()
                # Convert bounding box to view coordinates for hit test
                x1_view, y1_view = self._image_to_view_coords(x1_img, y1_img)
                x2_view, y2_view = self._image_to_view_coords(x2_img, y2_img)

                if x1_view <= x_view <= x2_view and y1_view <= y_view <= y2_view:
                    return index
            except AttributeError:
                logger.warning(f"Object {obj} in list lacks get_bounding_box method.")
                continue  # Skip objects without the required method

        return None

    # Overlay editing event handlers:
    def _on_left_click(self, event):
        """
        Handles left-clicks:
        1. Checks for hits on TEXT boxes.
        2. Checks for hits on USER_RECTANGLES boxes.
        3. If no hits, initiates drawing a new user rect
           else remove hit object from corresponding overlay
        4. If current image is a projection in a series only allow user rect drawing if propagate_overlays is true
        """
        if not self._interaction_allowed():
            return
        if not self.enable_interactive_editing:
            return
        if self.playing:
            return

        if self._event_has_shift(event):
            self._start_pan(event)
            return

        if self._annotate_mode == "annotate":
            self._painting = True
            self._last_paint_xy = None
            self._paint_at_event(event)
            return

        x, y = int(event.x), int(event.y)  # View coordinates

        # Check Text Overlay:
        hit = False
        for i in range(self.num_images):
            if not self.propagate_overlays and i != self.current_image_index:
                continue
            if i not in self.overlay_data:
                continue
            ocr_texts_overlay_data = self.overlay_data[i].ocr_texts
            ocr_text_ndx = self._find_hit_object(x, y, ocr_texts_overlay_data)
            if ocr_text_ndx is None:
                continue
            hit = True
            if i == self.current_image_index and self.add_to_whitelist_callback:
                self.add_to_whitelist_callback(ocr_texts_overlay_data[ocr_text_ndx].text)
            del ocr_texts_overlay_data[ocr_text_ndx]

        if hit:
            logging.info(f"Remove OCR Text at {x}, {y}, propagate={self.propagate_overlays}")
            if self.propagate_overlays:
                self.clear_cache()
            self.refresh_current_image()
            return

        # Check Exclude Rectangle Overlay (white dotted keepers):
        hit = False
        for i in range(self.num_images):
            if not self.propagate_overlays and i != self.current_image_index:
                continue
            if i not in self.overlay_data:
                continue
            exclude_overlay_data = self.overlay_data[i].exclude_rects
            rect_ndx = self._find_hit_object(x, y, exclude_overlay_data)
            if rect_ndx is None:
                continue
            hit = True
            del exclude_overlay_data[rect_ndx]

        if hit:
            logging.info(f"Remove Exclude Rectangle at {x}, {y}, propagate={self.propagate_overlays}")
            if self.propagate_overlays:
                self.clear_cache()
            self.refresh_current_image()
            return

        # Check User Rectangle Overlay:
        hit = False
        for i in range(self.num_images):
            if not self.propagate_overlays and i != self.current_image_index:
                continue
            if i not in self.overlay_data:
                continue
            user_rect_overlay_data = self.overlay_data[i].user_rects
            rect_ndx = self._find_hit_object(x, y, user_rect_overlay_data)
            if rect_ndx is None:
                continue
            hit = True
            del user_rect_overlay_data[rect_ndx]

        if hit:
            logging.info(f"Remove User Rectangle at {x}, {y}, propagate={self.propagate_overlays}")
            if self.propagate_overlays:
                self.clear_cache()
            self.refresh_current_image()
            return

        if self._is_projection_mode():
            logger.warning("User rectangles are not permitted while viewing projections")
            return

        # Otherwise start user drawing rectangle action:
        self.start_drawing_user_rect(event)

    def start_drawing_user_rect(self, event):
        """Starts drawing a new user definted rectangle"""
        self.drawing_rect = True
        self.start_x = int(event.x)  # Store *CANVAS (VIEW)* coordinates
        self.start_y = int(event.y)
        # Ensure any previous temporary rectangle is gone (safety check)
        if self.temp_rect_id:
            self.canvas.delete(self.temp_rect_id)
            self.temp_rect_id = None
        logger.info(f"Drawing User Rectangle start x:{self.start_x} y:{self.start_y}")
        self.canvas.config(cursor="sizing")

    def draw_box(self, event):
        """
        Updates the visual representation of the box being drawn temporarily.
        """
        # Only run if we are currently in the drawing state
        if not self.drawing_rect or self.start_x is None or self.start_y is None:
            return

        # Get current coordinates in CANVAS (VIEW) space
        current_x = int(event.x)
        current_y = int(event.y)

        # Delete the previous temporary rectangle item, if it exists
        if self.temp_rect_id:
            self.canvas.delete(self.temp_rect_id)

        # Create a new temporary rectangle item on the canvas
        # Use canvas coordinates directly. Choose a distinct outline color.
        self.temp_rect_id = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            current_x,
            current_y,
            outline="cyan",  # Use a visible color like blue or cyan
            width=1,
            # Consider adding 'dash=(2, 4)' for a dashed line effect
        )

    def end_drawing_user_rect(self, event):
        """
        Finalizes drawing: removes temp rect, adds permanent rect to overlay_data,
        and triggers a full redraw of the background image item.
        """
        # --- Check if drawing was valid ---
        if not self.drawing_rect:
            self.canvas.config(cursor="")
            return

        if self.start_x is None or self.start_y is None:
            logger.warning("Invalid drawing state, start coordinate invalid")
            self.canvas.config(cursor="")
            return

        # Get final coordinates before resetting state
        end_x = int(event.x)
        end_y = int(event.y)

        # --- Canvas Cleanup ---
        # Delete the final temporary rectangle item from the canvas
        if self.temp_rect_id:
            self.canvas.delete(self.temp_rect_id)
            self.temp_rect_id = None

        # Reset drawing state *after* getting coordinates but *before* processing
        self.drawing_rect = False
        local_start_x = self.start_x  # Copy start coords before clearing
        local_start_y = self.start_y
        self.start_x = None
        self.start_y = None

        # --- Create Permanent Box in Image Coordinates ---
        # Convert the start (view) and end (view) coordinates to image coordinates.
        try:
            x1_img, y1_img = self._view_to_image_coords(local_start_x, local_start_y)
            x2_img, y2_img = self._view_to_image_coords(end_x, end_y)
        except Exception as e:  # Catch potential errors during conversion
            logger.error(f"Error converting view coords to image coords: {e}")
            self.canvas.config(cursor="")
            return

        # Ensure correct ordering
        final_x1 = min(x1_img, x2_img)
        final_y1 = min(y1_img, y2_img)
        final_x2 = max(x1_img, x2_img)
        final_y2 = max(y1_img, y2_img)

        # --- Snapping Logic ---
        snap_threshold = 5  # Pixels in VIEW coordinates
        view_width, view_height = self.current_size

        # Check X coordinates against view boundaries
        if local_start_x <= snap_threshold or end_x <= snap_threshold:
            final_x1 = 0  # Snap left edge to image left edge
            logger.debug("Snapping X1 to image edge (0)")
        if local_start_x >= view_width - snap_threshold or end_x >= view_width - snap_threshold:
            final_x2 = self.image_width  # Snap right edge to image right edge
            logger.debug(f"Snapping X2 to image edge ({self.image_width})")

        # Check Y coordinates against view boundaries
        if local_start_y <= snap_threshold or end_y <= snap_threshold:
            final_y1 = 0  # Snap top edge to image top edge
            logger.debug("Snapping Y1 to image edge (0)")
        if local_start_y >= view_height - snap_threshold or end_y >= view_height - snap_threshold:
            final_y2 = self.image_height  # Snap bottom edge to image bottom edge
            logger.debug(f"Snapping Y2 to image edge ({self.image_height})")

        # --- Add to Overlay Data ---
        # Check for minimum box size
        min_width = 5
        min_height = 5
        if abs(final_x1 - final_x2) < min_width or abs(final_y1 - final_y2) < min_height:
            logger.info("ImageViewer: Drawn rect too small, not adding.")
            # Need to redraw to remove the temporary rectangle even if not adding
            self.refresh_current_image()
            self.canvas.config(cursor="")
            return

        new_user_rect = UserRectangle(
            top_left=(final_x1, final_y1),
            bottom_right=(final_x2, final_y2),
        )

        # --- Add User Rectangle to Overlay Data from SeriesView (edit context sensitive) ---
        logger.info(
            f"Add user rectangle to overlay data for current frame: {new_user_rect.top_left} -> {new_user_rect.bottom_right}, propagate: {self.propagate_overlays}"
        )
        for i in range(self.num_images):
            if not self.propagate_overlays and i != self.current_image_index:
                continue
            if i in self.overlay_data:
                self.overlay_data[i].user_rects.append(new_user_rect)
            else:
                self.overlay_data[i] = OverlayData()
                self.overlay_data[i].user_rects = [new_user_rect]

        if self.propagate_overlays:
            self.clear_cache()

        self.canvas.config(cursor="")
        self.refresh_current_image()

    # --- WW/WL (Brightness/Contrast) Calculation ---
    def _update_derived_alpha_beta(self):
        """
        Calculates the internal alpha and beta values used by cv2.convertScaleAbs
        based on the current user-facing self.current_ww and self.current_wl.
        """
        # Ensure WW is at least 1 to avoid division by zero and extreme alpha
        ww_safe = max(1.0, self.current_ww)
        self._derived_alpha = 255.0 / ww_safe
        # Calculate beta so that the pixel value 'wl' maps to the middle
        # of the output range (127.5 for 0-255)
        self._derived_beta = int(127.5 - (self._derived_alpha * self.current_wl))

    # --- WW/WL Adjustment Event Handlers ---
    def _start_adjust_display(self, event):
        """Starts WL/WW adjustment. (Bound to logical right-button press)"""
        if not self._interaction_allowed():
            return
        if self.drawing_rect:
            return  # Ignore if drawing
        logger.debug("Starting WL/WW adjust")
        self.adjusting_wlww = True
        self.adjust_start_x = int(event.x)
        self.adjust_start_y = int(event.y)
        self.initial_wl = self.current_wl
        self.initial_ww = self.current_ww
        self.canvas.config(cursor="fleur")

    def _adjust_display(self, event):
        """Adjusts WL(U/D)/WW(L/R) during drag. (Bound to logical right-button motion)"""
        if not self.adjusting_wlww or self.adjust_start_x is None or self.adjust_start_y is None:
            return

        current_x = int(event.x)
        current_y = int(event.y)
        delta_x = current_x - self.adjust_start_x
        delta_y = current_y - self.adjust_start_y  # Down = Positive Delta Y

        # --- Calculate New WW/WL based on Mouse Mapping ---
        # Adjust sensitivity based on data range? For now, use defaults.
        wl_sensitivity = self.DEFAULT_WL_SENSITIVITY
        ww_sensitivity = self.DEFAULT_WW_SENSITIVITY

        # WL (Brightness): Up/Down drag -> Up = Brighter (Higher WL)
        self.current_wl = self.initial_wl + (-delta_y / wl_sensitivity)

        # WW (Contrast): Left/Right drag -> Left = Less contrast (Higher WW)
        self.current_ww = self.initial_ww + (delta_x / ww_sensitivity)

        # Clamp WW (must be > 0)
        self.current_ww = max(1.0, self.current_ww)
        # Optional: Clamp WL based on data range if known, otherwise allow free range
        # self.current_wl = max(some_min, min(some_max, self.current_wl))

        logger.debug(f"Adjusting Display: WL={self.current_wl:.1f}, WW={self.current_ww:.1f}")

        # --- Update Histogram ---
        if self.histogram is not None:
            self.histogram.set_wlww(self.current_wl, self.current_ww)

        # --- Trigger Redraw ---
        self.refresh_current_image()

    def _end_adjust_display(self, event):
        """Ends WL/WW adjustment. (Bound to logical right-button release)"""
        if not self.adjusting_wlww:
            return
        logger.debug("Ending WL/WW adjust")
        self.adjusting_wlww = False
        self.adjust_start_x = None
        self.adjust_start_y = None
        # Final redraw to potentially update cache with final WW/WL settings
        self.refresh_current_image()
        self.canvas.config(cursor="")
        if not self._suppress_callbacks and self.on_wlww_changed is not None:
            self.on_wlww_changed(self.current_wl, self.current_ww)

    def destroy(self):
        """Override destroy to properly clean up resources."""
        self.release_resources()
        super().destroy()
