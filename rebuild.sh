#!/bin/bash
# Enhanced build script for MP3Player
# Cleans old build artifacts, activates venv, and rebuilds using PyInstaller.

# Exit immediately if any command fails
set -e

# Function to print errors in red
error() {
    echo -e "\033[0;31mERROR: $1\033[0m"
    exit 1
}

# Activate virtual environment
if [ -f "./venv/bin/activate" ]; then
    source "./venv/bin/activate"
else
    error "Virtual environment not found at ./venv. Please create it first."
fi

# Confirm before removing build artifacts
echo "Cleaning old build artifacts..."
rm -rf build/ dist/ MP3Player.spec || true

# Ensure library.json exists
LIB_FILE="data/library.json"
if [ ! -f "$LIB_FILE" ]; then
    echo "Creating empty library cache..."
    mkdir -p "$(dirname "$LIB_FILE")"
    echo "{}" > "$LIB_FILE"
fi

# Run PyInstaller safely
echo "Building MP3Player..."
pyinstaller --onedir \
            --name "MP3Player" \
            --noconsole \
            --add-data "Image:Image" \
            --add-data "data:data" \
            "app.py"

# Deactivate venv
deactivate

# Build success message
echo "✅ Build complete! Output is in ./dist/MP3Player/"
echo "Library cache remains at $LIB_FILE"