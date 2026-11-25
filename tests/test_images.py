"""Exercise actual image decoding, including MPO containers with JPEG filenames."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from engine import load_image_pixels
from storage import scan_folder


class ImageLoadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="caption-image-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def assert_source_unchanged(self, path):
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        pixels = load_image_pixels(path)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertEqual(pixels.dtype, np.float32)
        self.assertTrue(np.isfinite(pixels).all())
        self.assertGreaterEqual(pixels.min(), 0)
        self.assertLessEqual(pixels.max(), 1)
        return pixels

    def test_jpg_jpeg_and_uppercase_extensions(self):
        for index, extension in enumerate([".jpg", ".jpeg", ".JPG", ".JPEG"]):
            with self.subTest(extension=extension):
                path = self.root / (f"photo-{index}" + extension)
                Image.new("RGB", (30, 20), (220, 50, 30)).save(path, format="JPEG")
                pixels = self.assert_source_unchanged(path)
                self.assertEqual(pixels.shape, (20, 30, 3))
                np.testing.assert_allclose(pixels[10, 15], np.array([220, 50, 30]) / 255, atol=.02)
        self.assertEqual(len(scan_folder(self.root)[1]), 4)

    def test_progressive_and_cmyk_jpeg(self):
        for mode, options in [("RGB", {"progressive": True}), ("CMYK", {})]:
            with self.subTest(mode=mode):
                path = self.root / (mode + ".jpeg")
                Image.new("RGB", (30, 20), "red").convert(mode).save(path, format="JPEG", **options)
                pixels = self.assert_source_unchanged(path)
                self.assertEqual(pixels.shape, (20, 30, 3))
                self.assertGreater(pixels[10, 15, 0], .95)

    def test_mpo_jpeg_uses_primary_photo_not_auxiliary_picture(self):
        for extension in [".jpg", ".jpeg"]:
            with self.subTest(extension=extension):
                path = self.root / ("multi-picture" + extension)
                primary = Image.new("RGB", (40, 20), "red")
                auxiliary = Image.new("RGB", (12, 8), "blue")
                primary.save(path, format="MPO", save_all=True, append_images=[auxiliary])
                with Image.open(path) as source:
                    self.assertEqual(source.format, "MPO")
                    self.assertEqual(source.n_frames, 2)
                    self.assertTrue(source.is_animated)  # Previously rejected here.
                pixels = self.assert_source_unchanged(path)
                self.assertEqual(pixels.shape, (20, 40, 3))
                np.testing.assert_allclose(pixels[10, 20], [1, 0, 0], atol=.02)

    def test_mpo_burst_uses_one_primary_photo(self):
        path = self.root / "burst.jpeg"
        Image.new("RGB", (30, 20), "red").save(path, format="MPO", save_all=True,
            append_images=[Image.new("RGB", (30, 20), "blue") for _ in range(7)])
        with Image.open(path) as source:
            self.assertEqual(source.n_frames, 8)
        pixels = self.assert_source_unchanged(path)
        np.testing.assert_allclose(pixels[10, 15], [1, 0, 0], atol=.02)

    def test_exif_orientation_on_jpeg_and_mpo_primary(self):
        for format in ["JPEG", "MPO"]:
            with self.subTest(format=format):
                path = self.root / (format + "-rotated.jpeg")
                source = Image.new("RGB", (40, 20), "red")
                source.paste("blue", (0, 0, 20, 20))
                exif = Image.Exif()
                exif[274] = 6
                options = {"save_all": True, "append_images": [Image.new("RGB", (10, 10), "green")]} if format == "MPO" else {}
                source.save(path, format=format, exif=exif, **options)
                pixels = self.assert_source_unchanged(path)
                self.assertEqual(pixels.shape, (40, 20, 3))
                self.assertGreater(pixels[5, 10, 2], .9)
                self.assertGreater(pixels[35, 10, 0], .9)

    def test_still_png_transparency_composites_on_white(self):
        path = self.root / "transparent.png"
        Image.new("RGBA", (30, 20), (0, 0, 0, 0)).save(path)
        np.testing.assert_array_equal(self.assert_source_unchanged(path), np.ones((20, 30, 3)))

    def test_actual_animation_or_multipage_is_still_rejected(self):
        for format in ["GIF", "WEBP", "TIFF"]:
            with self.subTest(format=format):
                # A misleading JPEG extension must not bypass content detection.
                path = self.root / (format + ".jpeg")
                Image.new("RGB", (30, 20), "red").save(path, format=format, save_all=True,
                    append_images=[Image.new("RGB", (30, 20), "blue")])
                with self.assertRaisesRegex(ValueError, "animated or multi-page"):
                    load_image_pixels(path)

    def test_corrupt_jpeg_reports_decoding_error(self):
        path = self.root / "broken.jpeg"
        path.write_bytes(b"this is not an image")
        with self.assertRaises(OSError):
            load_image_pixels(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
