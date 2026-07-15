import datetime

from app.models.project import Project
from app.schemas.project import ProjectOutcomeUpdate
from app.services.projects import apply_outcome


def _project(**kwargs):
    defaults = dict(our_ref="Q-1", client_name="ACME", status="quotation_ready", quoted_value_myr=10000.0)
    defaults.update(kwargs)
    return Project(**defaults)


def test_won_without_explicit_value_defaults_to_quoted_value():
    project = _project()
    apply_outcome(project, ProjectOutcomeUpdate(outcome="won"))
    assert project.outcome == "won"
    assert project.outcome_value_myr == 10000.0
    assert isinstance(project.outcome_recorded_at, datetime.datetime)


def test_won_with_explicit_value_overrides_quoted_value():
    project = _project()
    apply_outcome(project, ProjectOutcomeUpdate(outcome="won", outcome_value_myr=9500.0))
    assert project.outcome_value_myr == 9500.0


def test_lost_records_notes_and_timestamp():
    project = _project()
    apply_outcome(project, ProjectOutcomeUpdate(outcome="lost", outcome_notes="Lost to competitor on price"))
    assert project.outcome == "lost"
    assert project.outcome_notes == "Lost to competitor on price"
    assert project.outcome_recorded_at is not None


def test_none_outcome_resets_all_fields():
    project = _project(outcome="won", outcome_value_myr=9500.0, outcome_notes="note",
                        outcome_recorded_at=datetime.datetime.utcnow())
    apply_outcome(project, ProjectOutcomeUpdate(outcome=None))
    assert project.outcome is None
    assert project.outcome_value_myr is None
    assert project.outcome_notes is None
    assert project.outcome_recorded_at is None
