from xrd_finder.layers.base import Layer


class CalculatedLayer(Layer):
    def __init__(self) -> None:
        super().__init__(name="Calculated", color="#d93025")
