"""Sequence diagrams view (stub). Model -> output/sequence_diagrams/."""
from .registry import register


@register("sequenceDiagrams")
def run(model, output_dir, model_dir, config):
    # Stub: other dev implements. Reads model["functions"], uses calledByIds/callsIds.
    pass
