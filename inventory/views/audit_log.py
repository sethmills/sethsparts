"""A read-only view of the audit trail — the answer to "where did it go?"."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from ..models import AuditEvent


@login_required
def audit_log(request):
    events = AuditEvent.objects.select_related("part", "actor")[:200]
    return render(request, "inventory/audit_log.html", {"events": events})
