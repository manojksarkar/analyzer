"""Component diagram view (stub). Model -> output/component_diagram."""
from .registry import register


@register("componentDiagram")
def run(model, output_dir, model_dir, config):
    # Stub: other dev implements. Reads model["units"], model["modules"], callerUnits/calleesUnits.
    pass
