from xrd_manager.layers.base import Layer


class ObservedLayer(Layer):
    def __init__(self) -> None:
        super().__init__(name="Observed", color="#202124")

