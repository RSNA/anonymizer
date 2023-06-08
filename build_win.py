# Run this python helper script from the project dir within pipenv virtual environment to generate the windows application: DICOM Anonymizer.exe

# pipenv shell
# python build_win.py

from dicom_scrub import __version__

import pyinstaller_versionfile
import PyInstaller.__main__

if __name__ == "__main__":
    print(
        f"Create Windows Version Resource Text file: versionfile.txt for PyInstaller, new version: {__version__}"
    )
    pyinstaller_versionfile.create_versionfile(
        output_file="versionfile.txt",
        version=__version__,
        company_name="Radiology Society of North America",
        file_description="RSNA DICOM Anonymizer & Scrubber",
        internal_name="dicom_scrub",
        legal_copyright="© Radiology Society of North America. All rights reserved.",
        original_filename="dicom_scrub.exe",
        product_name="DICOM Anonymizer",
    )

    print(
        "Using PyInstaller to create a single file exe from python source & libs + versionfile.txt + icon"
    )
    PyInstaller.__main__.run(
        [
            "--noconfirm",
            "--onedir",
            "--windowed",
            "--add-data",
            "C:\\Users\\tatea\\.virtualenvs\\dicom_scrub-yrdUUzYX\\Lib\\site-packages\\customtkinter;customtkinter\\",
            "--add-data",
            "assets\\;assets\\",
            "--log-level",
            "WARN",
            "--icon",
            "assets\\rsna_icon.ico",
            "--version-file",
            "versionfile.txt",
            "--name",
            "DICOM Anonymizer",
            "dicom_scrub.py",
        ]
    )
