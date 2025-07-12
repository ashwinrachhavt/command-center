from django.utils.html import format_html
from django.urls import reverse_lazy
from django.contrib import admin
from django.db import models
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import (
    FieldTextFilter,
    ChoicesDropdownFilter,
    RangeDateFilter,
)
from unfold.contrib.forms.widgets import WysiwygWidget
from unfold.decorators import action
from unfold.sections import TemplateSection
from .models import Job

class JobDescriptionSection(TemplateSection):
    verbose_name = _("Description")
    template_name = "job_automation_agent/job_description_section.html"

@admin.register(Job)
class JobAdmin(ModelAdmin):
    # — CHANGE LIST
    list_display = [
        "title",
        "company_name",
        "location",
        "contract_type",
        "experience_level",
        "applications_count",
        "published_at",
    ]
    list_display_links = ("title",)
    list_per_page = 25
    from unfold.paginator import InfinitePaginator
    paginator = InfinitePaginator
    show_full_result_count = False
    list_sections = [JobDescriptionSection]

    # — SEARCH & FILTERS
    search_fields = ("title__icontains", "company_name__icontains", "location__icontains")
    list_filter_submit = True
    list_filter = [
        ("title", FieldTextFilter),
        ("company_name", FieldTextFilter),
        ("contract_type", ChoicesDropdownFilter),
        ("experience_level", ChoicesDropdownFilter),
        ("work_type", ChoicesDropdownFilter),
        ("published_at", RangeDateFilter),
    ]

    # — READONLY & FORM
    readonly_fields = ("job_url_link",)
    formfield_overrides = {
        models.TextField: {"widget": WysiwygWidget},  # if you want rich text
    }

    # show the URL as a clickable link
    def job_url_link(self, obj):
        return format_html("<a href='{}' target='_blank'>Apply</a>", obj.job_url)
    job_url_link.short_description = "Apply Link"

    # — ACTIONS
    actions_list = ["refresh_from_source"]
    @action(description="Re-import selected jobs", icon="refresh")
    def refresh_from_source(self, request, queryset):
        for job in queryset:
            # place your re‐scrape or re‐import logic here…
            pass
