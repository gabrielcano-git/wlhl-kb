#!/bin/zsh

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR" || exit 1

clear
echo "Opening the WLHL Knowledge Base..."
echo ""

if curl -fsS --max-time 2 http://localhost:8501/ >/dev/null 2>&1; then
  open http://localhost:8501/
  echo "The app is already open."
  sleep 2
  exit 0
fi

# First launch: download a free local installer, Python, and the app requirements.
# Nothing is installed system-wide, no password is needed, and no podcast data is uploaded.
if [[ ! -x ".venv/bin/python" ]]; then
  echo "First-time setup — this may take a few minutes."
  echo "Please keep this window open."
  echo ""

  UV_DIR="$PROJECT_DIR/.wlhl-tools"
  UV="$UV_DIR/uv"
  export XDG_CONFIG_HOME="$PROJECT_DIR/.wlhl-config"
  export UV_CACHE_DIR="$PROJECT_DIR/.wlhl-cache"
  export UV_PYTHON_INSTALL_DIR="$PROJECT_DIR/.wlhl-python"
  mkdir -p "$UV_DIR" "$XDG_CONFIG_HOME" "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR"

  if [[ ! -x "$UV" ]]; then
    echo "Downloading the free setup tool..."
    curl -LsSf https://astral.sh/uv/0.11.28/install.sh | env UV_INSTALL_DIR="$UV_DIR" UV_NO_MODIFY_PATH=1 sh || {
      osascript -e 'display alert "Setup could not download" message "Check your internet connection and double-click Open WLHL.command again." as critical'
      exit 1
    }
  fi

  echo "Preparing Python..."
  "$UV" venv --python 3.12 .venv || {
    osascript -e 'display alert "Python setup did not finish" message "Check your internet connection and double-click Open WLHL.command again." as critical'
    exit 1
  }

  echo "Installing the app for the first time..."
  "$UV" pip install --python .venv/bin/python -r requirements.txt || {
    osascript -e 'display alert "Installation did not finish" message "Check your internet connection and double-click Open WLHL.command again." as critical'
    exit 1
  }
fi

if ! .venv/bin/python -c "import streamlit" >/dev/null 2>&1; then
  osascript -e 'display alert "WLHL could not start" message "Delete the .venv folder and double-click Open WLHL.command again." as critical'
  exit 1
fi

(sleep 3; open http://localhost:8501/) &
echo "The app will open in your browser."
echo "Keep this window open while using WLHL."
echo "To stop the app, return here and press Control + C."
echo ""

exec .venv/bin/python -m streamlit run app.py --server.headless true --server.port 8501 --browser.gatherUsageStats false
