# Run this python helper script from the project dir within pipenv virtual environment to generate executables for the following platforms:

# 1. Windows: Anonymizer.exe
# 2. Mac: Anonymizer.app
# 3. Linux: Anonymizer

# pipenv shell
# python build.py

import os
import shutil
import subprocess
import platform
import plistlib
import os

from __version__ import __version__
import pyinstaller_versionfile
import PyInstaller.__main__

os.environ["PYTHONOPTIMIZE"] = "2"  # range: 0,1,2 (2 is highest level of optimization)
os.environ["PIPENV_VERBOSITY"] = "-1"  # to suppress pipenv courtesy notice

# customtkinter may not be installed in standard python library directory, get path in virtual environment:
venv_path = subprocess.check_output(["pipenv", "--venv"]).strip().decode()

# Get the Python version
python_version = (
    "python"
    + platform.python_version_tuple()[0]
    + "."
    + platform.python_version_tuple()[1]
)
print(f"Python version tuple: {platform.python_version_tuple()}")

if os.name == "nt":  # Windows
    lib_dir = "Lib"
    python_version = ""
else:  # Unix-based systems
    lib_dir = "lib"


# Path to the customtkinter directory
customtkinter_path = os.path.join(
    venv_path, lib_dir, python_version, "site-packages", "customtkinter"
)

if not os.path.exists(customtkinter_path):
    raise Exception(
        f"customtkinter path: {customtkinter_path} does not exist, please install customtkinter in virtual environment"
    )


def set_macos_version(bundle_path, version):
    print(f"Setting macOS version to {version} for {bundle_path}")
    # Path to the Info.plist file
    plist_path = os.path.join(bundle_path, "Contents", "Info.plist")
    print(f"plist_path: {plist_path}")

    # Check if the plist file exists
    if not os.path.exists(plist_path):
        print(f"Error: {plist_path} does not exist")
        return

    # Read the existing plist file
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    # Set the version
    plist["CFBundleShortVersionString"] = version
    plist["CFBundleVersion"] = version

    # Write the modified plist file
    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)

    print(f"Successfully wrote modified plist to {plist_path}")


if __name__ == "__main__":

    build_version_name = f"Anonymizer_{__version__}"

    print(
        f"Build Current version: {build_version_name} on {platform.system()} platform using PyInstaller"
    )
    print(f"Customtkinter path: {customtkinter_path}")

    if platform.system() == "Windows":
        # Create versionfile.txt
        print(
            f"Create Windows Version Resource Text file: versionfile.txt for PyInstaller, new version: {__version__}"
        )
        pyinstaller_versionfile.create_versionfile(
            output_file="versionfile.txt",
            version=__version__,
            company_name="Radiology Society of North America",
            file_description="RSNA DICOM Anonymizer",
            internal_name="anonymizer",
            legal_copyright="© 2024 Radiology Society of North America. All rights reserved.",
            original_filename="anonymizer.exe",
            product_name="Anonymizer",
        )

        PyInstaller.__main__.run(
            [
                "--noconfirm",
                "--onedir",
                "--splash",
                "assets\\images\\rsna_logo_head_profile.png",
                "--windowed",
                "--add-data",
                f"{customtkinter_path};customtkinter\\",
                "--add-data",
                "assets;assets",
                "--log-level",
                "INFO",
                "--icon",
                "assets\\images\\rsna_icon.ico",
                "--version-file",
                "versionfile.txt",
                "--name",
                build_version_name,
                "anonymizer.py",
            ]
        )

    elif platform.system() == "Darwin":
        PyInstaller.__main__.run(
            [
                "--noconfirm",
                "--onedir",
                "--windowed",
                "--add-data",
                f"{customtkinter_path}:customtkinter/",
                "--add-data",
                "assets:assets",
                "--log-level",
                "INFO",
                "--icon",
                "assets/images/rsna_icon.icns",
                "--name",
                build_version_name",
                "anonymizer.py",
            ]
        )

        # Set the version
        set_macos_version(f"dist/Anonymizer_{__version__}.app", __version__)

        # Delete the redunant build folder
        app_dir = os.path.join("dist", build_version_name)
        if os.path.exists(app_dir):
            shutil.rmtree(app_dir)

    elif platform.system() == "Linux":
        PyInstaller.__main__.run(
            [
                "--noconfirm",
                "--onedir",
                "--windowed",
                "--add-data",
                f"{customtkinter_path}:customtkinter/",
                "--add-data",
                "assets:assets",
                "--log-level",
                "INFO",
                "--name",
                build_version_name",
                "anonymizer.py",
            ]
        )
