"""Create an owned, simple sample mesh; no third-party assets."""

from pathlib import Path
import trimesh

target = Path(__file__).resolve().parents[1] / "samples"
target.mkdir(exist_ok=True)
trimesh.creation.box(extents=[30, 20, 10]).export(target / "demo-block.stl")
print(target / "demo-block.stl")
