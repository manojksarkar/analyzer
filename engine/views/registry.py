"""View registry: name -> run(model, output_dir, model_dir, config)."""
VIEW_REGISTRY = {}


def register(name):
    def decorator(fn):
        VIEW_REGISTRY[name] = fn
        return fn
    return decorator
