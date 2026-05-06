"""ADD view registry: name -> run(model, output_dir, model_dir, config)."""
ADD_VIEW_REGISTRY = {}


def register(name):
    def decorator(fn):
        ADD_VIEW_REGISTRY[name] = fn
        return fn
    return decorator
