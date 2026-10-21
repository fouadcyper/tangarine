import base64
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from quickconvert.settings import DEFAULTS
from quickconvert.smart import actions_for_paths, detect, perform


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class SmartActionTests(unittest.TestCase):
    def settings(self):
        return patch("quickconvert.smart.load_settings", return_value=DEFAULTS.copy())

    def test_detects_content_instead_of_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "misleading.bin"
            source.write_bytes(PNG_1X1)
            item = detect(source)
            self.assertEqual(item.kind, "image")
            self.assertEqual(item.format, "png")

    def test_current_real_format_is_not_offered(self):
        with tempfile.TemporaryDirectory() as directory, self.settings():
            source = Path(directory) / "looks-like-jpeg.jpg"
            source.write_bytes(PNG_1X1)
            data = actions_for_paths([source])
            ids = {item["id"] for item in data["primary"] + data["more"]}
            self.assertNotIn("image_png", ids)
            self.assertIn("image_jpg", ids)

    def test_multi_image_selection_gets_batch_actions(self):
        with tempfile.TemporaryDirectory() as directory, self.settings():
            sources = []
            for number in range(2):
                source = Path(directory) / f"image-{number}.data"
                source.write_bytes(PNG_1X1)
                sources.append(source)
            data = actions_for_paths(sources)
            ids = {item["id"] for item in data["primary"]}
            self.assertEqual(data["count"], 2)
            self.assertIn("batch_image_webp", ids)
            self.assertIn("images_pdf", ids)

    def test_mixed_selection_gets_archive_actions(self):
        with tempfile.TemporaryDirectory() as directory, self.settings():
            image = Path(directory) / "image.bin"
            text = Path(directory) / "notes.txt"
            image.write_bytes(PNG_1X1)
            text.write_text("hello", encoding="utf-8")
            data = actions_for_paths([image, text])
            self.assertEqual(data["kind"], "mixed")
            self.assertIn("archive_zip", {item["id"] for item in data["primary"]})

    def test_archive_creation_works_for_files_from_different_folders(self):
        with tempfile.TemporaryDirectory() as directory, self.settings():
            root = Path(directory)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            first = left / "first.txt"
            second = right / "second.txt"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            output = perform("archive_targz", [first, second])[0]
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 0)

    def test_aab_is_detected_from_zip_structure(self):
        with tempfile.TemporaryDirectory() as directory, self.settings():
            source = Path(directory) / "bundle-without-extension.bin"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("BundleConfig.pb", b"config")
                archive.writestr("base/manifest/AndroidManifest.xml", b"manifest")
            self.assertEqual(detect(source).kind, "aab")
            data = actions_for_paths([source])
            ids = {item["id"] for item in data["primary"]}
            self.assertIn("aab_universal", ids)
            self.assertIn("aab_sign_apk", ids)


if __name__ == "__main__":
    unittest.main()
