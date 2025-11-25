# Setup and Testing Guide

## 1. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate  # On Windows
```

## 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

## 3. Install External Tools

### macOS (using Homebrew)
```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install required tools
brew install mkvtoolnix ffmpeg
```

### Linux (Debian/Ubuntu)
```bash
sudo apt update
sudo apt install mkvtoolnix ffmpeg
```

### Linux (Arch)
```bash
sudo pacman -S mkvtoolnix-cli ffmpeg
```

### Windows
Download and install:
- MKVToolnix: https://mkvtoolnix.download/downloads.html
- FFmpeg: https://ffmpeg.org/download.html

Add them to your PATH or specify paths in `unlinkmkv.ini`

## 4. Configure

```bash
cp unlinkmkv.ini.dist unlinkmkv.ini
```

Edit `unlinkmkv.ini` if needed (usually auto-detection works).

## 5. Test Installation

### Verify tools are found:
```bash
which mkvmerge mkvextract mkvinfo mkvpropedit ffmpeg
```

### Test the script:
```bash
python unlinkmkv.py --help
```

### Run with debug logging (no actual file needed):
```bash
python unlinkmkv.py --loglevel DEBUG
```

## 6. Basic Usage

```bash
# Process a single file
python unlinkmkv.py path/to/segmented.mkv

# Process with audio/video fixes
python unlinkmkv.py --fixaudio --fixvideo file.mkv

# Process entire directory
python unlinkmkv.py /path/to/directory/

# Custom output location
python unlinkmkv.py --outdir /output/path file.mkv
```

## Troubleshooting

### "command not found" errors
The external tools aren't in your PATH. Either:
1. Install them system-wide (see step 3)
2. Specify full paths in `unlinkmkv.ini`:
   ```ini
   ffmpeg = /full/path/to/ffmpeg
   mkvmerge = /full/path/to/mkvmerge
   mkvextract = /full/path/to/mkvextract
   mkvinfo = /full/path/to/mkvinfo
   mkvpropedit = /full/path/to/mkvpropedit
   ```

### "No space left on device"
Use a custom tmpdir with more space:
```bash
python unlinkmkv.py --tmpdir /path/to/large/drive/tmp file.mkv
```

### Keep temporary files for debugging
```bash
python unlinkmkv.py --no-cleanup --loglevel DEBUG file.mkv
```
