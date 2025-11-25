# UnlinkMKV - Python Version

Automate the tedious process of unlinking segmented MKV files.

This is a Python port of the original Perl script by Garret Noling. It provides the same functionality with improved maintainability and cross-platform compatibility.

## What is UnlinkMKV?

A segmented MKV is an MKV that utilizes external additional MKV files to create a "whole" MKV. A common example is when an anime series uses the same introduction and ending in every episode - the encoder will break the introduction and ending into their own MKV files, and then "link" to the segments as chapters in each episode's individual MKV. The problem is that very few players/filters/splitters support this, so this script automates the mkvtoolnix tools to "rebuild" each episode into "complete" MKVs.

## Features

- Automatically detects and processes segmented MKV files
- Preserves chapter information
- Optional audio/video re-encoding for codec compatibility
- Subtitle style normalization across segments
- FLAC audio handling (temporary conversion for processing)
- Attachment extraction and merging
- Metadata preservation

## Installation

### Requirements

- Python >= 3.8
- MKVToolnix >= 5.1.0 (mkvmerge, mkvextract, mkvinfo, mkvpropedit)
- FFmpeg (real version, not libav fork)

### Install Python Dependencies

```bash
pip install -r requirements.txt
```

Or install the package:

```bash
pip install -e .
```

### Configuration

Copy the example configuration file:

```bash
cp unlinkmkv.ini.dist unlinkmkv.ini
```

Edit `unlinkmkv.ini` to set paths to your tools and customize encoding settings.

## Usage

### Basic Usage

Process a single file:
```bash
python unlinkmkv.py princess-resurrection-ep-1.mkv
```

Process all MKV files in a directory:
```bash
python unlinkmkv.py /path/to/directory
```

Process current directory (default):
```bash
python unlinkmkv.py
```

### Common Options

```bash
# Re-encode audio and video for compatibility
python unlinkmkv.py --fixaudio --fixvideo file.mkv

# Custom output directory
python unlinkmkv.py --outdir /output/path file.mkv

# Custom temporary directory (useful for limited /tmp space)
python unlinkmkv.py --tmpdir /large/tmp/dir file.mkv

# Disable chapter inclusion
python unlinkmkv.py --no-chapters file.mkv

# Enable debug logging
python unlinkmkv.py --loglevel DEBUG file.mkv

# Force subtitle resolution
python unlinkmkv.py --playresx 1920 --playresy 1080 file.mkv
```

### All Options

```
--tmpdir               Set custom temporary/working folder
--outdir               Output directory (default: ./UMKV)
--fixaudio, --fa       Re-encode audio to AC3 320k
--fixvideo, --fv       Re-encode video to h264
--fixsubtitles, --fs   Fix subtitle styles (default: on)
--playresx             Force subtitle X resolution
--playresy             Force subtitle Y resolution
--ignoredefaultflag    Keep non-default chapters
--ignoresegmentstart   Ignore segment start times
--chapters             Include chapters (default: on)
--no-chapters          Exclude chapters
--cleanup              Cleanup temp files (default: on)
--no-cleanup           Keep temporary files
--edition N            Select which edition to keep (default: 1)
--ffmpeg PATH          Path to ffmpeg binary
--mkvext PATH          Path to mkvextract binary
--mkvinfo PATH         Path to mkvinfo binary
--mkvmerge PATH        Path to mkvmerge binary
--mkvpropedit PATH     Path to mkvpropedit binary
--fixvideotemplate     Custom FFmpeg video encoding template
--fixaudiotemplate     Custom FFmpeg audio encoding template
--loglevel LEVEL       Logging level (DEBUG, INFO, WARN, ERROR)
```

## Configuration Templates

The INI file supports variable templates for encoding. Variables can reference other variables and perform simple math:

```ini
fixvideotemplate = -c:v libx264 -b:v {var_minrate}k -minrate {var_minrate}k -maxrate {var_maxrate}k -bufsize 1835k
fixaudiotemplate = -map 0 -acodec ac3 -ab 320k
var_minrate = (var_size * 1.1) / var_duration
var_maxrate = var_minrate * 2
```

Special variables provided automatically:
- `var_bitrate` - Original file bitrate
- `var_size` - Original file size (KB)
- `var_duration` - Original file duration (seconds)

## Example Workflow

Given these files:
```
princess-resurrection-ep-1.mkv
princess-resurrection-clean-opening.mkv
princess-resurrection-clean-ending.mkv
```

Where `ep-1.mkv` links to the opening and ending files:

1. First attempt (no encoding):
   ```bash
   python unlinkmkv.py princess-resurrection-ep-1.mkv
   ```

2. Check the output in `./UMKV/` - test audio/video transitions

3. If there are problems, re-encode:
   ```bash
   python unlinkmkv.py --fixaudio --fixvideo princess-resurrection-ep-1.mkv
   ```

4. Process entire directory:
   ```bash
   python unlinkmkv.py --fixaudio --fixvideo "/home/user/videos/Princess Resurrection"
   ```

## Differences from Perl Version

- Written in Python 3.8+ instead of Perl
- Uses `lxml` for XML processing instead of XML::LibXML
- Uses native Python `subprocess`, `pathlib`, and `argparse` modules
- Same functionality and command-line interface
- Same configuration file format

## License

MIT License

Copyright (c) 2016-2022 Garret C. Noling (original Perl version)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Support

For issues with the Python port, please file an issue in the repository.

For questions about the original Perl version, see: https://github.com/gnoling/UnlinkMKV
