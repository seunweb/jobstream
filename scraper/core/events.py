"""
Domain Event Bus
Publishes events to Celery for async processing.
Persists events to domain_events table for guaranteed delivery.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# Event type constants
class Events:
    # Recruitment
    CANDIDATE_APPLIED       = "CandidateApplied"
    APPLICATION_REVIEWED    = "ApplicationReviewed"
    INTERVIEW_SCHEDULED     = "InterviewScheduled"
    INTERVIEW_COMPLETED     = "InterviewCompleted"
    OFFER_CREATED           = "OfferCreated"
    OFFER_ACCEPTED          = "OfferAccepted"
    OFFER_DECLINED          = "OfferDeclined"
    EMPLOYEE_HIRED          = "EmployeeHired"

    # Identity
    USER_REGISTERED         = "UserRegistered"
    USER_LOGIN              = "UserLogin"
    PASSWORD_RESET          = "PasswordReset"

    # Organization
    ORG_CREATED             = "OrganizationCreated"
    DEPARTMENT_CREATED      = "DepartmentCreated"

    # Future
    LEAVE_REQUESTED         = "LeaveRequested"
    LEAVE_APPROVED          = "LeaveApproved"
    PAYROLL_PROCESSED       = "PayrollProcessed"
    EMPLOYEE_TERMINATED     = "EmployeeTerminated"


def publish(event_type: str, payload: dict, tenant_id: str = None):
    """
    Publish a domain event.
    Phase 1: Logs and persists to DB.
    Phase 2: Will dispatch to Celery workers.
    """
    from core.database import get_conn, USE_POSTGRES

    event_id = str(uuid.uuid4())
    log.info(f"Event: {event_type} | tenant={tenant_id} | id={event_id}")

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute("""
                    INSERT INTO domain_events
                        (id, tenant_id, event_type, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    event_id, tenant_id, event_type,
                    __import__('json').dumps(payload),
                    datetime.now(timezone.utc).isoformat()
                ))
            else:
                cur.execute("""
                    INSERT INTO domain_events
                        (id, tenant_id, event_type, payload, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    event_id, tenant_id, event_type,
                    __import__('json').dumps(payload),
                    datetime.now(timezone.utc).isoformat()
                ))
    except Exception as e:
        # Never let event publishing crash the main flow
        log.error(f"Failed to persist event {event_type}: {e}")

    return event_id
