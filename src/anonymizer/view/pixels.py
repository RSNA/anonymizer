import logging
from enum import Enum
from math import ceil
from pathlib import Path

import customtkinter as ctk
from PIL import Image

from anonymizer.controller.create_projections import Projection, ProjectionImageSize, create_projection_from_series
from anonymizer.model.anonymizer import PHI_IndexRecord
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class PixelPAD(Enum):
    # padx, pady in pixels
    SMALL = (2, 4)
    MEDIUM = (3, 6)
    LARGE = (5, 10)

    def width(self):
        return self.value[0]

    def height(self):
        return self.value[1]


PAD_MAP: dict[ProjectionImageSize, PixelPAD] = {
    ProjectionImageSize.SMALL: PixelPAD.SMALL,
    ProjectionImageSize.MEDIUM: PixelPAD.MEDIUM,
    ProjectionImageSize.LARGE: PixelPAD.LARGE,
}


def get_pad(size):
    return PAD_MAP[size]


class PixelsView(ctk.CTkToplevel):
    PV_FRAME_RELATIVE_SIZE = (0.9, 0.9)  # fraction of screen size (width, height)
    IMAGE_PAD = 2  # pixels between the projections images when combined
    WIDGET_PAD = 10

    key_to_image_size_mapping: dict[str, ProjectionImageSize] = {
        "S": ProjectionImageSize.SMALL,
        "M": ProjectionImageSize.MEDIUM,
        "L": ProjectionImageSize.LARGE,
    }
    DEFAULT_SIZE = "L"

    def _get_series_paths(self) -> list[Path]:
        return [
            series_path
            for phi_record in self._phi_records
            for study_path in (self._base_dir / Path(phi_record.anon_patient_id)).iterdir()
            if study_path.is_dir() and study_path.name == phi_record.anon_study_uid
            for series_path in study_path.iterdir()
            if series_path.is_dir()
        ]

    def __init__(
        self,
        mono_font: ctk.CTkFont,
        base_dir: Path,
        phi_records: list[PHI_IndexRecord],
    ):
        super().__init__()
        self._data_font = mono_font  # get mono font from app

        if not base_dir.is_dir():
            raise ValueError(f"{base_dir} is not a valid directory")

        # all_patient_ids = [str(p) for p in base_dir.iterdir() if p.is_dir()]

        if not phi_records:
            raise ValueError("No phi_records for PixelsView")

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

        self._page_number = 1  # not zero based
        self._rows = 0
        self._cols = 0
        self._pages = 0
        self._page_slider = None
        self._loading_page = False
        self._pv_labels = {}

        self._update_title()
        self._create_widgets()

        logger.info(f"PixelsView for Studies={len(self._phi_records)}, Series={self._total_series}")

        # Bind keyboard arrow buttons to page control:
        self.bind("<Left>", lambda e: self._on_page_slider(max(1, self._page_number - 1)))
        self.bind(
            "<Right>",
            lambda e: self._on_page_slider(min(self._pages, self._page_number + 1)),
        )
        # Bind mousewheel to page control:
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

    def _update_image_size(self, value):
        logger.info(f"Updating image size to {value}")

        self._image_size = self.key_to_image_size_mapping[value]
        self._page_number = 1  # reset to first page number when image size is changed
        self._calc_layout()

        # Clear PixelView frame of all widgets:
        for widget in self._pv_frame.winfo_children():
            widget.destroy()

        self._pv_frame.update()
        self._pv_labels.clear()

        # Redraw the frame with new size
        self._populate_px_frame()

    def _create_widgets(self):
        logger.info("_create_widgets")
        PAD = self.WIDGET_PAD

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 1. PixelsView Frame:
        self._pv_frame = ctk.CTkFrame(
            self,
            fg_color="black",
        )
        self._pv_frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nsew")

        # 2. Bottom Frame for paging & image sizing:
        self._paging_frame = ctk.CTkFrame(self)
        self._paging_frame.grid(row=1, column=0, padx=PAD, pady=(0, PAD), sticky="ew")
        self._paging_frame.grid_columnconfigure(0, weight=1)

        self._page_label = ctk.CTkLabel(self._paging_frame, text="Page ...")
        self._page_label.grid(row=0, column=1, padx=PAD, pady=0, sticky="e")

        # CTkSlider widget created in _calc_layout if self._pages > 1

        # Segmented Button for PixelsView image size selection
        self._image_size_button = ctk.CTkSegmentedButton(
            self._paging_frame, values=["S", "M", "L"], command=self._update_image_size
        )
        self._image_size_button.set(self.DEFAULT_SIZE)
        self._image_size_button.grid(row=0, column=2)

    def _calc_layout(self):
        padded_combined_width = (
            3 * self._image_size.width() + 2 * self.IMAGE_PAD + 2 * get_pad(self._image_size).width()
        )
        padded_combined_height = self._image_size.height() + get_pad(self._image_size).height()

        self._rows = self._pv_frame_height // padded_combined_height
        self._cols = self._pv_frame_width // padded_combined_width
        self._pages = ceil(self._total_series / (self._rows * self._cols))

        logger.info(f"Rows: {self._rows}, Cols: {self._cols}, Pages: {self._pages}")

        if self._pages > 1:
            self._page_slider = ctk.CTkSlider(
                self._paging_frame,
                button_length=round(padded_combined_width * self._cols / self._pages),
                from_=1,
                to=self._pages,
                number_of_steps=self._pages - 1,
                command=self._on_page_slider,
            )
            self._page_slider.grid(row=0, column=0, padx=self.WIDGET_PAD, pady=0, sticky="we")
            self._page_slider.set(0)
        else:
            if self._page_slider:
                self._page_slider.grid_forget()
                del self._page_slider
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

        # self._page_number = self._page_number + 1 if value > self._page_number else self._page_number - 1
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

    def generate_combined_image(self, series_path) -> tuple[ctk.CTkImage, Projection]:
        """Generate a combined image from the Projection images of series."""

        projection = create_projection_from_series(series_path)
        combined_width = 3 * self._image_size.width() + 2 * self.IMAGE_PAD
        combined_image = Image.new(
            mode="RGB",
            size=(combined_width, self._image_size.height()),
            color="black",
        )
        for i, image in enumerate(projection.images):
            resized_image = image.resize(self._image_size.value)
            combined_image.paste(resized_image, (i * (self._image_size.width() + self.IMAGE_PAD), 0))

        return (
            ctk.CTkImage(
                light_image=combined_image,
                size=(combined_width, self._image_size.height()),
            ),
            projection,
        )

    def _create_or_update_label(self, row, col, image=None, projection=None):
        """Create or update a label at the given grid position."""
        label_key = (row, col)

        if label_key not in self._pv_labels:
            # Create new CTkLabel:
            label = ctk.CTkLabel(self._pv_frame, text="")
            label.grid(
                row=row,
                column=col,
                padx=(0, get_pad(self._image_size).value[0]),
                pady=(0, get_pad(self._image_size).value[1]),
                sticky="nsew",
            )
            self._pv_labels[label_key] = label
        else:
            # Fetch previously create CTkLabel:
            label = self._pv_labels[label_key]

        # Clear previous image and bind new event if applicable
        old_image = getattr(label, "image", None)
        if old_image:
            del old_image  # Explicitly delete the old image reference

        label.configure(image=image)
        label.unbind("<Button-1>")

        if image and projection:
            label.bind(
                "<Button-1>",
                lambda event, k=projection: self._on_image_click(event, k),
            )  # type: ignore

    def _populate_px_frame(self):
        """Populate the PixelsView frame with images for self._page_number"""
        logger.debug(f"Populate pv_frame page={self._page_number}")
        self._page_label.configure(text=_("Page") + f" {self._page_number} " + _("of") + f" {self._pages}")

        # Populate the grid
        start_index = (self._page_number - 1) * self._rows * self._cols
        series_ndx = start_index

        for row in range(self._rows):
            for col in range(self._cols):
                if series_ndx < self._total_series:
                    # Generate and display the combined image for the series
                    series_path = self._series_paths[series_ndx]
                    self._create_or_update_label(row, col, *self.generate_combined_image(series_path))
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
        self.grab_release()
        self.destroy()

    def _on_image_click(self, event, projection: Projection):
        logger.info(f"Projection clicked: projection: {projection}")
