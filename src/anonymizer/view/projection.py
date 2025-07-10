import logging
import tkinter as tk
from math import ceil
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from anonymizer.controller.create_projections import (
    Projection,
    ProjectionImageSize,
    ProjectionImageSizeConfig,
    create_projection_from_series,
)
from anonymizer.model.anonymizer import AnonymizerModel, PHI_IndexRecord
from anonymizer.utils.translate import _
from anonymizer.view.series import SeriesView

logger = logging.getLogger(__name__)


class ProjectionView(tk.Toplevel):
    PV_FRAME_RELATIVE_SIZE = (0.9, 0.9)  # fraction of screen size (width, height)

    key_to_image_size_mapping: dict[str, ProjectionImageSize] = {
        "S": ProjectionImageSize.SMALL,
        "M": ProjectionImageSize.MEDIUM,
        "L": ProjectionImageSize.LARGE,
    }
    DEFAULT_SIZE = "S"

    def _get_series_paths(self) -> list[Path]:
        return [
            series_path
            for phi_record in self._phi_records
            for study_path in (self._base_dir / Path(phi_record.anon_patient_id)).iterdir()
            if study_path.is_dir() and study_path.name == phi_record.anon_study_uid
            for series_path in study_path.iterdir()
            if series_path.is_dir()
        ]

    def __init__(self, parent, anon_model: AnonymizerModel, base_dir: Path, phi_records: list[PHI_IndexRecord]):
        super().__init__(master=parent)

        if not base_dir.is_dir():
            raise ValueError(f"{base_dir} is not a valid directory")

        if not phi_records:
            raise ValueError("No phi_records for ProjectionView")

        self._anon_model = anon_model
        self._base_dir = base_dir
        self._phi_records = phi_records

        self._series_paths = self._get_series_paths()
        if not self._series_paths:
            raise ValueError("No series paths found for study list")

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
        self._series_view: SeriesView | None = None

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

        self._update_image_size(self.DEFAULT_SIZE)  # sets self._image_size, initialise PixelView and populates frame

    def _update_title(self):
        title = (
            _("View")
            + f" {len(self._phi_records)} "
            + (_("Studies") if len(self._phi_records) > 1 else _("Study"))
            + " "
            + _("with")
            + f" {self._total_series} "
            + _("Series")
        )

        if self._pages > 1:
            title = title + " " + _("over") + f" {self._pages} " + _("Pages")

        self.title(title)

    def _clear_view(self):
        logger.debug("Clear ProjectionView Frame")
        for widget in self._pv_frame.winfo_children():
            widget.unbind("<Button-1>")
            widget.destroy()  # this should clean up the associated CTKImage & Tkinter PhotoImage

    def _update_image_size(self, value):
        logger.info(f"Updating image size to {value}")
        self._image_size: ProjectionImageSize = self.key_to_image_size_mapping[value]
        self._page_number = 1  # reset to first page number when image size is changed
        self._calc_layout()
        self._populate_px_frame()  # Redraw the frame with new size

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

        self._page_label = ctk.CTkLabel(self._paging_frame, text="Page ...")
        self._page_label.grid(row=0, column=1, padx=PAD, pady=0, sticky="e")

        # CTkSlider widget is created in _calc_layout if self._pages > 1

        # Segmented Button for ProjectionView image size selection
        self._image_size_button = ctk.CTkSegmentedButton(
            self._paging_frame, values=["S", "M", "L"], command=self._update_image_size
        )
        self._image_size_button.set(self.DEFAULT_SIZE)
        self._image_size_button.grid(row=0, column=2)

    def _calc_layout(self):
        combined_width = 3 * self._image_size.width()
        combined_height = self._image_size.height()
        self._rows = self._pv_frame_height // combined_height
        self._cols = self._pv_frame_width // combined_width
        self._pages = ceil(self._total_series / (self._rows * self._cols))

        logger.info(f"Rows: {self._rows}, Cols: {self._cols}, Pages: {self._pages}")

        if self._pages > 1:
            self._page_slider = ctk.CTkSlider(
                self._paging_frame,
                button_length=round(combined_width * self._cols / self._pages),
                from_=1,
                to=self._pages,
                number_of_steps=self._pages - 1,
                command=self._on_page_slider,
            )
            self._page_slider.grid(row=0, column=0, padx=10, pady=0, sticky="we")
            self._page_slider.set(0)
        else:
            if self._page_slider:
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
        if self._loading_page or self._pages <= 1:
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

    def generate_combined_image(self, series_path) -> tuple[ImageTk.PhotoImage, Projection]:
        """
        Generate a combined image from the Projection images of series using padding between images.
        """
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

        # Convert to PhotoImage
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

        self._pv_frame.update()

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info("_on_cancel")
        self._clear_view()
        self.grab_release()
        self.destroy()

    def _on_image_click(self, event, projection: Projection, series_path: Path):
        logger.info(f"Projection clicked: projection: {projection}")
        if self._series_view and self._series_view.winfo_exists():
            logger.info("SeriesView already OPEN")
            self._series_view.deiconify()
            self._series_view.focus_force()
            return

        self._series_view = SeriesView(self, anon_model=self._anon_model, series_path=series_path)
        if self._series_view is None:
            logger.error("Internal Error creating SeriesView")
            return
