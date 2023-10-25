# Run this python helper script from the project dir within pipenv virtual environment to generate the windows application: DICOM Anonymizer.exe

# pipenv shell
# python build_win.py

from __version__ import __version__
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
        file_description="RSNA DICOM Anonymizer",
        internal_name="anonymizer",
        legal_copyright="© 2023 Radiology Society of North America. All rights reserved.",
        original_filename="anonymizer.exe",
        product_name="Anonymizer",
    )

    print(
        "Using PyInstaller to create install dir with exe from python source & libs + versionfile.txt + icon"
    )
    PyInstaller.__main__.run(
        [
            "--noconfirm",
            "--onedir",
            "--splash",
            "assets\\images\\rsna_logo_head_profile.png",
            "--windowed",
            "--add-data",
            "C:\\Users\\michaelevans\\.virtualenvs\\anonymizer-eXljqkhi\\Lib\\site-packages\\customtkinter;customtkinter\\",
            "--add-data",
            "assets\\;assets\\",
            "--log-level",
            "WARN",
            "--icon",
            "assets\\images\\rsna_icon.ico",
            "--version-file",
            "versionfile.txt",
            "--name",
            "Anonymizer",
            "anonymizer.py",
        ]
    )
