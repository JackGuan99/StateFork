import random
from abc import ABC, abstractmethod


class Decider(ABC):
    """
    Strategy interface that decides whether to take
    a physical snapshot or create a virtual one.
    """

    @abstractmethod
    def decide(self) -> bool:
        """
        Return True  -> take physical snapshot
        Return False -> create virtual snapshot
        """
        pass


class RandomDecider(Decider):
    """
    Simple implementation: randomly returns True or False.
    """

    def decide(self) -> bool:
        return random.choice([True, False])
