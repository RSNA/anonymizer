import contextlib
import logging
import queue
import threading
import tkinter as tk
from math import ceil
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from anonymizer.controller.phi.phi_io import PHI_IndexRecord
from anonymizer.controller.project import ProjectController
from anonymizer.controller.series.create_projections import (
    PROJECTION_FILENAME,
    Projection,
    ProjectionImageSize,
    ProjectionImageSizeConfig,
    create_projection_from_series,
)
from anonymizer.utils.modalities import ContentClass, Modality, get_modality_catalog
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel, refresh_app_window_menu
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.tooltip import bind_hover_tooltip
from anonymizer.view.reports.open_workspace import open_series_workspace

logger = logging.getLogger(__name__)


def format_projection_view_title(
    phi_records: list[PHI_IndexRecord],
    total_series: int,
    pages: int,
) -> str:
    """Build the ProjectionView window title."""
    if len(phi_records) == 1:
        record = phi_records[0]
        title = _("View") + " " + record.tree_label()
        anon_id = (record.anon_patient_id or "").strip()
        if anon_id:
            title = title + f" {anon_id}"
        title = title + " " + _("with") + f" {total_series} " + _("Series")
    else:
        title = (
            _("View")
            + f" {len(phi_records)} "
            + _("Studies")
            + " "
            + _("with")
            + f" {total_series} "
            + _("Series")
        )
    if pages > 1:
        title = title + " " + _("over") + f" {pages} " + _("Pages")
    return title


def projection_study_uids(phi_records: list[PHI_IndexRecord]) -> tuple[str, ...]:
    """Stable study UID ordering for comparing ProjectionView requests."""
    return tuple(sorted(record.anon_study_uid for record in phi_records))


def study_has_projection_series(phi_record: PHI_IndexRecord) -> bool:
    """True when the study has at least one non-report series for Projection View."""

    series = getattr(phi_record, "series", None) or []
    if series:
        return any(
            (m := Modality.from_code(s.modality)) is not None and get_modality_catalog()[m].content_class is not ContentClass.TEXT
            for s in series
        )
    # No nested series metadata — ProjectionView may still find imaging dirs on disk.
    return True


def series_paths_for_phi_records(base_dir: Path, phi_records: list[PHI_IndexRecord]) -> list[Path]:
    """Resolve on-disk series directories for Projection View (skips SR/DOC/PDF)."""

    series_paths: list[Path] = []
    for phi_record in phi_records:
        patient_dir = base_dir / Path(phi_record.anon_patient_id)
        if not patient_dir.is_dir():
            continue
        study_dir = patient_dir / phi_record.anon_study_uid
        if not study_dir.is_dir():
            continue
        indexed = list(getattr(phi_record, "series", None) or [])
        if indexed:
            for series in sorted(
                indexed,
                key=lambda item: (str(item.modality or ""), str(item.anon_series_uid or "")),
            ):
                row_mod = Modality.from_code(series.modality)
                if row_mod is not None and get_modality_catalog()[row_mod].content_class is ContentClass.TEXT:
                    continue
                series_path = study_dir / series.anon_series_uid
                if series_path.is_dir():
                    series_paths.append(series_path)
            continue
        for series_path in sorted(study_dir.iterdir(), key=lambda path: path.name):
            if series_path.is_dir():
                series_paths.append(series_path)
    return series_paths


class ProjectionView(AppToplevel):
    PV_FRAME_RELATIVE_SIZE = (0.9, 0.9)  # fraction of screen size (width, height)

    key_to_image_size_mapping: dict[str, ProjectionImageSize] = {
        "S": ProjectionImageSize.SMALL,
        "M": ProjectionImageSize.MEDIUM,
        "L": ProjectionImageSize.LARGE,
    }
    DEFAULT_SIZE = "S"
    # Match Series View: show a loading shell when open will take noticeable time.
    PROGRESS_SERIES_THRESHOLD = 4
    LOAD_POLL_MS = 100
    LOADING_SHELL_WIDTH = 420
    LOADING_SHELL_HEIGHT = 72
    LOADING_SHELL_PAD = 12
    LOAD_PROGRESS_PULSE_MS = 180

    @property
    def phi_records(self) -> list[PHI_IndexRecord]:
        return self._phi_records

    def study_uids(self) -> tuple[str, ...]:
        return projection_study_uids(self._phi_records)

    def __init__(
        self,
        parent,
        controller: "ProjectController",
        base_dir: Path,
        phi_records: list[PHI_IndexRecord],
        fonts=None,
    ):

        if not base_dir.is_dir():
            raise ValueError(f"{base_dir} is not a valid directory")

        if not phi_records:
            raise ValueError("No phi_records for ProjectionView")

        self._fonts = fonts
        self._controller = controller
        self._base_dir = base_dir
        self._phi_records = phi_records
        self._parent = parent

        self._series_paths = series_paths_for_phi_records(base_dir, phi_records)
        if not self._series_paths:
            raise ValueError("No series paths found for study list")

        super().__init__(master=parent)
        self.withdraw()

        self._total_series = len(self._series_paths)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.resizable(width=False, height=False)
        self.bind("<Escape>", self._escape_keypress)

        self._pv_frame_width = int(self.PV_FRAME_RELATIVE_SIZE[0] * self.winfo_screenwidth())
        self._pv_frame_height = int(self.PV_FRAME_RELATIVE_SIZE[1] * self.winfo_screenheight())

        ProjectionImageSizeConfig.set_scaling_factor_if_needed(self._pv_frame_width)

        self._page_number = 1  # not zero based
        self._rows = 0
        self._cols = 0
        self._pages = 0
        self._page_slider = None
        self._loading_page = False
        self._series_view: tk.Misc | None = None
        self._loading = False
        self._load_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._load_cancel = threading.Event()
        self._loading_shell: ctk.CTkFrame | None = None
        self._load_progress: ctk.CTkProgressBar | None = None
        self._load_status_label: ctk.CTkLabel | None = None
        self._load_progress_after_id: str | None = None
        self._load_progress_value = 0.0
        self._prefetched_projections: dict[Path, Projection] = {}
        self._destroyed = False

        self._update_title()
        self._create_widgets()

        logger.info(f"ProjectionView for Studies={len(self._phi_records)}, Series={self._total_series}")

        # Bind keyboard arrow buttons for page control:
        self.bind("<Left>", lambda e: self._on_page_slider(max(1, self._page_number - 1)))
        self.bind(
            "<Right>",
            lambda e: self._on_page_slider(min(self._pages, self._page_number + 1)),
        )
        # Bind mousewheel for page control:
        self.bind("<MouseWheel>", self._mouse_wheel)

        self._image_size = self.key_to_image_size_mapping[self.DEFAULT_SIZE]
        self._calc_layout()
        self._update_title()
        self._trace_startup("widgets_done", viewable=0)
        self._begin_projection_load()

    def _trace_startup(self, step: str, **fields: object) -> None:
        parts = [f"step={step}"]
        for key, value in fields.items():
            parts.append(f"{key}={value}")
        logger.info("ProjectionView startup: %s", " ".join(parts))

    def _widget_alive(self) -> bool:
        if getattr(self, "_destroyed", False):
            return False
        with contextlib.suppress(tk.TclError):
            return bool(self.winfo_exists())
        return False

    def _first_page_series_paths(self) -> list[Path]:
        """Series paths for the current page (layout must already be calculated)."""
        if self._rows <= 0 or self._cols <= 0:
            return list(self._series_paths)
        start = (self._page_number - 1) * self._rows * self._cols
        end = min(start + self._rows * self._cols, self._total_series)
        return self._series_paths[start:end]

    def _needs_load_progress(self) -> bool:
        """True when first-page build is likely slow (many series or missing Projection.pkl)."""
        page_paths = self._first_page_series_paths()
        if len(page_paths) >= self.PROGRESS_SERIES_THRESHOLD:
            return True
        return any(not (path / PROJECTION_FILENAME).is_file() for path in page_paths)

    def _position_near_parent(self, *, width: int, height: int) -> None:
        """Place the loading shell near the parent Dataset window."""
        self.update_idletasks()
        try:
            self._parent.update_idletasks()
            pos_x = self._parent.winfo_rootx() + 30
            pos_y = self._parent.winfo_rooty() + 30
        except tk.TclError:
            pos_x = (self.winfo_screenwidth() - width) // 2
            pos_y = (self.winfo_screenheight() - height) // 2
        pos_x = max(0, min(pos_x, self.winfo_screenwidth() - width))
        pos_y = max(0, min(pos_y, self.winfo_screenheight() - height))
        self.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

    def _show_loading_shell(self) -> None:
        """Series View-style status window while projections are built."""
        # Hide grid content so we can pack the shell (tk forbids pack+grid on same parent).
        self._pv_frame.grid_remove()
        self._paging_frame.grid_remove()

        self.title(_("Projection View"))
        width = self.LOADING_SHELL_WIDTH
        height = self.LOADING_SHELL_HEIGHT
        self.geometry(f"{width}x{height}")
        self.minsize(width, height)

        self._loading_shell = ctk.CTkFrame(self, fg_color="transparent")
        pad = self.LOADING_SHELL_PAD
        self._loading_shell.pack(fill="both", expand=True, padx=pad, pady=pad)

        self._load_status_label = ctk.CTkLabel(
            self._loading_shell,
            text=f"{_('Building projections')}…",
            anchor="w",
        )
        self._load_status_label.pack(fill="x", pady=(0, 8))

        progress_width = width - (2 * pad)
        self._load_progress = ctk.CTkProgressBar(self._loading_shell, width=progress_width)
        self._load_progress.pack(fill="x")
        self._load_progress_value = 0.0
        self._load_progress.set(0.0)
        self._pulse_load_progress()
        self._position_near_parent(width=width, height=height)

    def _pulse_load_progress(self) -> None:
        if not self._loading or self._load_progress is None:
            return
        self._load_progress_value = min(0.92, self._load_progress_value + 0.035)
        self._load_progress.set(self._load_progress_value)
        self._load_progress_after_id = self.after(
            self.LOAD_PROGRESS_PULSE_MS,
            self._pulse_load_progress,
        )

    def _stop_load_progress_pulse(self) -> None:
        if self._load_progress_after_id is None:
            return
        with contextlib.suppress(tk.TclError):
            self.after_cancel(self._load_progress_after_id)
        self._load_progress_after_id = None

    def _set_load_status(self, text: str) -> None:
        if self._load_status_label is None:
            return
        with contextlib.suppress(tk.TclError):
            self._load_status_label.configure(text=text)

    def _begin_projection_load(self) -> None:
        """Show progress when needed; otherwise populate hidden like before."""
        page_paths = self._first_page_series_paths()
        if self._needs_load_progress():
            self._loading = True
            self._load_cancel.clear()
            self._show_loading_shell()
            self.update_idletasks()
            self.deiconify()
            self.lift()
            self._trace_startup("loading_shell", series=len(page_paths), viewable=1)
            threading.Thread(
                target=self._load_worker,
                args=(tuple(page_paths),),
                daemon=True,
                name="ProjectionViewLoad",
            ).start()
            self.after(self.LOAD_POLL_MS, self._poll_load_worker)
            return
        self._present_projection_grid()

    def _load_worker(self, series_paths: tuple[Path, ...]) -> None:
        """Build Projection objects off the UI thread (PhotoImage stays on main)."""
        results: list[tuple[Path, Projection | None, str | None]] = []
        total = len(series_paths)
        for index, series_path in enumerate(series_paths, start=1):
            if self._load_cancel.is_set():
                self._load_queue.put(("cancelled", None))
                return
            self._load_queue.put(
                (
                    "progress",
                    (index, total, series_path.name),
                )
            )
            try:
                projection = create_projection_from_series(series_path)
                results.append((series_path, projection, None))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Projection build failed for %s", series_path)
                results.append((series_path, None, str(exc)))
        if self._load_cancel.is_set():
            self._load_queue.put(("cancelled", None))
            return
        self._load_queue.put(("done", results))

    def _poll_load_worker(self) -> None:
        if not self._widget_alive() or not self._loading:
            return

        while True:
            try:
                kind, payload = self._load_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "progress":
                index, total, name = payload
                self._set_load_status(
                    f"{_('Building projections')}…  {index}/{total}  {name}"
                )
                continue
            if kind == "cancelled":
                self._loading = False
                self._stop_load_progress_pulse()
                return
            if kind == "done":
                self.after_idle(lambda results=payload: self._finish_projection_load(results))
                return
            if kind == "error":
                self._loading = False
                self._stop_load_progress_pulse()
                messagebox.showerror(
                    title=_("Projection View"),
                    message=_("Could not build projections.") + f"\n\n{payload}",
                    parent=self._parent,
                )
                self.destroy()
                return

        self.after(self.LOAD_POLL_MS, self._poll_load_worker)

    def _finish_projection_load(
        self,
        results: list[tuple[Path, Projection | None, str | None]],
    ) -> None:
        if not self._widget_alive():
            return
        if not self._loading:
            return
        self._loading = False
        self._stop_load_progress_pulse()
        failures = [f"{path.name}: {error}" for path, _proj, error in results if error]
        self._prefetched_projections = {
            path: projection for path, projection, error in results if projection is not None and error is None
        }

        if self._loading_shell is not None:
            self.withdraw()
            self._loading_shell.destroy()
            self._loading_shell = None
            self._load_progress = None
            self._load_status_label = None
            self.update_idletasks()

        if failures and not self._prefetched_projections:
            messagebox.showerror(
                title=_("Projection View"),
                message=_("Could not build projections.") + "\n\n" + "\n".join(failures[:8]),
                parent=self._parent,
            )
            self.destroy()
            return

        # Drop the loading-shell size lock so the projection grid can size the window.
        pad = 10
        self.minsize(0, 0)
        self.geometry("")
        self._pv_frame.grid(row=0, column=0, padx=pad, pady=pad, sticky="nsew")
        self._paging_frame.grid(row=1, column=0, padx=pad, pady=(0, pad), sticky="ew")
        self._present_projection_grid()

    def _apply_content_geometry(self) -> None:
        """Size the non-resizable window to the projection grid (clears loading-shell geometry)."""
        self.update_idletasks()
        width = max(int(self.winfo_reqwidth()), 1)
        height = max(int(self.winfo_reqheight()), 1)
        try:
            pos_x = int(self.winfo_x())
            pos_y = int(self.winfo_y())
        except tk.TclError:
            pos_x = max(0, (self.winfo_screenwidth() - width) // 2)
            pos_y = max(0, (self.winfo_screenheight() - height) // 2)
        pos_x = max(0, min(pos_x, self.winfo_screenwidth() - width))
        pos_y = max(0, min(pos_y, self.winfo_screenheight() - height))
        self.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

    def _present_projection_grid(self) -> None:
        """Populate while hidden, then show once (Series View finish pattern)."""
        self._calc_layout()
        self._update_title()
        self._trace_startup(
            "populate_start",
            page=self._page_number,
            size=self._image_size.name,
            viewable=0,
        )
        self._populate_px_frame()
        self._trace_startup(
            "populate_done",
            page=self._page_number,
            thumbnails=min(self._rows * self._cols, self._total_series),
            viewable=0,
        )
        self._apply_content_geometry()
        self.deiconify()
        self._trace_startup("deiconify", viewable=1)

    def load_phi_records(self, phi_records: list[PHI_IndexRecord]) -> None:
        """Replace the displayed studies without recreating the window."""
        if not phi_records:
            raise ValueError("No phi_records for ProjectionView")
        series_paths = series_paths_for_phi_records(self._base_dir, phi_records)
        if not series_paths:
            raise ValueError("No series paths found for study list")
        if projection_study_uids(phi_records) == self.study_uids() and series_paths == self._series_paths:
            return

        if self._loading:
            self._load_cancel.set()
            self._loading = False
            self._stop_load_progress_pulse()

        self._phi_records = phi_records
        self._series_paths = series_paths
        self._total_series = len(series_paths)
        self._page_number = 1
        self._prefetched_projections = {}

        self.withdraw()
        if self._loading_shell is not None:
            self._loading_shell.destroy()
            self._loading_shell = None
            self._load_progress = None
            self._load_status_label = None
        self._calc_layout()
        self._update_title()
        self._begin_projection_load()

    def _update_title(self):
        title = format_projection_view_title(self._phi_records, self._total_series, self._pages)
        self.title(title)
        refresh_app_window_menu(self)

    def _clear_view(self):
        logger.debug("Clear ProjectionView Frame")
        for widget in self._pv_frame.winfo_children():
            widget.unbind("<Button-1>")
            widget.destroy()  # this should clean up the associated CTKImage & Tkinter PhotoImage

    def _update_image_size(self, value):
        if self._loading:
            return
        logger.info(f"Updating image size to {value}")
        self._image_size: ProjectionImageSize = self.key_to_image_size_mapping[value]
        self._page_number = 1  # reset to first page number when image size is changed
        self._calc_layout()
        self._populate_px_frame()  # Redraw the frame with new size
        self._apply_content_geometry()


    def _create_widgets(self):
        logger.info("_create_widgets")
        PAD = 10

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 1. ProjectionView Frame:
        self._pv_frame = ctk.CTkFrame(
            self,
            bg_color="black",
        )
        self._pv_frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nsew")

        # 2. Bottom Frame for paging & image sizing:
        self._paging_frame = ctk.CTkFrame(self)
        self._paging_frame.grid(row=1, column=0, padx=PAD, pady=(0, PAD), sticky="ew")
        self._paging_frame.grid_columnconfigure(0, weight=1)

        self._instruction_label = ctk.CTkLabel(
            self._paging_frame,
            text=_("Click a projection to open Series View."),
            text_color="gray60",
        )
        self._instruction_label.grid(row=0, column=0, columnspan=3, padx=PAD, pady=(0, 4), sticky="w")

        self._page_label = ctk.CTkLabel(self._paging_frame, text="Page ...")
        self._page_label.grid(row=1, column=1, padx=PAD, pady=0, sticky="e")

        # CTkSlider widget is created in _calc_layout if self._pages > 1

        # Segmented Button for ProjectionView image size selection
        self._image_size_button = ctk.CTkSegmentedButton(
            self._paging_frame, values=["S", "M", "L"], command=self._update_image_size
        )
        self._image_size_button.set(self.DEFAULT_SIZE)
        self._image_size_button.grid(row=1, column=2)

    def _calc_layout(self):
        combined_width = 3 * self._image_size.width()
        combined_height = self._image_size.height()
        self._rows = self._pv_frame_height // combined_height
        self._cols = self._pv_frame_width // combined_width
        self._pages = ceil(self._total_series / (self._rows * self._cols))

        logger.info(f"Rows: {self._rows}, Cols: {self._cols}, Pages: {self._pages}")

        if self._pages > 1:
            if self._page_slider is not None:
                self._page_slider.grid_forget()
                self._page_slider.destroy()
                self._page_slider = None
            self._page_slider = ctk.CTkSlider(
                self._paging_frame,
                button_length=round(combined_width * self._cols / self._pages),
                from_=1,
                to=self._pages,
                number_of_steps=self._pages - 1,
                command=self._on_page_slider,
            )
            self._page_slider.grid(row=1, column=0, padx=10, pady=0, sticky="we")
            self._page_slider.set(0)
        else:
            if self._page_slider is not None:
                self._page_slider.grid_forget()
                self._page_slider.destroy()
                self._page_slider = None
                self._paging_frame.update()

    def _mouse_wheel(self, event):
        if not self._pages or not self._page_slider:
            return

        logger.debug(f"mouse wheel event.delta: {event.delta}")

        if event.delta > 0:  # Scroll up
            next_page_number = self._page_number + 1
            if next_page_number > self._pages:
                return
        elif event.delta < 0:  # Scroll down
            next_page_number = self._page_number - 1
            if next_page_number < 1:
                return

        self._on_page_slider(next_page_number)

    def _on_page_slider(self, value):
        if self._loading or self._loading_page or self._pages <= 1:
            return

        logger.debug(f"value: {value}, current_page: {self._page_number}")

        if round(value) == self._page_number:
            return

        self._page_number = round(value)

        if self._page_slider:
            try:
                self._loading_page = True  # prevent re-entry, use lock instead?
                self._page_slider.configure(state="disabled")
                self._populate_px_frame()
            finally:
                self._page_slider.configure(state="normal")
                self._page_slider.set(self._page_number)
                self._loading_page = False

    def add_border_inplace(self, image: Image.Image, border_fraction=0.0075, min_border_px=3, color: str = "red"):
        """
        Adds a border around and within a PIL Image, modifying the source image directly.

        Args:
            imge: The PIL Image to add a border to (modified in place).
            border_fraction: The percentage of the max dimension to use for the border width.
            min_border_px: Minimum border width in pixels
            color: Color of border pixels
        """
        width, height = image.size
        max_dimension = max(width, height)
        border_width = max(min_border_px, int(max_dimension * border_fraction))

        draw = ImageDraw.Draw(image)

        draw.rectangle(
            [(0, 0), (width - 1, height - 1)],  # Outer rectangle,
            outline=color,
            width=border_width,
        )

    def add_external_border(
        self, image: Image.Image, border_fraction=0.025, min_border_px=20, color: str = "black"
    ) -> Image.Image:
        """
        Adds a border external to a PIL Image, preserving the original image pixels.

        Args:
            image: The PIL Image to add a border to.
            border_fraction: The fraction of the max dimension to use for the border width.
            min_border_px: Minimum border width in pixels.
            color: Color of border pixels.

        Returns:
            A new PIL Image with the external border.
        """
        width, height = image.size
        max_dimension = max(width, height)
        border_width = max(min_border_px, int(max_dimension * border_fraction))

        # Calculate new dimensions with the border
        new_width = width + 2 * border_width
        new_height = height + 2 * border_width

        # Create a new image with the new dimensions
        bordered_image = Image.new(image.mode, (new_width, new_height), color)

        # Paste the original image into the center of the new image
        bordered_image.paste(image, (border_width, border_width))

        return bordered_image

    def generate_combined_image(
        self,
        series_path: Path,
        projection: Projection | None = None,
    ) -> tuple[ImageTk.PhotoImage, Projection]:
        """
        Generate a combined image from the Projection images of series using padding between images.

        Args:
            series_path: Series directory on disk.
            projection: Optional prebuilt Projection (worker prefetch); otherwise load/create.
        """
        if projection is None:
            projection = self._prefetched_projections.pop(series_path, None)
        if projection is None:
            projection = create_projection_from_series(series_path)
        combined_image = Image.new(
            mode="RGB",
            size=(3 * self._image_size.width(), self._image_size.height()),
            color="black",
        )

        if projection.proj_images:
            projection.ocr = []
            for i, proj_image in enumerate(projection.proj_images):
                combined_image.paste(
                    proj_image
                    if self._image_size == ProjectionImageSize.LARGE
                    and ProjectionImageSizeConfig().get_scaling_factor() == 1.0
                    else proj_image.resize((self._image_size.width(), self._image_size.height())),
                    (i * self._image_size.width(), 0),
                )

        # Convert to PhotoImage (must stay on the UI thread).
        photo_image = ImageTk.PhotoImage(combined_image)

        return photo_image, projection

    def _create_or_update_label(
        self,
        row,
        col,
        combined_image: ImageTk.PhotoImage | None = None,
        projection: Projection | None = None,
        series_path: Path | None = None,
    ):
        """
        Create or update a label at the given grid position.
        If image is none a blank image is attached to the label
        """
        if combined_image is None:
            # Create a blank combined image if None is provided
            combined_image = ImageTk.PhotoImage(
                Image.new(
                    mode="RGB",
                    size=(3 * self._image_size.width(), self._image_size.height()),
                    color="black",
                )
            )

        label = tk.Label(self._pv_frame, image=combined_image)
        label.grid(row=row, column=col)
        # Store a reference to avoid garbage collection by tkinter
        label.photo_image = combined_image  # type: ignore

        if projection and series_path:
            label.configure(cursor="hand2")
            tip = (projection.series_description or "").strip() or _("(no series description)")
            bind_hover_tooltip(label, tip, parent=self)
            label.bind(
                "<Button-1>",
                lambda event, k=projection, sp=series_path: self._on_image_click(event, k, sp),
            )

    def _populate_px_frame(self):
        """
        Populate the ProjectionView frame with projection images for self._page_number
        """
        logger.debug(f"Populate pv_frame page={self._page_number}, image size={self._image_size}")
        self._page_label.configure(text=_("Page") + f" {self._page_number} " + _("of") + f" {self._pages}")
        self._clear_view()

        # Populate the grid
        start_index = (self._page_number - 1) * self._rows * self._cols
        series_ndx = start_index

        for row in range(self._rows):
            for col in range(self._cols):
                if series_ndx < self._total_series:
                    # Generate and display the combined projection images for the series
                    series_path = self._series_paths[series_ndx]
                    image, projection = self.generate_combined_image(series_path)
                    self._create_or_update_label(row, col, image, projection, series_path)
                else:
                    if self._pages > 1:
                        self._create_or_update_label(row, col)  # draw blank image, clear previous

                series_ndx += 1

        self.update_idletasks()

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        if self._loading:
            self._load_cancel.set()
            self._loading = False
        self._stop_load_progress_pulse()
        super().destroy()

    def _on_cancel(self):
        logger.info("_on_cancel")
        if self._loading:
            self._load_cancel.set()
            self._loading = False
            self._stop_load_progress_pulse()
        self._clear_view()
        teardown_ctk_toplevel(self, parent=self.master)

    def _on_image_click(self, event, projection: Projection, series_path: Path):
        logger.info(f"Projection clicked: projection: {projection}")
        if self._series_view and self._series_view.winfo_exists():
            logger.info("SeriesView already OPEN")
            self._series_view.deiconify()
            self._series_view.focus_force()
            return

        self._series_view = open_series_workspace(
            self,
            controller=self._controller,
            series_path=series_path,
            fonts=self._fonts,
        )
        if self._series_view is None:
            return
