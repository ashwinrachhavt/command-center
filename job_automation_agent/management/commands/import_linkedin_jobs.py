import csv
from django.core.management.base import BaseCommand
from job_automation_agent.models import Job
from django.utils.dateparse import parse_datetime

class Command(BaseCommand):
    help = "Import jobs from LinkedIn scraper CSV"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str)

    def handle(self, *args, **opts):
        path = opts["csv_path"]
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                obj, created = Job.objects.update_or_create(
                    id=row.get("id"),
                    defaults={
                        "title": row.get("title"),
                        "company_name": row.get("companyName"),
                        "company_url": row.get("companyUrl") or None,
                        "location": row.get("location"),
                        "contract_type": row.get("contractType"),
                        "experience_level": row.get("experienceLevel"),
                        "work_type": row.get("workType"),
                        "applications_count": row.get("applicationsCount"),
                        "posted_time": row.get("postedTime"),
                        "published_at": parse_datetime(row.get("publishedAt")) if row.get("publishedAt") else None,
                        "salary": row.get("salary"),
                        "description": row.get("description"),
                        "job_url": row.get("jobUrl"),
                        "apply_type": row.get("applyType"),
                    },
                )
                self.stdout.write(f"{'Created' if created else 'Updated'} {obj}")
