from tkinter import Tk, Canvas, PhotoImage
from PIL import Image, ImageSequence
import time


def create_gif(images, duration=500, loop=0):
    """
    Creates an animated GIF from a list of PIL Image objects.

    Args:
        images: A list of PIL Image objects.
        duration: The duration of each frame in milliseconds.
        loop: The number of times to loop the animation. 0 means infinite loop.

    Returns:
        The created GIF image.
    """

    images[0].save("animation.gif", save_all=True, append_images=images[1:], duration=duration, loop=loop)

    return Image.open("animation.gif")


def main():
    # Create a list of PIL Image objects for the animation
    images = [
        Image.new("RGB", (100, 100), "white"),
        Image.new("RGB", (100, 100), "gray"),
        Image.new("RGB", (100, 100), "black"),
    ]

    # Create the animated GIF
    gif_image = create_gif(images, duration=500)

    # Create the Tkinter window
    root = Tk()
    root.title("Animated GIF")

    # Create a canvas to display the GIF
    canvas = Canvas(root, width=100, height=100)
    canvas.pack()

    # Create a PhotoImage object to display the GIF
    photo = PhotoImage(file="animation.gif")
    canvas.create_image(0, 0, image=photo, anchor="nw")

    # Start the animation
    def update():
        try:
            frame = next(ImageSequence.Iterator(gif_image))
            photo.put(frame.getdata(), (0, 0))
            root.after(500, update)  # Schedule next update
        except StopIteration:
            # Handle reaching the end of the animation
            pass

    update()

    root.mainloop()


if __name__ == "__main__":
    main()
