#!/bin/zsh
# Builds dist/Set Downloader.app: the UI, Python and tl2mixxx (without Set Copy), pywebview, and
# sockseek in Contents/Resources. SOCKSEEK=<path> picks the sockseek to bundle.
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
    --exclude-module tl2mixxx.setcopy --exclude-module numpy --exclude-module tkinter \
    build/entry.py

# sockseek goes in after PyInstaller (it would rewrite the binary), then the bundle is signed again
cp "$SOCKSEEK" "$APP/Contents/Resources/sockseek"
LICENSE="$(dirname "$SOCKSEEK")/sockseek-LICENSE.txt"
[[ -f "$LICENSE" ]] && cp "$LICENSE" "$APP/Contents/Resources/"
codesign --force --deep --sign - "$APP" 2>/dev/null
echo "Built $APP ($(du -sh "$APP" | cut -f1))"
