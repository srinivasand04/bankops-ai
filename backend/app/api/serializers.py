"""Build response schemas that include computed fields (live SLA, overdue flags, correlation timing)."""

from app.models import Incident, IncidentAction, IncidentRca, IncidentRelatedChange
from app.models.enums import ActionStatus, ActionType, RcaStatus, RootCauseStatus
from app.schemas.application import ApplicationRef, ChangeRecordOut
from app.schemas.incident import IncidentDetailOut, IncidentOut, SlaClockOut, SlaOut
from app.schemas.rca import ActionOut, RcaOut, RelatedChangeOut, RootCauseOut
from app.services import lifecycle, sla_service
from app.utils.time import minutes_between, utcnow


def sla_out(incident: Incident) -> SlaOut | None:
    if incident.sla is None:
        return None
    evaluation = sla_service.evaluate(incident, incident.sla, utcnow())
    return SlaOut(
        severity=evaluation.severity,
        clock_started_at=incident.sla.clock_started_at,
        response=SlaClockOut(**vars(evaluation.response)),
        resolution=SlaClockOut(**vars(evaluation.resolution)),
        is_breached=evaluation.is_breached,
        escalation_status=evaluation.escalation_status,
    )


def _incident_fields(incident: Incident) -> dict:
    data = {field: getattr(incident, field) for field in IncidentOut.model_fields if hasattr(incident, field)}
    data["application"] = ApplicationRef.model_validate(incident.application)
    data["application_name"] = incident.application.name
    data["sla"] = sla_out(incident)
    return data


def incident_out(incident: Incident) -> IncidentOut:
    return IncidentOut(**_incident_fields(incident))


def incident_detail_out(incident: Incident, root_cause_count: int, open_action_count: int) -> IncidentDetailOut:
    return IncidentDetailOut(
        **_incident_fields(incident),
        allowed_transitions=lifecycle.allowed_transitions(incident.status),
        root_cause_count=root_cause_count,
        open_action_count=open_action_count,
    )


def action_out(action: IncidentAction) -> ActionOut:
    is_overdue = (
        action.due_date is not None
        and action.status in (ActionStatus.OPEN, ActionStatus.IN_PROGRESS)
        and action.due_date < utcnow().date()
    )
    return ActionOut.model_validate({**_columns(action), "is_overdue": is_overdue})


def related_change_out(link: IncidentRelatedChange) -> RelatedChangeOut:
    deployed = link.change.deployed_at
    gap = round(minutes_between(deployed, link.incident.started_at), 1) if deployed else None
    return RelatedChangeOut.model_validate(
        {
            **_columns(link),
            "change": ChangeRecordOut.model_validate(link.change),
            "minutes_from_deployment_to_incident": gap,
        }
    )


def rca_out(incident: Incident, rca: IncidentRca | None) -> RcaOut:
    causes = [RootCauseOut.model_validate(rc) for rc in incident.root_causes]
    actions = [action_out(a) for a in incident.actions]
    return RcaOut(
        incident_id=incident.id,
        incident_reference=incident.reference_number,
        incident_summary=f"{incident.title} - {incident.description}",
        status=rca.status if rca else RcaStatus.DRAFT,
        summary=rca.summary if rca else None,
        confirmed_facts=rca.confirmed_facts if rca else [],
        contributing_factors=rca.contributing_factors if rca else [],
        missing_evidence=rca.missing_evidence if rca else [],
        business_impact=(rca.business_impact if rca and rca.business_impact else incident.business_impact),
        confirmed_root_causes=[c for c in causes if c.status == RootCauseStatus.CONFIRMED],
        hypotheses=[c for c in causes if c.status in (RootCauseStatus.HYPOTHESIS, RootCauseStatus.UNDER_REVIEW)],
        rejected_root_causes=[c for c in causes if c.status == RootCauseStatus.REJECTED],
        corrective_actions=[a for a in actions if a.action_type == ActionType.CORRECTIVE],
        preventive_actions=[a for a in actions if a.action_type == ActionType.PREVENTIVE],
        related_changes=[related_change_out(link) for link in incident.related_changes],
        updated_by=rca.updated_by if rca else None,
        approved_by=rca.approved_by if rca else None,
        approved_at=rca.approved_at if rca else None,
    )


def _columns(obj) -> dict:
    return {column.key: getattr(obj, column.key) for column in obj.__table__.columns}
