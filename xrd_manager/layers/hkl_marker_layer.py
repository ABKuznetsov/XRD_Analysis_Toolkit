from xrd_manager.layers.base import Layer


class HKLMarkerLayer(Layer):
    def __init__(self) -> None:
        super().__init__(name="HKL markers", color="#f9ab00")

