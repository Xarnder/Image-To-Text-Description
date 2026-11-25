# Image-To-Text-Description

**Caption Studio** — a local image-to-text batch application.

A local browser app for describing folders of images with a vision model. It runs its own server and model worker. No ComfyUI browser, ComfyUI server, API key, cloud inference, subscription, or upload is required.

## Start and use

1. Double-click **Launch Caption Studio.bat** or **Launch Caption Studio.cmd** in this folder. Both open the browser at **http://127.0.0.1:8790**. Launching either again opens the existing app.
2. Browse to an image folder. **Include subfolders** is enabled by default. **Scan folder** previews the images without generating captions.
3. Choose **Pose**, **Composition**, **Outfit**, or **Custom**. Edit the instructions once for the whole batch. The browser remembers your last settings.
4. Open **Model, output & advanced options** to choose a model path, output label, optional output folder, and text copies.
5. Click **Start batch**. Images are described one at a time, with the model loaded once and reused throughout the batch. Click any result to read and copy its description.

**Batches** in the header opens saved history. You can queue more batches, pause or cancel after the current image, resume unfinished work, retry failed images, and export JSON or CSV. Results save immediately after each image. Closing the browser tab does not stop the server. Use **Model & app → Stop app** when finished. If the app or computer restarts, unfinished batches are paused until you resume them.

The interface starts in **dark mode**, with a dark grey background. Use **Light mode** in the header to switch; your choice is remembered in that browser.

If the folder chooser cannot connect, the local server may be stopped. Double-click **Launch Caption Studio.cmd**, then click **Reconnect** in the existing tab. Reconnect refreshes the session after a server restart and preserves your saved settings. It does not automatically resubmit batch requests.

## Where descriptions are saved

By default the text is in separate files beside each original image, not inside its image metadata:

| Source image | Description type | Files written |
| --- | --- | --- |
| `photo.jpg` | Pose | `photo.jpg.pose.json` and `photo.jpg.pose.txt` |
| `photo.jpg` | Composition | `photo.jpg.composition.json` and `photo.jpg.composition.txt` |
| `photo.jpg` | Outfit | `photo.jpg.outfit.json` and `photo.jpg.outfit.txt` |
| `photo.jpg` | Custom | `photo.jpg.custom.json` and `photo.jpg.custom.txt` |

JSON includes the caption, source-image hash, model name, instructions, and cache metadata. Plain-text copies can be disabled. An optional output folder preserves the source folder structure beneath it. Originals are never modified. Each output label has one current description per image: choose a new label, such as `outfit-detail`, if you want to retain multiple versions of a prompt's output.

Matching descriptions are reused automatically. Changing the image, instructions, model file, or token limit regenerates them. **Regenerate matching descriptions** forces a fresh run. A run's captions also remain in its history and exports when a later run replaces a sidecar.

## Using captions with the fashion workflow

Choose the unedited **Pose** preset, keep output label `pose`, and leave **Output folder** empty. This creates the `.pose.json` sidecars that your existing fashion pose loader reads beside each pose image. Point that workflow's pose directory at the same image folder. Existing compatible pose descriptions are reused.

For example, the existing description for `page 061 image 003.png` is in:

`D:\Chrome Downloads\Good Fashion Poses\Good Fashion Poses\page 061 image 003.png.pose.json`

Editing the standard pose instructions or token limit automatically changes its output label to `pose-custom`. This preserves the standard fashion-workflow description. Composition, outfit, and custom descriptions have separate labels.

## Model and performance

The configured model is the already-installed **Qwen3.5-9B W4A8 GPTQ** vision checkpoint. This app reuses your portable Python and Comfy inference libraries directly; it does not call the ComfyUI HTTP server, workflow engine, or web interface. There are no downloads during inference. The app is free to run locally, apart from your computer's electricity use.

Paths are in `config.json`. Keep the referenced Python runtime, inference-library folder, and model file in place. If you move the Python runtime, update both `config.json` and `Launch Caption Studio.cmd`. Other checkpoints must be vision-capable `.safetensors` models supported by the installed native text-generation implementation; arbitrary GGUF, Ollama, or Hugging Face model folders are not supported by this version.

A first model load can take a few minutes. Once loaded, it stays in memory for all images in the batch. It normally releases GPU memory at the end; enable **Keep the model loaded between batches** for repeated work. Finish other large GPU jobs before starting inference. **Model & app → Release GPU memory** unloads an idle model.

The queue keeps metadata in SQLite and loads only one source image at a time. The browser displays 24 thumbnails per page. Supported still-image formats: PNG, JPEG, WebP, BMP, TIFF. Corrupt, animated, and multi-page inputs are reported individually, while the batch continues. Model-generated descriptions can contain mistakes; review sample outputs before processing a large new collection.

## Project files

- `app.py`: local FastAPI server, folder browser, previews and exports.
- `engine.py`: offline vision model adapter.
- `jobs.py`, `storage.py`: persistent queue, caching, atomic sidecar writes.
- `presets.json`: built-in instructions; `dist/`: browser interface, with no build step or remote assets.
- `data/batches.sqlite3`: batch history and progress; `data/server.log`: server and inference logs.
- `tests/test_app.py`: backend and queue regression tests using a mock model; real-model verification is recorded separately.

To run the regression checks from this folder:

```powershell
& 'D:\New_ComfyUI\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\python_embeded\python.exe' -s tests/test_app.py
```

The server listens only on this computer at `127.0.0.1`. Nothing is published or sent to an external service.
