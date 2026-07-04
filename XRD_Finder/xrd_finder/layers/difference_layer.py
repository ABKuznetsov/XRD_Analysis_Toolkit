from xrd_finder.layers.base import Layer


class DifferenceLayer(Layer):
    def __init__(self) -> None:
        super().__init__(name="Difference", color="#188038")
