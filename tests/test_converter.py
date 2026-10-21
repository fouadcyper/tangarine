import tempfile
import unittest
from pathlib import Path

from quickconvert.converter import actions_for, command_for, media_kind, unique_output


class ConverterTests(unittest.TestCase):
    def test_detects_supported_types(self):
        self.assertEqual(media_kind(Path("photo.PNG")), "image")
        self.assertEqual(media_kind(Path("clip.mkv")), "video")
        self.assertEqual(media_kind(Path("song.flac")), "audio")
        self.assertEqual(media_kind(Path("paper.pdf")), "pdf")
        self.assertIsNone(media_kind(Path("notes.txt")))

    def test_actions_do_not_offer_same_format(self):
        ids = {action.id for action in actions_for(Path("photo.jpg"))}
        self.assertNotIn("image_jpg", ids)
        self.assertIn("image_png", ids)
        self.assertIn("image_pdf", ids)

    def test_unique_output_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "photo.png"
            source.touch()
            first = unique_output(source, ".jpg")
            first.touch()
            self.assertNotEqual(first, unique_output(source, ".jpg"))

    def test_command_uses_argument_list(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "odd name; safe.png"
            source.touch()
            command, output = command_for("image_webp", source)
            self.assertEqual(command[0], "magick")
            self.assertIn(str(source.resolve()), command)
            self.assertEqual(command[-1], str(output))

    def test_video_includes_gif_action(self):
        ids = {action.id for action in actions_for(Path("clip.mov"))}
        self.assertIn("video_gif", ids)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.mov"
            source.touch()
            command, output = command_for("video_gif", source)
            self.assertEqual(command[0], "ffmpeg")
            self.assertEqual(output.suffix, ".gif")


if __name__ == "__main__":
    unittest.main()
