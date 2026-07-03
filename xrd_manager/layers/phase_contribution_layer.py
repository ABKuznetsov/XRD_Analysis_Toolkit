from xrd_manager.layers.base import Layer


class PhaseContributionLayer(Layer):
    def __init__(self, phase_name: str = "Phase contribution") -> None:
        super().__init__(name=phase_name, color="#8e24aa")

