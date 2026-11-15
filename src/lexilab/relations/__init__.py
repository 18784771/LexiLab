"""Local vocabulary relation engine (WordNet + RapidFuzz + user confusion)."""

from lexilab.relations.model import RelationRecord, RelationView
from lexilab.relations.service import RelationService

__all__ = ["RelationRecord", "RelationService", "RelationView"]
