#!/usr/bin/env python3
"""
UnlinkMKV - Undo segment linking in MKV files
Python port of the original Perl script by Garret Noling
Original: Garret Noling <garret@werockjustbecause.com> 2013-2022
Python port: 2024
"""

import argparse
import configparser
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import zlib
from datetime import timedelta
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lxml import etree as ET

# Set high precision for Decimal calculations
getcontext().prec = 50


class UnlinkMKV:
    """Main class for processing segmented MKV files."""

    def __init__(self, options: Dict):
        """Initialize UnlinkMKV with options."""
        self.opt = options
        self.tmpdir = None
        self.roottmp = None
        self.attachdir = None
        self.partsdir = None
        self.encodesdir = None
        self.subtitlesdir = None
        self.segments = {}
        self.flac_items = {}
        self.logger = logging.getLogger(__name__)
        self.indent_level = 0
        self.mktmp()

    def __del__(self):
        """Cleanup temporary directories on destruction."""
        if self.tmpdir and self.tmpdir.exists() and self.opt.get('cleanup', True):
            try:
                os.chdir(self.opt['outdir'])
                shutil.rmtree(self.tmpdir, ignore_errors=True)
                self.logger.debug(f"removed tmp {self.tmpdir}")
                if self.roottmp and self.roottmp.exists():
                    try:
                        self.roottmp.rmdir()
                        self.logger.debug(f"removed tmp {self.roottmp}")
                    except OSError:
                        pass
            except Exception as e:
                self.logger.debug(f"Error cleaning up: {e}")

    def mktmp(self):
        """Create temporary directory structure."""
        if not self.opt.get('tmpdir'):
            self.roottmp = Path.cwd() / "UnlinkMKV" / "tmp"
            self.tmpdir = self.roottmp / str(os.getpid())
        else:
            self.roottmp = Path(self.opt['tmpdir'])
            self.tmpdir = self.roottmp / str(os.getpid())

        if self.tmpdir.exists():
            try:
                shutil.rmtree(self.tmpdir)
                self.logger.debug(f"removed tmp {self.tmpdir}")
            except (OSError, PermissionError) as e:
                self.logger.error(f"failed to remove tmp {self.tmpdir}: {e}")
                raise RuntimeError(f"Cannot clean up temporary directory: {e}")

        self.attachdir = self.tmpdir / 'attach'
        self.partsdir = self.tmpdir / 'parts'
        self.encodesdir = self.tmpdir / 'encodes'
        self.subtitlesdir = self.tmpdir / 'subtitles'

        for directory in [self.tmpdir, self.attachdir, self.partsdir,
                         self.encodesdir, self.subtitlesdir]:
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                self.logger.error(f"failed to create directory {directory}: {e}")
                if e.errno == 12:  # Cannot allocate memory
                    raise RuntimeError(
                        f"Cannot create temporary directory on this filesystem.\n"
                        f"The error '{e}' usually indicates filesystem limitations on external drives.\n"
                        f"Solution: Use --tmpdir to specify a location on your local drive:\n"
                        f"  python unlinkmkv.py --tmpdir /tmp/unlinkmkv ..."
                    )
                raise RuntimeError(f"Cannot create temporary directory structure: {e}")

        self.logger.debug(f"created tmp {self.tmpdir}")

    def more(self):
        """Increase indentation level for logging."""
        self.indent_level += 1

    def less(self):
        """Decrease indentation level for logging."""
        self.indent_level = max(0, self.indent_level - 1)
        print()  # Empty line after section

    def _log(self, level, message):
        """Log with indentation."""
        indent = " " * (self.indent_level * 2)
        getattr(self.logger, level)(f"{indent}{message}")

    def info(self, message):
        """Log info message with indentation."""
        self._log('info', message)

    def debug(self, message):
        """Log debug message with indentation."""
        self._log('debug', message)

    def warn(self, message):
        """Log warning message with indentation."""
        self._log('warning', message)

    def error(self, message):
        """Log error message with indentation."""
        self._log('error', message)

    def sys(self, *args) -> str:
        """Execute system command and return output."""
        self.logger.debug(f"sys > {' '.join(str(a) for a in args)}")
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False
            )
            output = result.stdout + result.stderr
            for line in output.splitlines():
                self.logger.debug(f"sys < {line}")

            # Check if command failed
            if result.returncode != 0:
                self.error(f"Command failed with exit code {result.returncode}")
                self.error(f"Command: {' '.join(str(a) for a in args)}")
                if result.stderr:
                    for line in result.stderr.splitlines():
                        self.error(f"  {line}")
                raise RuntimeError(f"Command failed with exit code {result.returncode}")

            return output
        except subprocess.SubprocessError as e:
            self.error(f"Command execution failed: {e}")
            raise

    def is_linked(self, item: Path) -> bool:
        """Check if MKV file contains segmented chapters."""
        self.more()
        output = self.sys(
            self.opt['mkvext'], '--ui-language', self.opt['locale'],
            'chapters', str(item)
        )
        linked = '<ChapterSegmentUID' in output
        if linked:
            self.info("file contains segmented chapters")
        else:
            self.debug("file does not contain segmented chapters")
        self.less()
        return linked

    def mkvinfo(self, file: Path) -> Tuple[str, str]:
        """Get segment UID and duration from MKV file."""
        output = self.sys(
            self.opt['mkvmerge'], '-F', 'json', '--identify', str(file)
        )
        info = json.loads(output)
        duration_ns = info['container']['properties']['duration']
        duration_s = duration_ns / 1e9
        segment_uid = info['container']['properties']['segment_uid']

        # Convert to timecode format
        td = timedelta(seconds=duration_s)
        hours = int(td.total_seconds() // 3600)
        minutes = int((td.total_seconds() % 3600) // 60)
        seconds = int(td.total_seconds() % 60)
        timecode = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        return (segment_uid, timecode)

    def has_flac(self, item: Path) -> bool:
        """Check if MKV file contains FLAC audio."""
        output = self.sys(
            self.opt['mkvinfo'], '--ui-language', self.opt['locale'], str(item)
        )
        return 'Codec ID: A_FLAC' in output

    def add_duration_to_timecode(self, time: str, dur: str) -> str:
        """Add two timecodes together with high precision."""
        th, tm, ts = time.split(':')
        dh, dm, ds = dur.split(':')

        ts = Decimal(ts)
        ds = Decimal(ds)
        small = Decimal('0.000000001')
        sixty = Decimal('60.000000000')

        ts += ds + small

        if ts >= sixty:
            ts -= sixty
            dm = int(dm) + 1

        tm = int(tm) + int(dm)
        if tm >= 60:
            tm -= 60
            dh = int(dh) + 1

        th = int(th) + int(dh)

        # Format with zero-padding: HH:MM:SS.nnnnnnnnn
        ts_str = f"{float(ts):012.9f}"  # 12 chars total (SS.nnnnnnnnn)
        return f"{th:02d}:{tm:02d}:{ts_str}"

    def setpart(self, link: str, file: Path) -> Path:
        """Copy segment part to temporary directory."""
        part = self.partsdir / link
        self.debug(f"copying part {file} to {part}")
        try:
            shutil.copy2(file, part)
        except (PermissionError, OSError):
            # Fall back to copy without metadata if copy2 fails
            shutil.copy(file, part)
        return part

    def replace(self, dest: Path, source: Path):
        """Replace destination file with source."""
        if dest.exists():
            dest.unlink()
        shutil.move(str(source), str(dest))

    def uniquify_substyles(self, subtitles: List[Path]) -> List[str]:
        """Make subtitle styles unique across multiple subtitle files."""
        styles = []
        for sub_file in subtitles:
            self.debug(str(sub_file))
            uniq = zlib.crc32(str(sub_file).encode())

            with open(sub_file, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()

            new_lines = []
            in_styles = False
            in_dialogue = False
            key_idx = None

            for line in lines:
                if line.startswith('[') and 'V4+ Styles' in line:
                    in_styles = True
                    in_dialogue = False
                    key_idx = None
                    new_lines.append(line)
                    continue

                if (in_styles or in_dialogue) and not key_idx and line.lower().startswith('format:'):
                    test = line.replace(' ', '').lower().replace('format:', '')
                    parts = test.split(',')
                    for i, part in enumerate(parts):
                        if in_styles and part.strip() == 'name':
                            key_idx = i
                            break
                        elif in_dialogue and part.strip() == 'style':
                            key_idx = i
                            break
                    new_lines.append(line)
                    continue

                if in_styles and key_idx is not None and line.lower().startswith('style:'):
                    line = line.replace('Style:', '', 1).replace('style:', '', 1).lstrip()
                    parts = line.split(',')
                    parts[key_idx] = f"{parts[key_idx]} u{uniq}"
                    line = "Style: " + ','.join(parts)
                    styles.append(line)
                    self.debug(line.strip())
                    new_lines.append(line)
                    continue

                if line.startswith('[Events'):
                    in_styles = False
                    in_dialogue = True
                    key_idx = None
                    new_lines.append(line)
                    continue

                if in_dialogue and key_idx is not None and line.lower().startswith('dialogue:'):
                    line = line.replace('Dialogue:', '', 1).replace('dialogue:', '', 1).lstrip()
                    parts = line.split(',', key_idx + 1)
                    if len(parts) > key_idx:
                        parts[key_idx] = f"{parts[key_idx]} u{uniq}"
                        line = "Dialogue: " + ','.join(parts)
                    new_lines.append(line)
                    continue

                new_lines.append(line)

            with open(sub_file, 'w', encoding='utf-8-sig') as f:
                f.writelines(new_lines)

        return styles

    def mush_substyles(self, subtitles: List[Path], styles: List[str]):
        """Apply unified styles to all subtitle files."""
        for sub_file in subtitles:
            with open(sub_file, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()

            new_lines = []
            in_styles = False

            for line in lines:
                if line.startswith('[') and 'V4+ Styles' in line:
                    in_styles = True
                    new_lines.append(line)
                    continue

                if in_styles and line.lower().startswith('format:'):
                    new_lines.append(line)
                    for style in styles:
                        new_lines.append(style)
                    continue

                if in_styles and line.lower().startswith('style:'):
                    # Skip old styles
                    continue

                if in_styles and line.startswith('['):
                    in_styles = False
                    new_lines.append(line)
                    continue

                if self.opt.get('playresx') and line.startswith('PlayResX:'):
                    new_lines.append(f"PlayResX: {self.opt['playresx']}\n")
                    continue

                if self.opt.get('playresy') and line.startswith('PlayResY:'):
                    new_lines.append(f"PlayResY: {self.opt['playresy']}\n")
                    continue

                new_lines.append(line)

            with open(sub_file, 'w', encoding='utf-8-sig') as f:
                f.writelines(new_lines)

    def parseoptvars(self, vars_dict: Dict) -> Dict:
        """Parse and evaluate template variables."""
        V = {}
        for key, value in vars_dict.items():
            V[f"var_{key}"] = str(value)

        # Add custom vars from options
        for key, value in self.opt.items():
            if key.startswith('var_'):
                V[key] = str(value)

        # Evaluate variable expressions
        for _ in range(len(V) * len(V)):  # Multiple passes to resolve dependencies
            for var in list(V.keys()):
                expr = V[var]
                # Find all variable references in the expression
                for word in re.findall(r'[a-z]\w+', expr, re.IGNORECASE):
                    if word in V and V[word]:
                        expr = expr.replace(word, V[word])

                # Try to evaluate if it's a math expression
                if not re.search(r'[a-z]', expr, re.IGNORECASE):
                    try:
                        # Safe eval: only allow numbers and basic math operators
                        if re.match(r'^[\d\s+\-*/().]+$', expr):
                            V[var] = str(int(eval(expr) + 0.5))
                        else:
                            V[var] = expr
                    except (ValueError, SyntaxError, ZeroDivisionError):
                        V[var] = expr
                else:
                    V[var] = expr

        return V

    def ffdetails(self, file: Path) -> Dict:
        """Extract file details using ffmpeg."""
        output = self.sys(self.opt['ffmpeg'], '-i', str(file))

        duration = 0
        size = int(file.stat().st_size / 1024 + 0.5)
        bitrate = 0

        for line in output.splitlines():
            if match := re.search(r'duration: (\d+):(\d+):(\d+\.\d+)', line, re.IGNORECASE):
                hours, minutes, seconds = match.groups()
                duration = int(hours) * 3600 + int(minutes) * 60 + int(float(seconds) + 0.5)
                self.debug(f"duration [{hours}:{minutes}:{seconds}] = {duration} seconds")

            if match := re.search(r'bitrate: (\d+) k', line, re.IGNORECASE):
                bitrate = int(match.group(1))
                self.debug(f"bitrate {bitrate}k")

        return {
            'bitrate': bitrate,
            'size': size,
            'duration': duration,
        }

    def process(self, item: Path):
        """Process a segmented MKV file."""
        origpath = item.parent
        os.chdir(origpath)

        self.info(f"processing {item}")
        self.more()

        self.info("checking if file is segmented")
        if not self.is_linked(item):
            self.less()
            return

        self.info("generating chapter file")
        self.more()

        parent = item.stem
        suffix = item.suffix

        self.info("loading chapters")
        self.more()

        xml_str = self.sys(
            self.opt['mkvext'], '--ui-language', self.opt['locale'],
            'chapters', str(item)
        )
        xml = ET.fromstring(xml_str.encode())

        # Save original chapters
        with open(self.tmpdir / f"{parent}-chapters-original.xml", 'wb') as f:
            f.write(ET.tostring(xml, pretty_print=True))

        segments = []
        splits = []
        offs_time_end = '00:00:00.000000000'
        last_time_end = '00:00:00.000000000'
        offset = '00:00:00.000000000'
        chaptercount = 1
        lastuid = None

        # Remove non-default editions if ignoredefaultflag is not set
        for edition in xml.findall('.//EditionFlagDefault[.="0"]/..'):
            if not self.opt.get('ignoredefaultflag'):
                edition.getparent().remove(edition)
                self.warn("non-default chapter dropped")
            else:
                self.info("non-default chapter kept on purpose")

        edition_idx = self.opt.get('edition', 1)
        edition_path = f"//EditionEntry[{edition_idx}]/ChapterAtom"

        for chapter in xml.xpath(edition_path):
            chapter_start_elem = chapter.find('ChapterTimeStart')
            chapter_end_elem = chapter.find('ChapterTimeEnd')

            if chapter_start_elem is None or chapter_end_elem is None:
                continue

            chapter_start = chapter_start_elem.text
            chapter_end = chapter_end_elem.text

            chapter_enabled_elem = chapter.find('ChapterFlagEnabled')
            chapter_enabled = int(chapter_enabled_elem.text) if chapter_enabled_elem is not None else 1

            segment_uid_elem = chapter.find('ChapterSegmentUID')

            if segment_uid_elem is not None and chapter_enabled:
                segment_uid_text = segment_uid_elem.text.strip()

                # Handle different formats (hex/ascii)
                fmt = segment_uid_elem.get('format', 'hex')
                if fmt == 'hex':
                    segment_uid_text = segment_uid_text.replace('\n', '').replace(' ', '')
                elif fmt == 'ascii':
                    segment_uid_text = ''.join(f"{ord(c):x}" for c in segment_uid_text)

                if segment_uid_text == lastuid:
                    chapter.remove(segment_uid_elem)
                    goto_psegment = True
                else:
                    goto_psegment = False
                    segments.append({
                        'start': chapter_start,
                        'stop': chapter_end,
                        'id': segment_uid_text,
                        'split_start': last_time_end
                    })

                    if last_time_end != '00:00:00.000000000':
                        splits.append(last_time_end)

                    offset = self.add_duration_to_timecode(offset, chapter_end)

                    if offs_time_end == '00:00:00.000000000' and chaptercount > 1:
                        chapter_start_elem.text = offset
                        chapter_end_elem.text = self.add_duration_to_timecode(offset, chapter_end)
                    else:
                        chapter_start_elem.text = offs_time_end
                        chapter_end_elem.text = self.add_duration_to_timecode(offs_time_end, chapter_end)

                    offs_time_end = chapter_end_elem.text
                    chapter.remove(segment_uid_elem)
                    self.info("external")
                    lastuid = segment_uid_text
            else:
                goto_psegment = True

            if goto_psegment:
                segments.append({
                    'file': self.setpart(item.name, item.resolve()),
                    'start': chapter_start,
                    'stop': chapter_end,
                    'split_start': chapter_start,
                    'split_stop': chapter_end
                })
                last_time_end = chapter_end
                chapter_start_elem.text = self.add_duration_to_timecode(chapter_start, offset)
                chapter_end_elem.text = self.add_duration_to_timecode(chapter_end, offset)
                offs_time_end = chapter_end_elem.text
                self.info("internal")

            self.more()
            self.info(f"chapter start   {chapter_start_elem.text}")
            self.info(f"chapter end     {chapter_end_elem.text}")
            self.info(f"offset  start   {offset}")
            self.info(f"offset  end     {offs_time_end}")
            self.info(f"chapter enabled {chapter_enabled}")
            self.less()
            chaptercount += 1

        self.less()

        # Remove non-selected editions
        for i, edition in enumerate(xml.findall('.//EditionEntry'), 1):
            if i != edition_idx:
                edition.getparent().remove(edition)

        # Remove ordered flag
        for flag in xml.findall('.//EditionFlagOrdered'):
            flag.getparent().remove(flag)

        self.info("writing chapter temporary file")
        self.more()
        with open(self.tmpdir / f"{parent}-chapters.xml", 'wb') as f:
            f.write(ET.tostring(xml, pretty_print=True, xml_declaration=True, encoding='UTF-8'))
        self.less()

        self.info("looking for segment parts")
        self.more()

        if not self.segments:
            for mkv_file in origpath.glob('*.mkv'):
                mkv_path = mkv_file.resolve()
                seg_id, dur = self.mkvinfo(mkv_path)
                self.segments[seg_id] = {
                    'file': mkv_path,
                    'dur': dur,
                }

        for seg in segments:
            if 'id' not in seg:
                continue
            if seg['id'] in self.segments and self.segments[seg['id']]['file'].name != item.name:
                seg['file'] = self.setpart(
                    self.segments[seg['id']]['file'].name,
                    self.segments[seg['id']]['file']
                )
                self.info(f"found part {seg['file']}")

        self.less()

        self.info("checking that all required segments were found")
        self.more()
        okay_to_proceed = True
        for seg in segments:
            if 'id' in seg and 'file' not in seg:
                self.warn(f"missing segment: {seg['id']}")
                okay_to_proceed = False

        if okay_to_proceed:
            self.info("all segments found")
        else:
            self.warn("missing segments")
            self.less()
            self.less()
            return

        self.less()

        # FLAC→ALAC conversion (required for mkvmerge splitting)
        # Keep ALAC in output (don't convert back to FLAC)
        self.info("flac check")
        self.more()
        if self.has_flac(item):
            self.info(f"{item.name} has flac, converting to alac for processing")
            outfile = self.tmpdir / f"{item.name.replace('.mkv', '')}-alac.mkv"
            self.sys(
                self.opt['ffmpeg'], '-i', str(item), '-vcodec', 'copy',
                '-map', '0', '-acodec', 'alac', str(outfile)
            )
            item = outfile

        for i, seg in enumerate(segments):
            if 'file' in seg and self.has_flac(seg['file']):
                self.info(f"{seg['file'].name} has flac, converting to alac for processing")
                outfile = self.tmpdir / f"{seg['file'].name.replace('.mkv', '')}-alac.mkv"
                if not outfile.exists():
                    self.sys(
                        self.opt['ffmpeg'], '-i', str(seg['file']), '-vcodec', 'copy',
                        '-map', '0', '-acodec', 'alac', str(outfile)
                    )
                segments[i]['file'] = outfile

        self.less()

        # Read metadata
        self.info("reading metadata")
        meta = []
        metaid = {}

        in_track = False
        NAME, TYPE, LANG, DEF = None, None, None, None

        for line in self.sys(self.opt['mkvinfo'], '--ui-language', self.opt['locale'], str(item)).splitlines():
            if re.match(r'^\| ?\+', line):
                in_track = False
                if TYPE:
                    m = []
                    if LANG:
                        m.extend(['--edit', f"track:{TYPE}{metaid.get(TYPE, 1)}", '--set', f"language={LANG}"])
                    if NAME:
                        m.extend(['--edit', f"track:{TYPE}{metaid.get(TYPE, 1)}", '--set', f'name="{NAME}"'])
                    if DEF:
                        m.extend(['--edit', f"track:{TYPE}{metaid.get(TYPE, 1)}", '--set', f"flag-default={DEF}"])
                    if m:
                        meta.append(m)
                NAME, LANG, TYPE, DEF = None, None, None, None

            if re.search(r'^\| \+ Title: (.*)', line):
                title = re.search(r'^\| \+ Title: (.*)', line).group(1)
                meta.append(['--edit', 'info', '--set', f'title="{title}"'])

            if re.search(r'^\| \+ A track|^\| \+ Track', line):
                in_track = True
            elif in_track and (match := re.search(r'\|  \+ Language: (.*)$', line)):
                LANG = match.group(1)
            elif in_track and (match := re.search(r'\|  \+ Track type: (.*)', line)):
                track_type = match.group(1)
                if track_type == 'audio':
                    TYPE = 'a'
                elif track_type == 'subtitles':
                    TYPE = 's'
                if TYPE:
                    metaid[TYPE] = metaid.get(TYPE, 0) + 1
            elif in_track and (match := re.search(r'\|  \+ Name: (.*)', line)):
                NAME = match.group(1)
            elif in_track and (match := re.search(r'\|  \+ Default flag: (.*)', line)):
                DEF = match.group(1)

        # Handle attachments
        self.info("searching attachments")
        self.more()

        for seg in segments:
            if 'file' not in seg:
                continue
            file = seg['file']
            self.info(str(file))
            self.more()

            in_att = False
            N, T, D, U = None, None, None, None
            attachments = []

            for line in self.sys(self.opt['mkvinfo'], '--ui-language', self.opt['locale'], str(file)).splitlines():
                if re.search(r'\|[\s\t]+\+[\s\t]+Attached', line, re.IGNORECASE):
                    in_att = True
                elif in_att and (match := re.search(r'File name: (.*)', line, re.IGNORECASE)):
                    N = match.group(1)
                elif in_att and (match := re.search(r'Mime type: (.*)', line, re.IGNORECASE)):
                    T = match.group(1)
                elif in_att and (match := re.search(r'File data[,:]? size[:]? (.*)', line, re.IGNORECASE)):
                    D = match.group(1)
                elif in_att and (match := re.search(r'File UID: (.*)', line, re.IGNORECASE)):
                    U = match.group(1)

                if N and T and D and U:
                    att_path = self.attachdir / N
                    if not att_path.exists():
                        attachments.append({'name': N, 'type': T, 'data': D, 'UID': U})
                        self.info(f"found {N}")
                    else:
                        self.info(f"skipping (duplicate) {N}")
                    N, T, D, U = None, None, None, None

            if attachments:
                self.info("extracting attachments...")
                old_dir = Path.cwd()
                os.chdir(self.attachdir)
                self.sys(
                    self.opt['mkvext'], '--ui-language', self.opt['locale'],
                    'attachments', str(file), *[str(i) for i in range(1, len(attachments) + 1)]
                )
                os.chdir(old_dir)
                seg['attachments'] = attachments

            self.less()

        self.less()

        # Collect attachments for final merge
        atts = []
        for item_path in self.attachdir.iterdir():
            if item_path.is_file():
                atts.extend(['--attachment-mime-type', 'application/x-truetype-font', '--attach-file', str(item_path)])

        # Create splits if needed
        if splits:
            self.info(f"creating {len(splits) + 1} splits from {item}")
            self.more()
            self.sys(
                self.opt['mkvmerge'], '--ui-language', self.opt['locale'],
                '--no-chapters', '-o', str(self.partsdir / "split-%03d.mkv"),
                str(item), '--split', 'timecodes:' + ','.join(splits)
            )
            self.less()

        # Set up parts list
        self.info("setting parts")
        self.more()
        parts = []
        count = 1
        LAST = None

        for i, segment in enumerate(segments):
            self.debug(f"segment {i}: id={segment.get('id', 'none')}, has_file={('file' in segment)}, start={segment.get('start', 'none')}")
            if 'id' in segment and (self.opt.get('ignoresegmentstart') or segment['start'].startswith('00:00:00.')):
                # External segment - use the linked file
                if 'file' in segment:
                    self.info(f"part {segment['file']}")
                    parts.append(segment['file'])
            elif 'file' in segment and (LAST != segment.get('file') or not splits):
                # Internal segment with file - either use directly or it's a split
                if splits:
                    # This internal segment is part of the split file
                    f = self.partsdir / f"split-{count:03d}.mkv"
                    self.info(f"part {f}")
                    parts.append(f)
                    count += 1
                else:
                    # No splits, use the file directly
                    self.info(f"part {segment['file']}")
                    parts.append(segment['file'])
            LAST = segment.get('file')

        self.less()

        # Extract and fix subtitles
        subs = {}
        if self.opt.get('fixsubtitles', True):
            self.info("extracting subs")
            self.more()

            for part in parts:
                self.debug(str(part))
                in_track = False
                sub = False
                T = None

                for line in self.sys(self.opt['mkvinfo'], '--ui-language', self.opt['locale'], str(part)).splitlines():
                    if re.search(r'^\| \+ A track|^\| \+ Track', line):
                        in_track = True
                        sub = False
                        T = None
                    elif in_track and 'Track type: subtitles' in line:
                        sub = True
                    elif in_track and (match := re.search(r'Track number: .*: (\d)\)$', line)):
                        T = match.group(1)

                    if in_track and sub and T:
                        sf = self.subtitlesdir / f"{part.name}-{T}.ass"
                        self.sys(
                            self.opt['mkvext'], '--ui-language', self.opt['locale'],
                            'tracks', str(part), f"{T}:{sf}"
                        )
                        if part not in subs:
                            subs[part] = []
                        subs[part].append(sf)
                        T = None
                        in_track = False
                        sub = False

            self.less()

            if subs:
                self.info("making substyles unique")
                self.more()
                all_styles = []
                for sub_files in subs.values():
                    all_styles.extend(self.uniquify_substyles(sub_files))
                self.less()

                self.info("mashing unique substyles to all parts")
                self.more()
                for sub_files in subs.values():
                    self.mush_substyles(sub_files, all_styles)
                self.less()

                self.info("remuxing subtitles")
                self.more()
                for part, sub_files in subs.items():
                    self.debug(str(part))
                    stracks = [str(s) for s in sub_files]
                    self.sys(
                        self.opt['mkvmerge'], '--ui-language', self.opt['locale'],
                        '-o', f"{part}-fixsubs.mkv", '--no-chapters', '--no-subs',
                        str(part), *stracks, *atts
                    )
                    self.replace(part, Path(f"{part}-fixsubs.mkv"))
                self.less()

        # Encode parts if needed
        if self.opt.get('fixvideo') or self.opt.get('fixaudio'):
            self.info("encoding parts")
            self.more()

            for part in parts:
                vopt = ['-vcodec', 'copy']
                aopt = ['-map', '0', '-acodec', 'copy']
                self.warn(str(part))

                if self.opt.get('fixvideo'):
                    vv = self.parseoptvars(self.ffdetails(part))
                    template = self.opt['fixvideotemplate']
                    template = template.replace('\t', ' ').replace('  ', ' ')
                    for var, val in vv.items():
                        template = template.replace(f"{{{var}}}", val)
                    vopt = template.split()

                if self.opt.get('fixaudio'):
                    template = self.opt['fixaudiotemplate']
                    template = template.replace('\t', ' ').replace('  ', ' ')
                    aopt = template.split()

                self.sys(
                    self.opt['ffmpeg'], '-i', str(part), *vopt, *aopt,
                    f"{part}-fixed.mkv"
                )
                self.replace(part, Path(f"{part}-fixed.mkv"))

            self.less()

        # Build final file
        self.info("building file")
        self.more()

        prts = []
        for part in parts:
            prts.append(str(part))
            prts.append('+')
        prts.pop()  # Remove last '+'

        output_file = self.encodesdir / item.name
        if self.opt.get('chapters', True):
            self.sys(
                self.opt['mkvmerge'], '--ui-language', self.opt['locale'],
                '--no-chapters', '-M', '--chapters',
                str(self.tmpdir / f"{parent}-chapters.xml"),
                '-o', str(output_file), *prts
            )
        else:
            self.sys(
                self.opt['mkvmerge'], '--ui-language', self.opt['locale'],
                '--no-chapters', '-M', '-o', str(output_file), *prts
            )

        self.less()

        # Fix subtitles again
        self.info("fixing subs, again... (maybe an mkvmerge issue?)")
        self.more()

        if self.opt.get('fixsubtitles', True):
            fs = []
            in_track = False
            sub = False
            T = None

            for line in self.sys(self.opt['mkvinfo'], '--ui-language', self.opt['locale'], str(output_file)).splitlines():
                if re.search(r'^\| \+ A track|^\| \+ Track', line):
                    in_track = True
                    sub = False
                    T = None
                elif in_track and 'Track type: subtitles' in line:
                    sub = True
                elif in_track and (match := re.search(r'Track number: .*: (\d)\)$', line)):
                    T = match.group(1)

                if in_track and sub and T:
                    sub_file = self.encodesdir / f"{T}.ass"
                    self.sys(
                        self.opt['mkvext'], '--ui-language', self.opt['locale'],
                        'tracks', str(output_file), f"{T}:{sub_file}"
                    )
                    fs.append(str(sub_file))
                    T = None
                    in_track = False
                    sub = False

            if fs:
                fixed_output = self.encodesdir / f"fixed.{item.name}"
                self.sys(
                    self.opt['mkvmerge'], '--ui-language', self.opt['locale'],
                    '-o', str(fixed_output), '-S', str(output_file), *fs
                )
                self.replace(output_file, fixed_output)

        self.less()

        # Apply metadata
        if meta and output_file.exists():
            self.info("applying metadata")
            self.more()
            for m in meta:
                self.sys(
                    self.opt['mkvpropedit'], '--ui-language', self.opt['locale'],
                    *m, str(output_file)
                )
            self.less()

        # Convert back to FLAC if needed - DISABLED
        # (not needed with modern FFmpeg, conversion skipped)

        # Move to final destination
        self.info("moving built file to final destination")
        self.more()

        if output_file.exists():
            Path(self.opt['outdir']).mkdir(parents=True, exist_ok=True)
            final_path = Path(self.opt['outdir']) / output_file.name
            shutil.move(str(output_file), str(final_path))
            self.info(f"Success! Output: {final_path}")
        else:
            self.warn("file failed to build")

        self.less()

        # Cleanup
        if self.opt.get('cleanup', True):
            self.mktmp()

        self.less()


def setup_logging(loglevel: str, colors: bool = False):
    """Set up logging configuration."""
    level = getattr(logging, loglevel.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )


def load_config(basedir: Path) -> Dict:
    """Load configuration from INI file."""
    inifile = basedir / "unlinkmkv.ini"
    opt = {
        'outdir': str((Path.cwd() / "UMKV").resolve()),
        'tmpdir': str((Path.cwd() / "UMKV.tmp").resolve()),
        'ffmpeg': 'ffmpeg',
        'mkvext': 'mkvextract',
        'mkvinfo': 'mkvinfo',
        'mkvmerge': 'mkvmerge',
        'mkvpropedit': 'mkvpropedit',
        'locale': 'en_US',
        'fixaudio': False,
        'fixvideo': False,
        'fixsubtitles': True,
        'ignoredefaultflag': False,
        'ignoresegmentstart': False,
        'chapters': True,
        'cleanup': True,
        'fixvideotemplate': '-c:v libx264 -b:v {var_minrate}k -minrate {var_minrate}k -maxrate {var_maxrate}k -bufsize 1835k',
        'fixaudiotemplate': '-map 0 -acodec ac3 -ab 320k',
        'edition': 1,
        'playresx': None,
        'playresy': None,
    }

    if inifile.exists():
        with open(inifile, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                match = re.match(r'^[\s\t]*([a-z0-9_]+)[\s\t]*=[\s\t]*["\']?([^\s\t].*[^\s\t]?)["\']?[\s\t]*$', line)
                if match:
                    key, val = match.groups()
                    val = val.replace('$basedir', str(basedir))
                    logging.debug(f"[ini] [{key}] = [{val}]")
                    opt[key] = int(val) if val.isdigit() else val
                else:
                    logging.debug(f"[ini] skipping line [{line}]")

    return opt


def find_executable(name: str) -> Optional[str]:
    """Find executable in PATH."""
    result = shutil.which(name)
    return result if result else name


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='UnlinkMKV - Automate the tedious process of unlinking segmented MKV files'
    )
    parser.add_argument('paths', nargs='*', help='Files or directories to process')
    parser.add_argument('--loglevel', '--ll', default='INFO', help='Log level (DEBUG, INFO, WARN, ERROR)')
    parser.add_argument('--colors', action='store_true', help='Enable colored logging')
    parser.add_argument('--tmpdir', help='Custom temporary/working folder')
    parser.add_argument('--outdir', help='Output directory')
    parser.add_argument('--fixaudio', '--fa', action='store_true', help='Re-encode audio')
    parser.add_argument('--no-fixaudio', dest='fixaudio', action='store_false')
    parser.add_argument('--fixvideo', '--fv', action='store_true', help='Re-encode video')
    parser.add_argument('--no-fixvideo', dest='fixvideo', action='store_false')
    parser.add_argument('--fixsubtitles', '--fs', action='store_true', default=None, help='Fix subtitle styles')
    parser.add_argument('--no-fixsubtitles', dest='fixsubtitles', action='store_false')
    parser.add_argument('--playresx', type=int, help='Force subtitle X resolution')
    parser.add_argument('--playresy', type=int, help='Force subtitle Y resolution')
    parser.add_argument('--ignoredefaultflag', action='store_true', help='Keep non-default chapters')
    parser.add_argument('--ignoresegmentstart', action='store_true', help='Ignore segment start times')
    parser.add_argument('--chapters', action='store_true', default=None, help='Include chapters')
    parser.add_argument('--no-chapters', dest='chapters', action='store_false')
    parser.add_argument('--cleanup', action='store_true', default=None, help='Cleanup temporary files')
    parser.add_argument('--no-cleanup', dest='cleanup', action='store_false')
    parser.add_argument('--ffmpeg', help='Path to ffmpeg binary')
    parser.add_argument('--mkvext', help='Path to mkvextract binary')
    parser.add_argument('--mkvinfo', help='Path to mkvinfo binary')
    parser.add_argument('--mkvmerge', help='Path to mkvmerge binary')
    parser.add_argument('--mkvpropedit', help='Path to mkvpropedit binary')
    parser.add_argument('--fixvideotemplate', help='FFmpeg video encoding template')
    parser.add_argument('--fixaudiotemplate', help='FFmpeg audio encoding template')
    parser.add_argument('--edition', type=int, help='Which edition to keep (1-based index)')

    args = parser.parse_args()

    setup_logging(args.loglevel, args.colors)
    logger = logging.getLogger(__name__)

    logger.info("UnlinkMKV")

    basedir = Path(__file__).parent.resolve()
    opt = load_config(basedir)

    # Override with command-line arguments
    for key, value in vars(args).items():
        if value is not None and key not in ['paths', 'loglevel', 'colors']:
            opt[key] = value

    # Resolve tool paths
    for tool in ['ffmpeg', 'mkvext', 'mkvinfo', 'mkvmerge', 'mkvpropedit']:
        if opt[tool]:
            exe_path = find_executable(opt[tool])
            if exe_path:
                opt[tool] = exe_path

    opt['outdir'] = str(Path(opt['outdir']).resolve())
    opt['tmpdir'] = str(Path(opt['tmpdir']).resolve())

    logger.info("Options")
    for key in sorted(opt.keys()):
        logger.info(f"  {key}: {opt[key]}")
    print()

    umkv = UnlinkMKV(opt)

    paths = args.paths if args.paths else [Path.cwd()]

    file_list = []
    for path_str in paths:
        path = Path(path_str)
        if path.is_dir():
            for mkv_file in path.glob('*.mkv'):
                if mkv_file.is_file():
                    out_path = Path(opt['outdir']) / mkv_file.name
                    if not out_path.exists():
                        file_list.append(mkv_file.resolve())
        elif path.is_file():
            file_list.append(path.resolve())

    for item in sorted(file_list):
        umkv.process(item)


if __name__ == '__main__':
    main()
