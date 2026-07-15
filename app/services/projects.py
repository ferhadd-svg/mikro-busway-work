"""
Win/loss outcome mutation for a Project. Kept as a pure function (no DB
access) so it's testable without a session, mirroring the
app.services.customers module's separation of mutation logic from routers.
"""

import datetime

from app.models.project import Project
from app.schemas.project import ProjectOutcomeUpdate


def apply_outcome(project: Project, data: ProjectOutcomeUpdate) -> None:
    if data.outcome is None:
        project.outcome = None
        project.outcome_value_myr = None
        project.outcome_notes = None
        project.outcome_recorded_at = None
        return

    project.outcome = data.outcome
    project.outcome_value_myr = (
        data.outcome_value_myr if data.outcome_value_myr is not None else project.quoted_value_myr
    )
    project.outcome_notes = data.outcome_notes
    project.outcome_recorded_at = datetime.datetime.utcnow()
