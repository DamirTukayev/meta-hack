"""Assemble the frames written by capture_demo.mjs into docs/demo.gif (and the result screenshot into docs/result.png).

Usage: uv run python scripts/make_gif.py [frames-dir]
Frames whose name ends in _hold stay on screen longer.
"""

import sys
from pathlib import Path

from PIL import Image

src = Path(sys.argv[1] if len(sys.argv) > 1 else "scratch/frames")
out = Path("docs")
out.mkdir(exist_ok=True)
WIDTH = 960
frames, durations = [], []
for f in sorted(src.glob("f*.jpg")):
    im = Image.open(f).convert("RGB")
    im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
    frames.append(im.quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    durations.append(1800 if f.stem.endswith("_hold") else 330)
frames[0].save(out / "demo.gif", save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True, disposal=1)
print(f"docs/demo.gif: {len(frames)} frames, {(out / 'demo.gif').stat().st_size / 1e6:.1f} MB")
res = src / "result.png"
if res.exists():
    Image.open(res).convert("RGB").save(out / "result.png", optimize=True)
    print(f"docs/result.png: {(out / 'result.png').stat().st_size / 1e3:.0f} KB")
