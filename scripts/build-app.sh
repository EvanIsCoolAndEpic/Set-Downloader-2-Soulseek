#!/bin/zsh
# Builds dist/Set Downloader.app: the UI, Python and tl2mixxx (without Set Copy), pywebview, yt-dlp,
# mutagen, ffmpeg (imageio-ffmpeg's), macOS Vision for pictures, and sockseek in Contents/Resources.
# SOCKSEEK=<path> picks the sockseek to bundle.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
SOCKSEEK=${SOCKSEEK:-$HOME/Downloads/tl2mixxx/dist/1001tracklists-tools/sockseek}
# tl2mixxx is installed editable, which PyInstaller can't see through: its source goes on the path
TL2MIXXX=$(.venv/bin/python -c "import tl2mixxx, pathlib; print(pathlib.Path(tl2mixxx.__file__).parent.parent)")
[[ -x "$SOCKSEEK" ]] || { echo "sockseek not found at $SOCKSEEK (set SOCKSEEK=...)" >&2; exit 1; }
APP="dist/Set Downloader.app"

(cd web && npm run build)

mkdir -p build
cat > build/entry.py <<'PY'
import sys
from setdl.app import main
sys.exit(main())
PY

rm -rf build/pyinstaller "$APP"
.venv/bin/pyinstaller --noconfirm --clean --log-level WARN --windowed --onedir \
    --name "Set Downloader" --osx-bundle-identifier local.setdownloader \
    --distpath dist --workpath build/pyinstaller --specpath build \
    --paths "$ROOT" --paths "$TL2MIXXX" \
    --add-data "$ROOT/web/dist:web/dist" \
    --hidden-import tl2mixxx.media_cli --hidden-import tl2mixxx.inputs --collect-submodules tl2mixxx.inputs \
    --hidden-import yt_dlp --collect-submodules yt_dlp --copy-metadata yt-dlp \
    --hidden-import mutagen --collect-submodules mutagen \
    --hidden-import imageio_ffmpeg --collect-data imageio_ffmpeg \
    --hidden-import Vision --hidden-import Foundation --hidden-import Quartz --hidden-import CoreML \
    --exclude-module tl2mixxx.setcopy --exclude-module numpy --exclude-module tkinter \
    build/entry.py

# The plain folder PyInstaller makes the .app from isn't needed (89 MB)
rm -rf "dist/Set Downloader"

# sockseek goes in after PyInstaller (it would rewrite the binary), then the bundle is signed again
cp "$SOCKSEEK" "$APP/Contents/Resources/sockseek"
LICENSE="$(dirname "$SOCKSEEK")/sockseek-LICENSE.txt"
[[ -f "$LICENSE" ]] && cp "$LICENSE" "$APP/Contents/Resources/"
codesign --force --deep --sign - "$APP" 2>/dev/null

# What tl2mixxx imports only when it's used must be inside: a frozen child checks
EXE="$APP/Contents/MacOS/Set Downloader"
"$EXE" --helper ytdlp-version >/dev/null || { echo "yt-dlp is missing from the app" >&2; exit 1; }
"$EXE" --tl2mixxx resolve --detect "https://www.youtube.com/watch?v=x" >/dev/null || { echo "tl2mixxx resolve doesn't run" >&2; exit 1; }
"$EXE" --tl2mixxx finish --help >/dev/null || { echo "tl2mixxx finish doesn't run" >&2; exit 1; }
FFMPEG=$(ls "$APP"/Contents/Frameworks/imageio_ffmpeg/binaries/ffmpeg-* 2>/dev/null | head -1)
[[ -n "$FFMPEG" ]] && "$FFMPEG" -version >/dev/null || { echo "ffmpeg is missing from the app" >&2; exit 1; }
[[ -d "$APP/Contents/Frameworks/Vision" ]] || { echo "pyobjc's Vision is missing from the app" >&2; exit 1; }
echo "Built $APP ($(du -sh "$APP" | cut -f1))"
