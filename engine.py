"""Headless, offline vision inference. No ComfyUI server or queue is used."""
import gc
import os
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageOps


class VisionEngine:
    def __init__(self, runtime_directory):
        self.runtime_directory = Path(runtime_directory)
        self.clip = None
        self.model_key = None
        self.initialized = False

    def initialize(self):
        if self.initialized:
            return
        if not (self.runtime_directory / "comfy" / "sd.py").is_file():
            raise ValueError("Inference libraries were not found. Check runtime_directory in config.json.")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        sys.path.insert(0, str(self.runtime_directory))
        previous = sys.argv
        try:
            sys.argv = [previous[0]]
            import comfy.options
            comfy.options.enable_args_parsing()
            import torch
            import comfy.sd
            import comfy.model_management
            from comfy_extras.nodes_textgen import TextGenerateV2
            self.torch = torch
            self.sd = comfy.sd
            self.memory = comfy.model_management
            self.generate = TextGenerateV2
        finally:
            sys.argv = previous
        self.initialized = True

    def load(self, model_path):
        path = Path(model_path).resolve()
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if self.clip is not None and self.model_key == key:
            return
        self.initialize()
        self.unload()
        # The selected 9B checkpoint fits this GPU; the native fixed loader also
        # works without ComfyUI's server-startup DynamicVRAM initialization.
        with self.torch.inference_mode():
            self.clip = self.sd.load_clip(ckpt_paths=[str(path)], embedding_directory=[],
                                         clip_type=self.sd.CLIPType.STABLE_DIFFUSION,
                                         disable_dynamic=True)
        self.model_key = key

    def describe(self, image_path, prompt, system_prompt, max_tokens):
        if self.clip is None:
            raise RuntimeError("Load a vision model before describing an image.")
        with Image.open(image_path) as source:
            if getattr(source, "n_frames", 1) != 1:
                raise ValueError("Use a still image; animated or multi-page files are not supported.")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            image = Image.alpha_composite(background, image).convert("RGB")
            pixels = np.asarray(image, dtype=np.float32) / 255.0
        with self.torch.inference_mode():
            tensor = self.torch.from_numpy(pixels)[None]
            result = self.generate.execute(clip=self.clip, prompt=prompt,
                system_prompt=system_prompt, images={"image1": tensor},
                max_length=max_tokens, sampling_mode={"sampling_mode": "off"},
                thinking=False, use_default_template=True, mtp="off")
            text = result.args[0].strip()
        if not text:
            raise ValueError("The model returned no description. Try a shorter instruction or another vision checkpoint.")
        return text

    def unload(self):
        self.clip = None
        self.model_key = None
        if self.initialized:
            self.memory.unload_all_models()
            gc.collect()
            self.memory.soft_empty_cache()
