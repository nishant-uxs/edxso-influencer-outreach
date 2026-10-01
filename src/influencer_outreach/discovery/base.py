"""Discovery provider interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod

from influencer_outreach.models import InfluencerProfile


class DiscoveryProvider(ABC):
    """Pluggable source for influencer candidates."""

    name: str = "base"

    @abstractmethod
    def discover(self, niche: str, limit: int) -> list[InfluencerProfile]:
        raise NotImplementedError
