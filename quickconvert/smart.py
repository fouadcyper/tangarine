from __future__ import annotations

import json
import mimetypes
import functools
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .converter import human_size, run_conversion
from .settings import load_settings


@dataclass(frozen=True)
class DetectedFile:
    path: Path
    mime: str
    kind: str
    format: str


ARCHIVE_MIMES = {
    "application/zip", "application/x-7z-compressed", "application/x-tar",
    "application/gzip", "application/x-gzip", "application/x-bzip2",
    "application/x-xz", "application/x-rar", "application/vnd.rar",
}
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".rar"}
MIME_FORMATS = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "image/avif": "avif", "image/heic": "heic", "image/heif": "heic",
    "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov",
    "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
    "audio/flac": "flac", "audio/ogg": "ogg", "audio/mp4": "m4a",
    "application/pdf": "pdf", "application/zip": "zip",
    "application/x-7z-compressed": "7z",
}


def _mime_from_content(path: Path) -> str:
    if shutil.which("file"):
        result = subprocess.run(
            ["file", "--brief", "--mime-type", "--", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and "/" in result.stdout:
            return result.stdout.strip().splitlines()[0]
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _zip_kind(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
        if "BundleConfig.pb" in names and "base/manifest/AndroidManifest.xml" in names:
            return "aab"
    except (OSError, zipfile.BadZipFile):
        pass
    return None


def detect(path: Path) -> DetectedFile:
    path = path.resolve()
    mime = _mime_from_content(path)
    ext = path.suffix.lower().lstrip(".")
    zip_kind = _zip_kind(path) if mime in {"application/zip", "application/java-archive"} else None
    if zip_kind == "aab":
        kind = "aab"
        ext = "aab"
    elif mime.startswith("image/"):
        kind = "image"
    elif mime.startswith("video/"):
        kind = "video"
    elif mime.startswith("audio/"):
        kind = "audio"
    elif mime == "application/pdf":
        kind = "pdf"
        ext = "pdf"
    elif mime in ARCHIVE_MIMES or path.suffix.lower() in ARCHIVE_EXTENSIONS:
        kind = "archive"
    elif mime.startswith("text/") or mime in {
        "application/json", "application/xml", "application/rtf",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }:
        kind = "text"
    else:
        kind = "other"
    format_name = MIME_FORMATS.get(mime, {"jpeg": "jpg", "x-matroska": "mkv"}.get(ext, ext))
    return DetectedFile(path, mime, kind, format_name)


@functools.lru_cache(maxsize=1)
def _imagemagick_write_formats() -> set[str]:
    if not shutil.which("magick"):
        return set()
    result = subprocess.run(["magick", "-list", "format"], capture_output=True, text=True, check=False)
    writable: set[str] = set()
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) >= 3 and "w" in columns[2].lower():
            writable.add(columns[0].rstrip("*").lower())
    return writable


def _action_available(action_id: str) -> bool:
    command_requirements = {
        "image_pdf": "img2pdf", "images_pdf": "img2pdf",
        "image_clipboard": "wl-copy", "text_clipboard": "wl-copy",
        "pdf_png_all": "pdftoppm", "pdf_split": "pdfseparate",
        "pdf_rotate": "qpdf", "pdf_merge": "pdfunite",
        "archive_extract": "7z", "archive_zip": "7z", "archive_7z": "7z",
    }
    command = command_requirements.get(action_id)
    if command and not shutil.which(command):
        return False
    if action_id.endswith("_avif") and "avif" not in _imagemagick_write_formats():
        return False
    if action_id.endswith("_heic") and "heic" not in _imagemagick_write_formats():
        return False
    if action_id.startswith("aab_") and (not shutil.which("java") or not _bundletool_jar().is_file()):
        return False
    if action_id == "aab_sign_bundle" and not shutil.which("jarsigner"):
        return False
    return True


def _bundletool_jar() -> Path:
    return Path(__file__).resolve().parent.parent / "vendor" / "bundletool-all-1.18.3.jar"


def _action(action_id: str, label: str, icon: str) -> dict:
    return {"id": action_id, "label": label, "icon": icon}


def _conversion_actions(kind: str, current: str, targets: list[str], prefix: str) -> list[dict]:
    icons = {"pdf": "application-pdf-symbolic", "gif": "image-x-generic-symbolic"}
    return [
        _action(f"{prefix}_{target}", target.upper(), icons.get(target, f"{kind}-x-generic-symbolic"))
        for target in targets if target != current
    ]


def actions_for_paths(paths: list[Path]) -> dict:
    files = [detect(path) for path in paths if path.is_file()]
    if not files:
        raise ValueError("No supported local files were provided")
    kinds = {item.kind for item in files}
    settings = load_settings()
    primary: list[dict] = []
    more: list[dict] = []

    if len(files) > 1:
        if kinds == {"image"}:
            default = settings["default_image_format"]
            primary = [
                _action(f"batch_image_{default}", f"{default.upper()} ALL", "image-x-generic-symbolic"),
                _action("batch_image_compress", "COMPRESS", "document-save-symbolic"),
                _action("batch_image_resize", "RESIZE", "zoom-out-symbolic"),
                _action("images_pdf", "PDF", "application-pdf-symbolic"),
                _action("archive_zip", "ZIP", "package-x-generic-symbolic"),
            ]
            more = _conversion_actions("image", "", ["jpg", "png", "webp", "avif"], "batch_image") + [
                _action("batch_image_strip", "CLEAN META", "edit-clear-all-symbolic")
            ]
        elif kinds == {"pdf"}:
            primary = [
                _action("pdf_merge", "MERGE", "object-select-symbolic"),
                _action("batch_pdf_compress", "COMPRESS", "document-save-symbolic"),
                _action("batch_pdf_extract", "PAGES", "folder-pictures-symbolic"),
                _action("archive_zip", "ZIP", "package-x-generic-symbolic"),
            ]
        else:
            primary = [
                _action("archive_zip", "ZIP", "package-x-generic-symbolic"),
                _action("archive_7z", "7Z", "package-x-generic-symbolic"),
                _action("archive_targz", "TAR.GZ", "package-x-generic-symbolic"),
            ]
    else:
        item = files[0]
        if item.kind == "image":
            conversions = _conversion_actions("image", item.format, ["jpg", "png", "webp"], "image")
            primary = conversions[:2] + [
                _action("image_compress", "COMPRESS", "document-save-symbolic"),
                _action("image_resize", "RESIZE", "zoom-out-symbolic"),
                _action("image_pdf", "PDF", "application-pdf-symbolic"),
            ]
            more = conversions[2:] + _conversion_actions("image", item.format, ["avif", "heic"], "image") + [
                _action("image_crop", "CROP", "edit-cut-symbolic"),
                _action("image_rotate", "ROTATE", "object-rotate-right-symbolic"),
                _action("image_strip", "CLEAN META", "edit-clear-all-symbolic"),
                _action("image_clipboard", "COPY", "edit-copy-symbolic"),
            ]
        elif item.kind == "video":
            primary = [
                _action("video_compress", "COMPRESS", "document-save-symbolic"),
                _action("video_gif", "GIF", "image-x-generic-symbolic"),
                _action("video_audio", "MP3", "audio-x-generic-symbolic"),
            ] + _conversion_actions("video", item.format, ["mp4", "webm"], "video")[:1]
            more = _conversion_actions("video", item.format, ["mp4", "webm", "mov"], "video") + [
                _action("video_720p", "720P", "video-display-symbolic"),
                _action("video_trim", "TRIM", "edit-cut-symbolic"),
                _action("video_noaudio", "NO AUDIO", "audio-volume-muted-symbolic"),
                _action("video_fps30", "30 FPS", "preferences-system-time-symbolic"),
                _action("video_strip", "CLEAN META", "edit-clear-all-symbolic"),
            ]
        elif item.kind == "audio":
            primary = _conversion_actions("audio", item.format, ["mp3", "wav", "flac", "ogg"], "audio")[:3] + [
                _action("audio_compress", "COMPRESS", "document-save-symbolic")
            ]
            more = _conversion_actions("audio", item.format, ["mp3", "wav", "flac", "ogg", "m4a"], "audio") + [
                _action("audio_trim", "TRIM", "edit-cut-symbolic"),
                _action("audio_bitrate", "BITRATE", "audio-volume-high-symbolic"),
                _action("audio_metadata", "INFO", "dialog-information-symbolic"),
                _action("audio_strip", "CLEAN META", "edit-clear-all-symbolic"),
            ]
        elif item.kind == "pdf":
            primary = [
                _action("pdf_png_all", "IMAGES", "folder-pictures-symbolic"),
                _action("pdf_compress", "COMPRESS", "document-save-symbolic"),
                _action("pdf_split", "SPLIT", "view-list-symbolic"),
                _action("pdf_rotate", "ROTATE", "object-rotate-right-symbolic"),
            ]
        elif item.kind == "archive":
            primary = [
                _action("archive_extract", "EXTRACT", "folder-download-symbolic"),
                _action("archive_zip", "ZIP", "package-x-generic-symbolic"),
                _action("archive_7z", "7Z", "package-x-generic-symbolic"),
                _action("archive_targz", "TAR.GZ", "package-x-generic-symbolic"),
            ]
        elif item.kind == "aab":
            primary = [
                _action("aab_universal", "APK (TEST)", "application-x-executable-symbolic"),
                _action("aab_sign_apk", "SIGN APK", "security-high-symbolic"),
                _action("aab_sign_bundle", "SIGN AAB", "channel-secure-symbolic"),
                _action("aab_info", "DETAILS", "dialog-information-symbolic"),
                _action("archive_extract", "EXPLORE", "folder-open-symbolic"),
            ]
        elif item.kind == "text":
            if shutil.which("pandoc"):
                primary = _conversion_actions("text", item.format, ["txt", "md", "html"], "text")
            primary += [_action("text_clipboard", "COPY", "edit-copy-symbolic")]
        else:
            primary = [_action("archive_zip", "ZIP", "package-x-generic-symbolic")]

    # Remove duplicates while preserving contextual priority.
    seen: set[str] = set()
    primary = [item for item in primary if _action_available(item["id"]) and not (item["id"] in seen or seen.add(item["id"]))][:5]
    more = [item for item in more if _action_available(item["id"]) and item["id"] not in seen and not (item["id"] in seen or seen.add(item["id"]))]
    first = files[0]
    return {
        "kind": first.kind if len(kinds) == 1 else "mixed",
        "count": len(files),
        "name": first.path.name if len(files) == 1 else f"{len(files)} files",
        "size": human_size(sum(item.path.stat().st_size for item in files)),
        "primary": primary,
        "more": more,
        "mimes": [item.mime for item in files],
    }


def _target(source: Path, suffix: str, tag: str, settings: dict) -> Path:
    directory = source.parent
    if settings["output_mode"] == "custom" and settings["output_directory"]:
        requested = Path(settings["output_directory"]).expanduser()
        requested.mkdir(parents=True, exist_ok=True)
        directory = requested
    stem = source.stem
    base = directory / f"{stem}-{tag}{suffix}"
    if settings["overwrite"] or not base.exists():
        return base
    for number in range(2, 10_000):
        candidate = directory / f"{stem}-{tag}-{number}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not choose a safe output name")


def _run(command: list[str], output: Path) -> Path:
    run_conversion(command, output)
    return output


def _ffmpeg_base(source: Path) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-y", "-i", str(source)]


def image_dimensions(source: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["magick", "identify", "-format", "%w %h", f"{source}[0]"],
        capture_output=True, text=True, check=True,
    )
    width, height = result.stdout.strip().split()
    return int(width), int(height)


def resize_image(source: Path, width: int, height: int, mode: str, settings: dict | None = None) -> Path:
    settings = settings or load_settings()
    if not 1 <= width <= 10000 or not 1 <= height <= 10000:
        raise ValueError("Width and height must be between 1 and 10000 pixels")
    output = _target(source, source.suffix or ".png", f"{width}x{height}", settings)
    command = ["magick", f"{source}[0]", "-auto-orient"]
    if settings["remove_metadata"]:
        command.append("-strip")
    if mode == "inside":
        command += ["-resize", f"{width}x{height}>"]
    elif mode == "fill":
        command += ["-resize", f"{width}x{height}^", "-gravity", "center", "-extent", f"{width}x{height}"]
    elif mode == "stretch":
        command += ["-resize", f"{width}x{height}!"]
    else:
        raise ValueError("Unknown resize mode")
    return _run(command + [str(output)], output)


def crop_image(source: Path, width: int, height: int, circular: bool = False, settings: dict | None = None) -> Path:
    settings = settings or load_settings()
    if not 1 <= width <= 10000 or not 1 <= height <= 10000:
        raise ValueError("Width and height must be between 1 and 10000 pixels")
    if circular:
        side = min(width, height)
        output = _target(source, ".png", f"circle-{side}", settings)
        center = side / 2
        command = [
            "magick", f"{source}[0]", "-auto-orient", "-resize", f"{side}x{side}^",
            "-gravity", "center", "-extent", f"{side}x{side}",
            "(", "-size", f"{side}x{side}", "xc:none", "-fill", "white",
            "-draw", f"circle {center},{center} {center},0", ")",
            "-alpha", "off", "-compose", "CopyOpacity", "-composite",
        ]
    else:
        output = _target(source, source.suffix or ".png", f"crop-{width}x{height}", settings)
        command = [
            "magick", f"{source}[0]", "-auto-orient", "-resize", f"{width}x{height}^",
            "-gravity", "center", "-extent", f"{width}x{height}",
        ]
    if settings["remove_metadata"]:
        command.append("-strip")
    return _run(command + [str(output)], output)


def _single_action(action: str, source: Path, settings: dict) -> Path:
    iq = str(int(settings["image_quality"]))
    video_crf = str(round(34 - int(settings["video_quality"]) * 0.16))
    bitrate = str(settings["audio_bitrate"])
    strip = ["-map_metadata", "-1"] if settings["remove_metadata"] else []

    if action == "aab_universal":
        return build_universal_apk(source, settings)
    if action == "aab_info":
        out = _target(source, ".txt", "details", settings)
        result = subprocess.run(
            ["java", "-jar", str(_bundletool_jar()), "dump", "manifest", f"--bundle={source}"],
            capture_output=True, text=True, check=True,
        )
        out.write_text(result.stdout, encoding="utf-8")
        return out

    if action.startswith("image_"):
        op = action.removeprefix("image_")
        if op in {"jpg", "png", "webp", "avif", "heic"}:
            out = _target(source, f".{op}", "converted", settings)
            command = ["magick", f"{source}[0]", "-auto-orient"]
            if settings["remove_metadata"]:
                command += ["-strip"]
            if op == "jpg":
                command += ["-background", "white", "-alpha", "remove", "-quality", iq]
            elif op in {"webp", "avif", "heic"}:
                command += ["-quality", iq]
            return _run(command + [str(out)], out)
        if op == "pdf":
            out = _target(source, ".pdf", "converted", settings)
            return _run(["img2pdf", str(source), "-o", str(out)], out)
        out = _target(source, source.suffix, op, settings)
        transforms = {
            "compress": ["-strip", "-quality", iq],
            "resize": ["-resize", "50%"],
            "crop": ["-gravity", "center", "-extent", "%[fx:min(w,h)]x%[fx:min(w,h)]"],
            "rotate": ["-rotate", "90"],
            "strip": ["-strip"],
        }
        if op == "clipboard":
            subprocess.run(["wl-copy", "--type", _mime_from_content(source)], input=source.read_bytes(), check=True)
            return source
        return _run(["magick", str(source), "-auto-orient", *transforms[op], str(out)], out)

    if action.startswith("video_"):
        op = action.removeprefix("video_")
        if op == "mp4":
            out = _target(source, ".mp4", "converted", settings)
            return _run(_ffmpeg_base(source) + [*strip, "-c:v", "libx264", "-crf", video_crf, "-c:a", "aac", "-movflags", "+faststart", str(out)], out)
        if op == "webm":
            out = _target(source, ".webm", "converted", settings)
            return _run(_ffmpeg_base(source) + [*strip, "-c:v", "libvpx-vp9", "-crf", video_crf, "-b:v", "0", "-c:a", "libopus", str(out)], out)
        if op == "mov":
            out = _target(source, ".mov", "converted", settings)
            return _run(_ffmpeg_base(source) + [*strip, "-c:v", "libx264", "-crf", video_crf, "-c:a", "aac", str(out)], out)
        if op == "gif":
            out = _target(source, ".gif", "converted", settings)
            vf = "fps=12,scale='min(960,iw)':-2:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=192[p];[s1][p]paletteuse=dither=sierra2_4a"
            return _run(_ffmpeg_base(source) + ["-vf", vf, "-loop", "0", str(out)], out)
        if op == "audio":
            out = _target(source, ".mp3", "audio", settings)
            return _run(_ffmpeg_base(source) + ["-vn", "-c:a", "libmp3lame", "-b:a", bitrate, str(out)], out)
        suffix = source.suffix
        out = _target(source, suffix, op, settings)
        options = {
            "compress": [*strip, "-c:v", "libx264", "-crf", str(min(36, int(video_crf) + 5)), "-c:a", "aac", "-b:a", "128k"],
            "720p": [*strip, "-vf", "scale=-2:720", "-c:v", "libx264", "-crf", video_crf, "-c:a", "aac"],
            "trim": ["-t", "10", "-c", "copy"],
            "noaudio": [*strip, "-an", "-c:v", "copy"],
            "fps30": [*strip, "-vf", "fps=30", "-c:v", "libx264", "-crf", video_crf, "-c:a", "copy"],
            "strip": ["-map_metadata", "-1", "-c", "copy"],
        }
        return _run(_ffmpeg_base(source) + [*options[op], str(out)], out)

    if action.startswith("audio_"):
        op = action.removeprefix("audio_")
        specs = {
            "mp3": (".mp3", ["-c:a", "libmp3lame", "-b:a", bitrate]),
            "wav": (".wav", ["-c:a", "pcm_s16le"]),
            "flac": (".flac", ["-c:a", "flac"]),
            "ogg": (".ogg", ["-c:a", "libvorbis", "-q:a", "6"]),
            "m4a": (".m4a", ["-c:a", "aac", "-b:a", bitrate]),
        }
        if op in specs:
            suffix, spec = specs[op]
            out = _target(source, suffix, "converted", settings)
            return _run(_ffmpeg_base(source) + ["-vn", *strip, *spec, str(out)], out)
        if op == "metadata":
            out = _target(source, ".txt", "metadata", settings)
            result = subprocess.run(["ffprobe", "-v", "quiet", "-show_format", "-show_streams", str(source)], capture_output=True, text=True, check=True)
            out.write_text(result.stdout, encoding="utf-8")
            return out
        out = _target(source, source.suffix, op, settings)
        options = {
            "compress": ["-vn", *strip, "-c:a", "libmp3lame", "-b:a", "128k"],
            "trim": ["-t", "30", "-c", "copy"],
            "bitrate": ["-vn", *strip, "-c:a", "libmp3lame", "-b:a", bitrate],
            "strip": ["-map_metadata", "-1", "-c", "copy"],
        }
        return _run(_ffmpeg_base(source) + [*options[op], str(out)], out)

    if action.startswith("pdf_"):
        op = action.removeprefix("pdf_")
        if op == "compress":
            out = _target(source, ".pdf", "compressed", settings)
            return _run(["gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4", "-dPDFSETTINGS=/ebook", "-dNOPAUSE", "-dQUIET", "-dBATCH", f"-sOutputFile={out}", str(source)], out)
        if op in {"png_all", "split"}:
            directory = _target(source, "", "pages", settings)
            directory.mkdir(parents=True, exist_ok=settings["overwrite"])
            command = ["pdftoppm", "-png", "-r", "180", str(source), str(directory / "page")] if op == "png_all" else ["pdfseparate", str(source), str(directory / "page-%d.pdf")]
            subprocess.run(command, check=True, capture_output=True)
            return directory
        if op == "rotate":
            out = _target(source, ".pdf", "rotated", settings)
            return _run(["qpdf", str(source), "--rotate=+90:1-z", str(out)], out)

    if action == "text_clipboard":
        subprocess.run(["wl-copy"], input=source.read_bytes(), check=True)
        return source
    if action.startswith("text_"):
        target = action.removeprefix("text_")
        suffix = {"txt": ".txt", "md": ".md", "html": ".html"}[target]
        out = _target(source, suffix, "converted", settings)
        return _run(["pandoc", str(source), "-t", {"txt": "plain", "md": "gfm", "html": "html5"}[target], "-o", str(out)], out)
    raise ValueError(f"Unsupported action: {action}")


def build_universal_apk(
    source: Path,
    settings: dict | None = None,
    keystore: Path | None = None,
    alias: str = "",
    store_password: str = "",
    key_password: str = "",
) -> Path:
    settings = settings or load_settings()
    output = _target(source, ".apk", "signed" if keystore else "universal-test", settings)
    with tempfile.TemporaryDirectory(prefix="quickconvert-aab-") as temporary:
        temporary_path = Path(temporary)
        apks = temporary_path / "output.apks"
        command = [
            "java", "-jar", str(_bundletool_jar()), "build-apks",
            f"--bundle={source}", f"--output={apks}", "--mode=universal", "--overwrite",
        ]
        if keystore:
            if not keystore.is_file() or not alias or not store_password:
                raise ValueError("Keystore, key alias, and keystore password are required")
            store_secret = temporary_path / "store.password"
            store_secret.write_text(store_password, encoding="utf-8")
            os.chmod(store_secret, 0o600)
            command += [
                f"--ks={keystore}", f"--ks-pass=file:{store_secret}", f"--ks-key-alias={alias}",
            ]
            if key_password:
                key_secret = temporary_path / "key.password"
                key_secret.write_text(key_password, encoding="utf-8")
                os.chmod(key_secret, 0o600)
                command.append(f"--key-pass=file:{key_secret}")
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "bundletool failed")
        with zipfile.ZipFile(apks) as archive:
            try:
                with archive.open("universal.apk") as source_apk, output.open("wb") as destination:
                    shutil.copyfileobj(source_apk, destination)
            except KeyError as error:
                raise RuntimeError("bundletool did not create a universal APK") from error
    if shutil.which("apksigner"):
        verify = subprocess.run(["apksigner", "verify", "--verbose", str(output)], capture_output=True, text=True)
        if verify.returncode != 0:
            output.unlink(missing_ok=True)
            raise RuntimeError(verify.stderr.strip() or "APK signature verification failed")
    return output


def sign_aab(
    source: Path,
    keystore: Path,
    alias: str,
    store_password: str,
    key_password: str = "",
    settings: dict | None = None,
) -> Path:
    settings = settings or load_settings()
    if not keystore.is_file() or not alias or not store_password:
        raise ValueError("Keystore, key alias, and keystore password are required")
    output = _target(source, ".aab", "signed", settings)
    command = [
        "jarsigner", "-keystore", str(keystore), "-signedjar", str(output),
        str(source), alias,
    ]
    secrets = f"{store_password}\n{key_password or store_password}\n"
    result = subprocess.run(command, input=secrets, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not output.is_file():
        output.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "AAB signing failed")
    verify = subprocess.run(
        ["jarsigner", "-verify", "-certs", str(output)],
        capture_output=True, text=True, check=False,
    )
    if verify.returncode != 0 or "jar verified" not in verify.stdout.lower():
        output.unlink(missing_ok=True)
        raise RuntimeError(verify.stderr.strip() or verify.stdout.strip() or "AAB signature verification failed")
    return output


def _archive(action: str, sources: list[Path], settings: dict) -> Path:
    first = sources[0]
    if action == "archive_extract":
        output = _target(first, "", "extracted", settings)
        output.mkdir(parents=True, exist_ok=settings["overwrite"])
        subprocess.run(["7z", "x", str(first), f"-o{output}", "-y"], check=True, capture_output=True)
        return output
    suffix = {"archive_zip": ".zip", "archive_7z": ".7z", "archive_targz": ".tar.gz"}[action]
    output = _target(first, suffix, "archive", settings)
    with tempfile.TemporaryDirectory(prefix="quickconvert-") as temporary:
        staging = Path(temporary) / "contents"
        staging.mkdir()
        if len(sources) == 1 and detect(first).kind == "archive":
            subprocess.run(["7z", "x", str(first), f"-o{staging}", "-y"], check=True, capture_output=True)
        else:
            used: set[str] = set()
            for source in sources:
                name = source.name
                counter = 2
                while name in used:
                    name = f"{source.stem}-{counter}{source.suffix}"
                    counter += 1
                used.add(name)
                shutil.copy2(source, staging / name)
        entries = [path.name for path in staging.iterdir()]
        if action == "archive_targz":
            subprocess.run(["tar", "-czf", str(output), "--", *entries], cwd=staging, check=True, capture_output=True)
        else:
            archive_type = "zip" if action == "archive_zip" else "7z"
            subprocess.run(["7z", "a", f"-t{archive_type}", str(output), *entries], cwd=staging, check=True, capture_output=True)
    return output


def perform(action: str, paths: list[Path]) -> list[Path]:
    sources = [path.resolve() for path in paths]
    settings = load_settings()
    if action.startswith("archive_"):
        return [_archive(action, sources, settings)]
    if action == "images_pdf":
        output = _target(sources[0], ".pdf", "combined", settings)
        return [_run(["img2pdf", *[str(path) for path in sources], "-o", str(output)], output)]
    if action == "pdf_merge":
        output = _target(sources[0], ".pdf", "merged", settings)
        return [_run(["pdfunite", *[str(path) for path in sources], str(output)], output)]
    if action.startswith("batch_image_"):
        op = action.removeprefix("batch_image_")
        mapped = {"compress": "image_compress", "resize": "image_resize", "strip": "image_strip"}.get(op, f"image_{op}")
        return [_single_action(mapped, source, settings) for source in sources]
    if action == "batch_pdf_compress":
        return [_single_action("pdf_compress", source, settings) for source in sources]
    if action == "batch_pdf_extract":
        return [_single_action("pdf_png_all", source, settings) for source in sources]
    return [_single_action(action, sources[0], settings)]


def actions_json(paths: list[Path]) -> str:
    return json.dumps(actions_for_paths(paths), ensure_ascii=False)
