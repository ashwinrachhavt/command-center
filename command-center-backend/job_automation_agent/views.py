from django.shortcuts import render
from job_automation_agent.models import Job
from django.db.models import Count, Max, Min, Avg
import json

def dashboard_callback(request, context):
    # Basic stats
    total_jobs = Job.objects.count()
    companies = Job.objects.values("company_name").annotate(count=Count("id")).order_by("-count")[:10]
    locations = Job.objects.values("location").annotate(count=Count("id")).order_by("-count")[:10]
    contract_types = Job.objects.values("contract_type").annotate(count=Count("id")).order_by("-count")
    experience_levels = Job.objects.values("experience_level").annotate(count=Count("id")).order_by("-count")
    latest_job = Job.objects.order_by("-published_at").first()
    earliest_job = Job.objects.order_by("published_at").first()
    avg_salary = None  # Placeholder, since salary is a CharField

    # Prepare analytics for dashboard and charts
    contract_data = [{"contract": x["contract_type"], "count": x["count"]} for x in contract_types if x["contract_type"]]
    chart_data = {
        "labels": [item["contract"] for item in contract_data],
        "datasets": [{
            "label": "Job Count by Contract Type",
            "data": [item["count"] for item in contract_data],
            "backgroundColor": "rgba(54, 162, 235, 0.6)"
        }]
    }
    context.update({
        "total_jobs": total_jobs,
        "top_companies": companies,
        "top_locations": locations,
        "contract_types": contract_types,
        "experience_levels": experience_levels,
        "latest_job": latest_job,
        "earliest_job": earliest_job,
        "avg_salary": avg_salary,
        "job_chart": json.dumps(chart_data),
    })
    return context

from django.views.generic import FormView
from django import forms
from django.urls import reverse_lazy
from unfold.views import UnfoldModelAdminViewMixin
from unfold.contrib.forms.widgets import WysiwygWidget

class ChatbotForm(forms.Form):
    content = forms.CharField(
        widget=WysiwygWidget(attrs={
            'class': 'w-full min-h-[30vh] md:min-h-[50vh] p-4 text-lg border-2 border-purple-700 rounded-lg resize-y focus:outline-none focus:ring-2 focus:ring-purple-500 transition-all',
            'autofocus': 'autofocus',
        }),
        label="Question",
        initial="Ask your question here..."
    )

class ChatbotView(UnfoldModelAdminViewMixin, FormView):
    model_admin = None
    permission_required = ()
    title = "Question Answering Chatbot"
    form_class = ChatbotForm
    template_name = "job_automation_agent/chatbot.html"
    success_url = reverse_lazy("admin:index")
    
    def get_model_admin(self):
        from django.contrib import admin
        return admin.site if self.model_admin is None else self.model_admin

    def get_context_data(self, **kwargs):
        if self.model_admin is None:
            self.model_admin = self.get_model_admin()
        if not hasattr(self.model_admin, 'admin_site'):
            self.model_admin.admin_site = self.model_admin
        return super().get_context_data(**kwargs)
