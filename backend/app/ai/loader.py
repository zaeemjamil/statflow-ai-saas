"""Bridge from a stored ``Analysis`` row to an evidence packet.

Kept separate so ``evidence.py`` stays free of database and service imports.
Reads only what is already on the row (and its already-persisted statistics
and charts); it writes nothing and never opens the uploaded file.
"""

from __future__ import annotations

from app.ai.evidence import EvidenceBuild, EvidencePacket, build_evidence, build_evidence_packet
from app.models import Analysis
from app.services import project_analysis_service


def evidence_packet_for_analysis(analysis: Analysis) -> EvidencePacket:
    """Provider-facing packet only. Same public view the dashboard uses ->
    same numbers the user sees. Carries no alias mapping."""
    return build_evidence_packet(project_analysis_service.to_public(analysis))


def evidence_build_for_analysis(analysis: Analysis) -> EvidenceBuild:
    """Packet plus the LOCAL alias mapping, for application logic only."""
    return build_evidence(project_analysis_service.to_public(analysis))
