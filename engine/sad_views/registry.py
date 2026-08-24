"""SAD view registry: name -> run(model, output_dir, model_dir, config)."""
SAD_VIEW_REGISTRY = {}


def register(name):
    def decorator(fn):
        SAD_VIEW_REGISTRY[name] = fn
        return fn
    return decorator
