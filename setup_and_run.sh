#!/bin/bash

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Function for error handling
# shellcheck disable=SC2317
handle_error() {
    # Skip error handling for KeyboardInterrupt (exit code 4 from Python script)
    if [ "${2:-1}" -ne 4 ]; then
        echo "Script failed with error on line $1"
        deactivate 2>/dev/null || true
        exit "$2"
    fi
}
trap 'handle_error $LINENO $?' ERR

# Show usage
show_usage() {
    echo "Usage: $0 https://iono.fm/c/<number> [--force] [--short-names] [--dir <name>] [--recheck] [--log-level <DEBUG|INFO|WARNING|ERROR>] [--venv-dir <path>]"
    exit 1
}

# Detect package manager
detect_package_manager() {
    if command -v apt-get &>/dev/null; then
        echo "apt"
    elif command -v dnf &>/dev/null; then
        echo "dnf"
    elif command -v brew &>/dev/null; then
        echo "brew"
    else
        echo "none"
    fi
}

# Check and install dependencies
check_dependencies() {
    local package_manager
    package_manager=$(detect_package_manager)
    local deps=("python3" "pip3")
    
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &>/dev/null; then
            echo "$dep not found. Attempting to install..."
            case $package_manager in
                apt)
                    sudo apt update && sudo apt install -y python3 python3-pip python3-venv
                    ;;
                dnf)
                    sudo dnf install -y python3 python3-pip python3-libs
                    ;;
                brew)
                    brew install python3
                    ;;
                none)
                    echo "No supported package manager found. Please install python3 and pip3 manually."
                    echo "On Debian/Ubuntu (WSL): sudo apt update && sudo apt install python3 python3-pip python3-venv"
                    echo "On Fedora: sudo dnf install python3 python3-pip python3-libs"
                    echo "On macOS (without Homebrew): Download Python from https://www.python.org/downloads/"
                    echo "On Windows: Install Python from https://www.python.org/downloads/ or Microsoft Store"
                    exit 1
                    ;;
            esac
            break
        fi
    done
}

# Parse arguments
parse_arguments() {
    CHANNEL_URL=""
    VENV_DIR="$HOME/podcast_venv"
    ADDITIONAL_ARGS=()
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            https://iono.fm/c/[0-9]*)
                CHANNEL_URL="$1"
                ;;
            --force|--short-names|--recheck)
                ADDITIONAL_ARGS+=("$1")
                ;;
            --dir|--log-level|--venv-dir)
                if [[ -z "${2:-}" ]]; then
                    echo "Error: $1 requires a value"
                    show_usage
                fi
                if [[ "$1" == "--venv-dir" ]]; then
                    VENV_DIR="$2"
                else
                    ADDITIONAL_ARGS+=("$1" "$2")
                fi
                shift
                ;;
            *)
                echo "Unknown argument: $1"
                show_usage
                ;;
        esac
        shift
    done
    
    if [[ -z "$CHANNEL_URL" ]]; then
        echo "Error: Channel URL is required"
        show_usage
    fi
}

# Main execution
PYTHON_SCRIPT="download_podcast.py"

check_dependencies

if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "Error: $PYTHON_SCRIPT not found in current directory."
    exit 1
fi

parse_arguments "$@"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "Installing required Python packages..."
if ! pip3 install requests beautifulsoup4 feedparser tqdm python-dateutil; then
    echo "Failed to install Python packages. Run 'pip3 install requests beautifulsoup4 feedparser tqdm python-dateutil' in the virtual environment."
    deactivate
    exit 1
fi

echo "Running $PYTHON_SCRIPT with $CHANNEL_URL ${ADDITIONAL_ARGS[*]}..."
python3 "$PYTHON_SCRIPT" "$CHANNEL_URL" "${ADDITIONAL_ARGS[@]}"
EXIT_CODE=$?

deactivate

if [ $EXIT_CODE -eq 0 ]; then
    echo "Script completed successfully."
elif [ $EXIT_CODE -eq 4 ]; then
    echo "Script interrupted by user. Check 'podcast_download.log' for details."
else
    echo "Script exited with error code $EXIT_CODE. Check 'podcast_download.log' for details."
fi

exit $EXIT_CODE
