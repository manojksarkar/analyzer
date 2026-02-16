"""Flowcharts view (stub). Model -> output/flowcharts/."""
from .registry import register


@register("flowcharts")
def run(model, output_dir, model_dir, config):
    # Stub: other dev implements. Reads model["functions"], uses function bodies/LLM.
    pass
