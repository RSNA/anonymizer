class CTkSliderWithMarkers(ctk.CTkSlider):
    def __init__(self, master=None, marker_height=10, **kwargs):
        """
        Custom slider with evenly spaced markers.

        Args:
            master: Parent widget.
            marker_height (int): Height of the markers.
            **kwargs: Additional arguments for CTkSlider.
        """
        super().__init__(master, **kwargs)
        self.marker_height = marker_height

        # Use the slider's background color for the canvas
        slider_bg_color = self._apply_appearance_mode(self.cget("fg_color"))

        self.markers_canvas = ctk.CTkCanvas(self, bg=slider_bg_color, highlightthickness=0)
        self.markers_canvas.place(relx=0, rely=1, relwidth=1, y=-marker_height)

        self.bind("<Configure>", self._draw_markers)

    def _draw_markers(self, event=None):
        """Draw evenly spaced markers below the slider."""
        self.markers_canvas.delete("marker")  # Clear previous markers
        width = self.markers_canvas.winfo_width()

        if self._number_of_steps is None or width == 1:
            return  # Prevent errors when widget is initializing or number_of_steps is None

        step = width / (self._number_of_steps - 1)

        for i in range(self._number_of_steps):
            x = i * step
            self.markers_canvas.create_line(
                x, 0, x, self.marker_height, fill=self._apply_appearance_mode(self.cget("progress_color")), tag="marker"
            )
