from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from apps.commerce.accounting_report import build_accounting_report


class Command(BaseCommand):
    help = "Report aggregate local commerce consistency without provider calls or writes."
    requires_system_checks: list[str] = []

    def handle(self, *args: Any, **options: Any) -> None:
        del args, options
        try:
            report = build_accounting_report()
        except DatabaseError:
            raise CommandError("Local commerce report query failed.") from None
        self.stdout.write(json.dumps(report, sort_keys=True))
        if report["local_integrity"] == "inconsistent":
            raise CommandError("Local commerce integrity discrepancies detected.")
