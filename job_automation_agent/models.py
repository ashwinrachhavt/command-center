from django.db import models

class Job(models.Model):
    title             = models.CharField(max_length=512)
    company_name      = models.CharField(max_length=255)
    company_url       = models.URLField(blank=True, null=True)
    location          = models.CharField(max_length=255, blank=True, null=True)
    contract_type     = models.CharField(max_length=64, blank=True, null=True)
    experience_level  = models.CharField(max_length=64, blank=True, null=True)
    work_type         = models.CharField(max_length=64, blank=True, null=True)
    applications_count= models.CharField(max_length=64, blank=True, null=True)
    posted_time       = models.CharField(max_length=64, blank=True, null=True)
    published_at      = models.DateTimeField(blank=True, null=True)
    salary            = models.CharField(max_length=128, blank=True, null=True)
    description       = models.TextField(blank=True, null=True)
    job_url           = models.URLField()
    apply_type        = models.CharField(max_length=32)

    class Meta:
        ordering = ["-published_at"]
        verbose_name = "Job"
        verbose_name_plural = "Jobs"

    def __str__(self):
        return f"{self.title} @ {self.company_name}"
