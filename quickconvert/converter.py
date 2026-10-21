from __future__ import annotations

import mimetypes
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Action:
    id: str
    title: str
    subtitle: str
    icon: str


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".avif"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".oga", ".flac", ".m4a", ".aac", ".opus"}


def media_kind(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    mime, _ = mimetypes.guess_type(path.name)
    if mime:
        return mime.split("/", 1)[0] if mime.split("/", 1)[0] in {"image", "video", "audio"} else None
    return None


def actions_for(path: Path) -> list[Action]:
    kind = media_kind(path)
    ext = path.suffix.lower()
    actions: list[Action] = []
    if kind == "image":
        for target, label in (("png", "PNG"), ("jpg", "JPG"), ("webp", "WebP")):
            if ext not in ({".jpg", ".jpeg"} if target == "jpg" else {f".{target}"}):
                actions.append(Action(f"image_{target}", f"حوّل إلى {label}", "صورة عالية الجودة", "image-x-generic-symbolic"))
        actions.append(Action("image_pdf", "حوّل إلى PDF", "صفحة مضبوطة على حجم الصورة", "application-pdf-symbolic"))
    elif kind == "video":
        if ext != ".mp4":
            actions.append(Action("video_mp4", "حوّل إلى MP4", "H.264 متوافق مع معظم الأجهزة", "video-x-generic-symbolic"))
        if ext != ".webm":
            actions.append(Action("video_webm", "حوّل إلى WebM", "VP9 عالي الكفاءة للويب", "video-x-generic-symbolic"))
        actions.append(Action("video_gif", "حوّل إلى GIF", "مقطع متحرك محسّن للمشاركة", "image-x-generic-symbolic"))
        actions.append(Action("video_audio", "استخرج الصوت MP3", "مسار صوتي بجودة 192 kbps", "audio-x-generic-symbolic"))
    elif kind == "audio":
        for target, label, hint in (("mp3", "MP3", "192 kbps للاستخدام اليومي"), ("wav", "WAV", "صوت غير مضغوط"), ("ogg", "OGG", "Vorbis عالي الجودة")):
            if ext != f".{target}":
                actions.append(Action(f"audio_{target}", f"حوّل إلى {label}", hint, "audio-x-generic-symbolic"))
    elif kind == "pdf":
        actions.extend([
            Action("pdf_png_first", "الصفحة الأولى إلى PNG", "صورة بدقة 180 DPI", "image-x-generic-symbolic"),
            Action("pdf_png_all", "كل الصفحات إلى PNG", "مجلد صور بدقة 180 DPI", "folder-pictures-symbolic"),
            Action("pdf_compress", "ضغط ملف PDF", "حجم أصغر للمشاركة", "document-save-symbolic"),
        ])
    return actions


def _safe_stem(path: Path) -> str:
    stem = re.sub(r"[\x00-\x1f/\\]", "_", path.stem).strip(" .")
    return stem or "converted"


def unique_output(path: Path, suffix: str, tag: str = "converted") -> Path:
    base = path.parent / f"{_safe_stem(path)}-{tag}{suffix}"
    if not base.exists():
        return base
    for number in range(2, 10_000):
        candidate = path.parent / f"{_safe_stem(path)}-{tag}-{number}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("تعذر اختيار اسم جديد للملف الناتج")


def command_for(action_id: str, source: Path) -> tuple[list[str], Path]:
    source = source.resolve()
    commands: dict[str, tuple[list[str], Path]] = {}

    def image(target: str) -> tuple[list[str], Path]:
        out = unique_output(source, f".{target}")
        cmd = ["magick", str(source), "-auto-orient", "-strip"]
        if target == "jpg":
            cmd += ["-background", "white", "-alpha", "remove", "-quality", "92"]
        elif target == "webp":
            cmd += ["-quality", "88"]
        cmd.append(str(out))
        return cmd, out

    for target in ("png", "jpg", "webp"):
        commands[f"image_{target}"] = image(target)

    pdf_out = unique_output(source, ".pdf")
    commands["image_pdf"] = (["img2pdf", str(source), "-o", str(pdf_out)], pdf_out)

    mp4_out = unique_output(source, ".mp4")
    commands["video_mp4"] = (["ffmpeg", "-hide_banner", "-y", "-i", str(source), "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(mp4_out)], mp4_out)
    webm_out = unique_output(source, ".webm")
    commands["video_webm"] = (["ffmpeg", "-hide_banner", "-y", "-i", str(source), "-c:v", "libvpx-vp9", "-crf", "31", "-b:v", "0", "-c:a", "libopus", "-b:a", "128k", str(webm_out)], webm_out)
    gif_out = unique_output(source, ".gif")
    commands["video_gif"] = (["ffmpeg", "-hide_banner", "-y", "-i", str(source), "-vf", "fps=12,scale='min(960,iw)':-2:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=192[p];[s1][p]paletteuse=dither=sierra2_4a", "-loop", "0", str(gif_out)], gif_out)
    audio_out = unique_output(source, ".mp3", "audio")
    commands["video_audio"] = (["ffmpeg", "-hide_banner", "-y", "-i", str(source), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(audio_out)], audio_out)

    audio_specs = {
        "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
        "wav": ["-c:a", "pcm_s16le"],
        "ogg": ["-c:a", "libvorbis", "-q:a", "6"],
    }
    for target, spec in audio_specs.items():
        out = unique_output(source, f".{target}")
        commands[f"audio_{target}"] = (["ffmpeg", "-hide_banner", "-y", "-i", str(source), "-vn", *spec, str(out)], out)

    first_out = unique_output(source, ".png", "page-1")
    first_prefix = first_out.with_suffix("")
    commands["pdf_png_first"] = (["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "180", str(source), str(first_prefix)], first_out)

    pages_dir = unique_output(source, "", "pages")
    commands["pdf_png_all"] = (["__pdf_all__", str(source), str(pages_dir)], pages_dir)

    compressed_out = unique_output(source, ".pdf", "compressed")
    commands["pdf_compress"] = (["gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4", "-dPDFSETTINGS=/ebook", "-dNOPAUSE", "-dQUIET", "-dBATCH", f"-sOutputFile={compressed_out}", str(source)], compressed_out)

    if action_id not in commands:
        raise ValueError(f"Unsupported action: {action_id}")
    return commands[action_id]


def run_conversion(command: list[str], output: Path, on_process: Callable[[subprocess.Popen], None] | None = None) -> None:
    if command[0] == "__pdf_all__":
        source, directory = Path(command[1]), Path(command[2])
        directory.mkdir(parents=False, exist_ok=False)
        real_command = ["pdftoppm", "-png", "-r", "180", str(source), str(directory / "page")]
    else:
        real_command = command
    process = subprocess.Popen(real_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if on_process:
        on_process(process)
    _, stderr = process.communicate()
    if process.returncode != 0:
        if output.is_dir():
            shutil.rmtree(output, ignore_errors=True)
        elif output.exists():
            output.unlink(missing_ok=True)
        message = stderr.strip().splitlines()[-1] if stderr.strip() else "فشل برنامج التحويل"
        raise RuntimeError(message)
    if not output.exists():
        raise RuntimeError("انتهت العملية لكن لم يتم إنشاء ملف ناتج")


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
