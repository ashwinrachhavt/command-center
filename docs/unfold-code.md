(Files content cropped to 300k characters, download full ingest to see more)
================================================
FILE: README.md
================================================
# Formula - Django Unfold Admin Demo <!-- omit from toc -->

The Formula repository contains a sample project build upon the Unfold theme for Django. It includes the best practices when it comes to Unfold but keep in mind that it does not incorporate any more in-depth business logic. Everything is composed just for demonstration purposes.

- [Unfold](https://github.com/unfoldadmin/django-unfold) - Admin theme for Django
- [Turbo](https://github.com/unfoldadmin/turbo) - Django & Next.js starter kit including Unfold

## Table of contents <!-- omit from toc -->

- [Installation](#installation)
- [Loading sample data](#loading-sample-data)
- [Custom Dashboard](#custom-dashboard)
- [Compiling Styles](#compiling-styles)

## Installation

First of all, it is required to create new `.env` file containing environment variables for the project. In this case, there are just two most important variables needed to be configured. If you are on local machine, set `DEBUG=1` to enable debug mode for further development. Second variable is `SECRET_KEY` which needs to be configured with some random long and secure string. Project is quite simple and it should be possible to run it without Docker at all. Make sure Python 3.13 is installed together with Poetry and follow the commands below to install all required dependencies and run migrations.

```bash
git clone git@github.com:unfoldadmin/formula.git
```

Run these commands inside `formula` directory, to install all dependencies and to run all migrations.

```bash
docker compose up
```

Create the admin user or you can't access to the instance.

```bash
docker compose exec web python manage.py createsuperuser
```

Run the command below to start the local development server.

## Loading sample data

After successful installation, database will be empty and there will be no data to observe through the admin area. Unfold provides some sample data available under `formula/fixtures`. These data can be loaded via commands below. It is important to run this command against empty database so primary keys will match.

```bash
docker compose exec web python manage.py loaddata formula/fixtures/*
```

## Custom Dashboard

The Formula demonstration project includes a custom dashboard. All components available in the dashboard are custom-made just for showcase and are not a part of Unfold. It means that any real data are used there and in case that real data are involved it is necessary to pass additional data into the template from the database.

All custom widgets used in Formula are located inside `formula/templates/admin/components/`. The main layout for the dashboard is created by overriding `index.html` and the content can be found here `formula/templates/admin/index.html`. For more information check official Unfold documentation.

## Compiling Styles

When creating a custom admin dashboard, you are going to locate all your HTML code with Tailwind classes in your project, so newly added dashboard styles are not compiled. To do so, the first thing which is needed is to edit `UNFOLD` variable in `settings.py` and add `STYLES` key pointing at the new CSS stylesheet containing all new styles.

```python
# settings.py
from django.templatetags.static import static


UNFOLD = {
    "STYLES": [
        lambda request: static("css/styles.css"),
    ],
}
```

To compile new styles, run one of the commands below depending on your needs. To see what exactly the commands are doing and how the files are linked check `scripts` section inside `package.json`.

```bash
npm run tailwind:build  # one-time build
npm run tailwind:watch  # watch all files for changes
```

Before compiling the styles it is important to install all node dependencies as well which in our case contain just TailwindCSS and its typography plugin for styling formatted blocks of texts inside the WYSIWYG editor.

```bash
npm install
```



================================================
FILE: docker-compose.yml
================================================
services:
  web:
    command: bash -c "poetry run python manage.py runserver 0.0.0.0:8000"
    env_file:
      - path: .env
    volumes:
      - .:/code
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"



================================================
FILE: Dockerfile
================================================
FROM python:3.13-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE=1

ENV PYTHONUNBUFFERED=1

RUN mkdir -p /code

WORKDIR /code

RUN pip install poetry

COPY pyproject.toml poetry.lock /code/

RUN poetry config virtualenvs.create false

RUN poetry install --only main --no-root --no-interaction

COPY . /code

WORKDIR /code

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "--bind", ":8000", "--workers", "2", "formula.wsgi"]



================================================
FILE: LICENSE.md
================================================
MIT License

Copyright (c) 2023 Unfold Admin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.



================================================
FILE: manage.py
================================================
#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "formula.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()



================================================
FILE: package.json
================================================
{
	"scripts": {
		"tailwind:build": "npx @tailwindcss/cli -i formula/styles.css -o formula/static/css/styles.css --minify",
		"tailwind:watch": "npx @tailwindcss/cli -i formula/styles.css -o formula/static/css/styles.css --watch --minify"
	},
	"dependencies": {
		"@tailwindcss/cli": "^4.1.7",
		"tailwindcss": "^4.1.7"
	}
}



================================================
FILE: pyproject.toml
================================================
[tool.poetry]
name = "formula"
version = "0.1.0"
description = ""
authors = []
readme = "README.md"

[tool.poetry.dependencies]
python = "^3.13"
django = "^5.2"
django-celery-beat = "^2.8"
django-crispy-forms = "^2.4"
django-debug-toolbar = "^5.2"
django-guardian = "^3.0"
django-import-export = "^4.3"
django-simple-history = "^3.8"
django-modeltranslation = "^0.19"
django-money = "^3.5"
django-unfold = { git = "https://github.com/unfoldadmin/django-unfold.git" }
whitenoise = "^6.9"
gunicorn = "^23.0"
pillow = "^11.2"
sentry-sdk = { extras = ["django"], version = "^2.27" }
pygments = "^2.19"

[tool.ruff]
fix = true
line-length = 88
lint.select = [
    "E",  # pycodestyle errors
    "W",  # pycodestyle warnings
    "F",  # pyflakes
    "I",  # isort
    "C",  # flake8-comprehensions
    "B",  # flake8-bugbear
    "UP", # pyupgrade
]
lint.ignore = [
    "E501", # line too long, handled by black
    "B008", # do not perform function calls in argument defaults
    "C901", # too complex
]
exclude = ["**/migrations"]

[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"



================================================
FILE: .pre-commit-config.yaml
================================================
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: check-case-conflict
      - id: check-json
      - id: check-merge-conflict
      - id: check-symlinks
      - id: check-toml
      - id: end-of-file-fixer
      - id: trailing-whitespace
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.9
    hooks:
      - id: ruff
        args:
          - --fix
      - id: ruff-format
  - repo: https://github.com/compilerla/conventional-pre-commit
    rev: v4.0.0
    hooks:
      - id: conventional-pre-commit
        stages: [commit-msg]
        args: []
  - repo: https://github.com/rtts/djhtml
    rev: 3.0.7
    hooks:
      - id: djhtml
        files: .*/templates/.*\.html$
  - repo: https://github.com/adamchainz/django-upgrade
    rev: 1.23.1
    hooks:
      - id: django-upgrade
        args: ['--target-version', '5.0']



================================================
FILE: formula/__init__.py
================================================



================================================
FILE: formula/admin.py
================================================
import json
import random
from functools import lru_cache

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.contrib.contenttypes.admin import GenericTabularInline
from django.core.validators import EMPTY_VALUES
from django.db import models
from django.db.models import OuterRef, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import path, reverse_lazy
from django.utils.html import format_html
from django.utils.timezone import now, timedelta
from django.utils.translation import gettext_lazy as _
from django_celery_beat.admin import ClockedScheduleAdmin as BaseClockedScheduleAdmin
from django_celery_beat.admin import CrontabScheduleAdmin as BaseCrontabScheduleAdmin
from django_celery_beat.admin import PeriodicTaskAdmin as BasePeriodicTaskAdmin
from django_celery_beat.admin import PeriodicTaskForm, TaskSelectWidget
from django_celery_beat.models import (
    ClockedSchedule,
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    SolarSchedule,
)
from guardian.admin import GuardedModelAdmin
from import_export.admin import (
    ExportActionModelAdmin,
    ImportExportModelAdmin,
)
from modeltranslation.admin import TabbedTranslationAdmin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.components import BaseComponent, register_component
from unfold.contrib.filters.admin import (
    AllValuesCheckboxFilter,
    AutocompleteSelectMultipleFilter,
    BooleanRadioFilter,
    CheckboxFilter,
    ChoicesCheckboxFilter,
    RangeDateFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
    RelatedCheckboxFilter,
    RelatedDropdownFilter,
    SingleNumericFilter,
    SliderNumericFilter,
    TextFilter,
)
from unfold.contrib.forms.widgets import WysiwygWidget
from unfold.contrib.import_export.forms import ExportForm, ImportForm
from unfold.contrib.inlines.admin import NonrelatedStackedInline
from unfold.decorators import action, display
from unfold.enums import ActionVariant
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.paginator import InfinitePaginator
from unfold.sections import TableSection, TemplateSection
from unfold.widgets import (
    UnfoldAdminCheckboxSelectMultiple,
    UnfoldAdminColorInputWidget,
    UnfoldAdminSelectWidget,
    UnfoldAdminSplitDateTimeWidget,
    UnfoldAdminTextInputWidget,
)

from formula.models import (
    Circuit,
    Constructor,
    Driver,
    DriverStatus,
    DriverWithFilters,
    Race,
    Standing,
    Tag,
    User,
)
from formula.resources import AnotherConstructorResource, ConstructorResource
from formula.sites import formula_admin_site
from formula.views import CrispyFormsetView, CrispyFormView

admin.site.unregister(PeriodicTask)
admin.site.unregister(IntervalSchedule)
admin.site.unregister(CrontabSchedule)
admin.site.unregister(SolarSchedule)
admin.site.unregister(ClockedSchedule)
admin.site.unregister(Group)


class UnfoldTaskSelectWidget(UnfoldAdminSelectWidget, TaskSelectWidget):
    pass


class UnfoldPeriodicTaskForm(PeriodicTaskForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["task"].widget = UnfoldAdminTextInputWidget()
        self.fields["regtask"].widget = UnfoldTaskSelectWidget()


@admin.register(PeriodicTask, site=formula_admin_site)
class PeriodicTaskAdmin(BasePeriodicTaskAdmin, ModelAdmin):
    form = UnfoldPeriodicTaskForm


@admin.register(IntervalSchedule, site=formula_admin_site)
class IntervalScheduleAdmin(ModelAdmin):
    pass


@admin.register(CrontabSchedule, site=formula_admin_site)
class CrontabScheduleAdmin(BaseCrontabScheduleAdmin, ModelAdmin):
    pass


@admin.register(SolarSchedule, site=formula_admin_site)
class SolarScheduleAdmin(ModelAdmin):
    pass


@admin.register(ClockedSchedule, site=formula_admin_site)
class ClockedScheduleAdmin(BaseClockedScheduleAdmin, ModelAdmin):
    pass


class CircuitNonrelatedStackedInline(NonrelatedStackedInline):
    model = Circuit
    fields = ["name", "city", "country"]
    extra = 1
    tab = True

    def get_form_queryset(self, obj):
        return self.model.objects.all().distinct()

    def save_new_instance(self, parent, instance):
        pass


class TagGenericTabularInline(TabularInline, GenericTabularInline):
    model = Tag


class UserDriverTabularInline(TabularInline):
    model = Driver
    fk_name = "author"
    autocomplete_fields = ["standing"]
    fields = ["first_name", "last_name", "code", "status", "salary", "category"]


@admin.register(User, site=formula_admin_site)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    list_fullwidth = True
    list_filter = [
        ("is_staff", BooleanRadioFilter),
        ("is_superuser", BooleanRadioFilter),
        ("is_active", BooleanRadioFilter),
        ("groups", RelatedCheckboxFilter),
    ]
    list_filter_submit = True
    list_filter_sheet = False
    inlines = [
        CircuitNonrelatedStackedInline,
        TagGenericTabularInline,
        UserDriverTabularInline,
    ]
    compressed_fields = True
    list_display = [
        "display_header",
        "is_active",
        "display_staff",
        "display_superuser",
        "display_created",
    ]
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            _("Personal info"),
            {
                "fields": (("first_name", "last_name"), "email", "biography"),
                "classes": ["tab"],
            },
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
                "classes": ["tab"],
            },
        ),
        (
            _("Important dates"),
            {
                "fields": ("last_login", "date_joined"),
                "classes": ["tab"],
            },
        ),
    )
    filter_horizontal = (
        "groups",
        "user_permissions",
    )
    formfield_overrides = {
        models.TextField: {
            "widget": WysiwygWidget,
        }
    }
    readonly_fields = ["last_login", "date_joined"]
    show_full_result_count = False

    @display(description=_("User"))
    def display_header(self, instance: User):
        return instance.username

    @display(description=_("Staff"), boolean=True)
    def display_staff(self, instance: User):
        return instance.is_staff

    @display(description=_("Superuser"), boolean=True)
    def display_superuser(self, instance: User):
        return instance.is_superuser

    @display(description=_("Created"))
    def display_created(self, instance: User):
        return instance.created_at


@admin.register(Group, site=formula_admin_site)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    def changelist_view(self, request, extra_context=None):
        messages.success(
            request,
            _(
                "Donec tristique risus ut lobortis consequat. Vestibulum ac volutpat magna. Quisque dictum mauris a rutrum tincidunt. "
            ),
        )
        messages.info(
            request,
            _(
                "Donec tristique risus ut lobortis consequat. Vestibulum ac volutpat magna. Quisque dictum mauris a rutrum tincidunt. "
            ),
        )
        messages.warning(
            request,
            _(
                "Donec tristique risus ut lobortis consequat. Vestibulum ac volutpat magna. Quisque dictum mauris a rutrum tincidunt. "
            ),
        )
        messages.error(
            request,
            _(
                "Donec tristique risus ut lobortis consequat. Vestibulum ac volutpat magna. Quisque dictum mauris a rutrum tincidunt. "
            ),
        )
        return super().changelist_view(request, extra_context=extra_context)


class CircuitRaceInline(StackedInline):
    model = Race
    autocomplete_fields = ["winner"]


@admin.register(Circuit, site=formula_admin_site)
class CircuitAdmin(ModelAdmin, TabbedTranslationAdmin):
    show_facets = admin.ShowFacets.ALLOW
    search_fields = ["name", "city", "country"]
    list_display = ["name", "city", "country"]
    list_filter = ["country"]
    inlines = [CircuitRaceInline]


class DriverTableSection(TableSection):
    related_name = "driver_set"
    fields = ["first_name", "last_name", "code"]


@admin.register(Constructor, site=formula_admin_site)
class ConstructorAdmin(ModelAdmin, ImportExportModelAdmin, ExportActionModelAdmin):
    search_fields = ["name"]
    list_display = ["name"]
    list_sections = [DriverTableSection]
    resource_classes = [ConstructorResource, AnotherConstructorResource]
    save_as = True
    import_form_class = ImportForm
    export_form_class = ExportForm
    # export_form_class = SelectableFieldsExportForm

    actions_list = ["custom_actions_list"]
    actions_row = [
        "custom_actions_row",
        "custom_actions_row2",
        "custom_actions_row3",
        "custom_actions_row4",
        "custom_actions_row5",
    ]
    actions_detail = ["custom_actions_detail"]
    actions_submit_line = ["custom_actions_submit_line"]

    @action(
        description="Custom list action",
        url_path="actions-list-custom-url",
        permissions=[
            "custom_actions_list",
            "another_custom_actions_list",
        ],
    )
    def custom_actions_list(self, request):
        messages.success(request, "List action has been successfully executed.")
        return redirect(request.headers["referer"])

    def has_custom_actions_list_permission(self, request):
        return request.user.is_superuser

    def has_another_custom_actions_list_permission(self, request):
        return request.user.is_staff

    @action(
        description=_("Rebuild Index"),
        url_path="actions-row-custom-url",
        permissions=[
            "custom_actions_row",
            "another_custom_actions_row",
        ],
    )
    def custom_actions_row(self, request, object_id):
        messages.success(
            request, f"Row action has been successfully executed. Object ID {object_id}"
        )
        return redirect(
            request.headers.get("referer")
            or reverse_lazy("admin:formula_constructor_changelist")
        )

    def has_custom_actions_row_permission(self, request, object_id=None):
        return request.user.is_superuser

    def has_another_custom_actions_row_permission(self, request, object_id=None):
        return request.user.is_staff

    @action(description=_("Reindex Cache"), url_path="actions-row-reindex-cache")
    def custom_actions_row2(self, request, object_id):
        messages.success(
            request, f"Row action has been successfully executed. Object ID {object_id}"
        )
        return redirect(
            request.headers.get("referer")
            or reverse_lazy("admin:formula_constructor_changelist")
        )

    @action(description=_("Deploy Hypervisor"), url_path="actions-row-hyperdrive")
    def custom_actions_row3(self, request, object_id):
        messages.success(
            request, f"Row action has been successfully executed. Object ID {object_id}"
        )
        return redirect(
            request.headers.get("referer")
            or reverse_lazy("admin:formula_constructor_changelist")
        )

    @action(description=_("Sync Containers"), url_path="actions-row-sync-containers")
    def custom_actions_row4(self, request, object_id):
        messages.success(
            request, f"Row action has been successfully executed. Object ID {object_id}"
        )
        return redirect(
            request.headers.get("referer")
            or reverse_lazy("admin:formula_constructor_changelist")
        )

    @action(
        description=_("Never visible"),
        url_path="actions-row-deploy-containers",
        permissions=["custom_row_action_false", "custom_row_action_true"],
    )
    def custom_actions_row5(self, request, object_id):
        messages.success(
            request, f"Row action has been successfully executed. Object ID {object_id}"
        )
        return redirect(
            request.headers.get("referer")
            or reverse_lazy("admin:formula_constructor_changelist")
        )

    def has_custom_row_action_false_permission(self, request):
        return False

    def has_custom_row_action_true_permission(self, request):
        return True

    @action(
        description="Custom detail action",
        url_path="actions-detail-custom-url",
        permissions=["custom_actions_detail", "another_custom_actions_detail"],
    )
    def custom_actions_detail(self, request, object_id):
        messages.success(
            request,
            f"Detail action has been successfully executed. Object ID {object_id}",
        )
        return redirect(request.headers["referer"])

    def has_custom_actions_detail_permission(self, request, object_id):
        return request.user.is_superuser

    def has_another_custom_actions_detail_permission(self, request, object_id):
        return request.user.is_staff

    @action(
        description="Custom submit line action",
        permissions=[
            "custom_actions_submit_line",
            "another_custom_actions_submit_line",
        ],
    )
    def custom_actions_submit_line(self, request, obj):
        messages.success(
            request,
            f"Detail action has been successfully executed. Object ID {obj.pk}",
        )

    def has_custom_actions_submit_line_permission(self, request, obj):
        return request.user.is_superuser

    def has_another_custom_actions_submit_line_permission(self, request, obj):
        return request.user.is_staff


class FullNameFilter(TextFilter):
    title = _("full name")
    parameter_name = "fullname"

    def queryset(self, request, queryset):
        if self.value() in EMPTY_VALUES:
            return queryset

        return queryset.filter(
            Q(first_name__icontains=self.value()) | Q(last_name__icontains=self.value())
        )


class DriverStandingInline(TabularInline):
    model = Standing
    fields = ["position", "points", "laps", "race", "weight"]
    readonly_fields = ["race"]
    ordering_field = "weight"
    show_change_link = True
    tab = True

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("race", "driver")
            .prefetch_related("race__circuit")
        )


class RaceWinnerInline(StackedInline):
    model = Race
    fields = ["winner", "year", "laps", "picture", "weight"]
    readonly_fields = ["winner", "year", "laps"]
    ordering_field = "weight"
    extra = 3
    tab = True
    # classes = ["collapse"]


class DriverAdminForm(forms.ModelForm):
    flags = forms.MultipleChoiceField(
        label=_("Flags"),
        choices=[
            ("POPULAR", _("Popular")),
            ("FASTEST", _("Fastest")),
            ("TALENTED", _("Talented")),
        ],
        required=False,
        widget=UnfoldAdminCheckboxSelectMultiple,
    )
    first_name = forms.CharField(
        label=_("First name"),
        widget=UnfoldAdminTextInputWidget,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["first_name"].widget.attrs.update(
            {
                "prefix_icon": "search",
                "suffix_icon": "euro",
            }
        )


class ContructorTableSection(TableSection):
    # verbose_name = _("Constructors - Many to many relationship")
    related_name = "constructors"
    height = 380
    fields = [
        "name",
        "custom_field",
    ]

    @admin.display(description=_("Points"))
    def custom_field(self, instance):
        return random.randint(0, 50)


class ChartSection(TemplateSection):
    template_name = "formula/driver_section.html"


class DriverAdminMixin(ModelAdmin):
    list_sections = [ContructorTableSection, ChartSection]
    list_sections_classes = "lg:grid-cols-2"
    list_editable = ["category"]
    form = DriverAdminForm
    history_list_per_page = 10
    search_fields = ["last_name", "first_name", "code"]
    warn_unsaved_form = True
    compressed_fields = True
    list_display = [
        "display_header",
        "display_constructor",
        "display_total_points",
        "display_total_wins",
        "category",
        "display_status",
        "display_code",
    ]
    inlines = [
        DriverStandingInline,
        RaceWinnerInline,
    ]
    conditional_fields = {
        "conditional_field_active": "status == 'ACTIVE'",
        "conditional_field_inactive": "status == 'INACTIVE'",
    }
    autocomplete_fields = [
        "constructors",
        "editor",
        "standing",
    ]
    radio_fields = {
        "status": admin.VERTICAL,
    }
    readonly_fields = [
        # "author",
        "data",
    ]
    list_before_template = "formula/driver_list_before.html"
    list_after_template = "formula/driver_list_after.html"
    change_form_show_cancel_button = True
    change_form_before_template = "formula/driver_change_form_before.html"
    change_form_after_template = "formula/driver_change_form_after.html"

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        form.base_fields["color"].widget = UnfoldAdminColorInputWidget()
        form.base_fields["first_name"].widget = UnfoldAdminTextInputWidget(
            attrs={"class": "first-name-input"}
        )
        return form

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(total_points=Sum("standing__points"))
            .annotate(
                constructor_name=Constructor.objects.filter(
                    standing__driver_id=OuterRef("pk")
                ).values("name")[:1]
            )
            .prefetch_related(
                "constructors",
                "race_set",
                "race_set__circuit",
                "standings",
                "standings__race",
                "standings__race__circuit",
            )
        )

    @display(description=_("Driver"), header=True)
    def display_header(self, instance: Driver) -> list:
        standing = instance.standings.all().first()

        if not standing:
            return []

        return [
            instance.full_name,
            None,
            instance.initials,
            {
                "path": static("images/avatar.jpg"),
                "height": 24,
                "width": 24,
                "borderless": True,
                # "squared": True,
            },
        ]

    @display(description=_("Constructor"), dropdown=True)
    def display_constructor(self, instance: Driver):
        total = instance.constructors.all().count()
        items = []

        for constructor in instance.constructors.all():
            title = format_html(
                """
                <div class="flex flex-row gap-2 items-center">
                    <span class="truncate">{}</span>
                    <a href="" class="leading-none ml-auto">
                        <span class="material-symbols-outlined leading-none text-base-500">ungroup</span>
                    </a>
                </div>
                """,
                constructor.name,
            )
            items.append(
                {
                    "title": title,
                    # "link": "#",  # Optional: Add a href attribute
                }
            )

        # Display custom string if no records found
        if total == 0:
            return "-"

        return {
            "title": f"{total} contructors",
            "items": items,
            "striped": True,
            # "height": 202,  # Optional, max line height 30px
            # "width": 320,  # Optional
        }

    @display(description=_("Total points"), ordering="total_points")
    def display_total_points(self, instance: Driver):
        return instance.total_points

    @display(description=_("Total wins"))
    def display_total_wins(self, instance: Driver):
        return instance.race_set.count()

    @display(
        description=_("Status"),
        label={
            DriverStatus.INACTIVE: "danger",
            DriverStatus.ACTIVE: "success",
        },
    )
    def display_status(self, instance: Driver):
        if instance.status:
            return instance.status

        return None

    @display(description=_("Code"), label=True)
    def display_code(self, instance: Driver):
        return instance.code


@admin.register(Driver, site=formula_admin_site)
class DriverAdmin(GuardedModelAdmin, SimpleHistoryAdmin, DriverAdminMixin):
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "first_name",
                    "last_name",
                    "salary",
                    "category",
                    "picture",
                    "born_at",
                    "last_race_at",
                    "best_time",
                    "first_race_at",
                    "resume",
                    "author",
                    "editor",
                    "standing",
                    "constructors",
                    "code",
                    "color",
                    "link",
                    "data",
                ]
            },
        ),
        (
            _("Conditional fields"),
            {
                "classes": ["tab"],
                "fields": [
                    "status",
                    "conditional_field_active",
                    "conditional_field_inactive",
                ],
            },
        ),
        (
            _("Boolean fields"),
            {
                "classes": ["tab"],
                "fields": [
                    "is_active",
                    "is_hidden",
                ],
            },
        ),
    ]
    actions_list = [
        "changelist_action_should_not_be_visible",
        "changelist_action1",
        "changelist_action4",
        {
            "title": _("More"),
            "variant": ActionVariant.PRIMARY,
            "items": [
                "changelist_action3",
                "changelist_action4",
                "changelist_action5",
            ],
        },
    ]
    actions_detail = [
        "change_detail_action3",
        "change_detail_action",
        {
            "title": _("More"),
            "items": [
                "change_detail_action1",
                "change_detail_action2",
            ],
        },
    ]

    def get_urls(self):
        return super().get_urls() + [
            path(
                "crispy-with-formset",
                self.admin_site.admin_view(CrispyFormsetView.as_view(model_admin=self)),
                name="crispy_formset",
            ),
            path(
                "crispy-form",
                self.admin_site.admin_view(CrispyFormView.as_view(model_admin=self)),
                name="crispy_form",
            ),
        ]

    @action(description=_("Initialize nodes"), icon="hub")
    def changelist_action1(self, request):
        messages.success(
            request, _("Changelist action has been successfully executed.")
        )
        return redirect(reverse_lazy("admin:formula_driver_changelist"))

    @action(
        description=_("Sync DB replicas"),
        icon="sync",
    )
    def changelist_action3(self, request):
        messages.success(
            request, _("Changelist action has been successfully executed.")
        )
        return redirect(reverse_lazy("admin:formula_driver_changelist"))

    @action(description=_("Rebuild cache index"), icon="book_4")
    def changelist_action4(self, request):
        messages.success(
            request, _("Changelist action has been successfully executed.")
        )
        return redirect(reverse_lazy("admin:formula_driver_changelist"))

    @action(description=_("Optimize queries"), icon="database")
    def changelist_action5(self, request):
        messages.success(
            request, _("Changelist action has been successfully executed.")
        )
        return redirect(reverse_lazy("admin:formula_driver_changelist"))

    @action(
        description=_("Should not be visible"), permissions=["should_not_be_visible"]
    )
    def changelist_action_should_not_be_visible(self, request):
        messages.success(
            request, _("Changelist action has been successfully executed.")
        )
        return redirect(reverse_lazy("admin:formula_driver_changelist"))

    def has_should_not_be_visible_permission(self, request):
        return False

    @action(
        description=_("Action with form"),
        url_path="change-detail-action",
        permissions=["change_detail_action"],
    )
    def change_detail_action(self, request, object_id):
        try:
            object_id = int(object_id)
        except (TypeError, ValueError) as e:
            raise Http404 from e

        object = get_object_or_404(Driver, pk=object_id)

        class SomeForm(forms.Form):
            # It is important to set a widget coming from Unfold
            from_date = forms.SplitDateTimeField(
                label="From Date", widget=UnfoldAdminSplitDateTimeWidget, required=False
            )
            to_date = forms.SplitDateTimeField(
                label="To Date", widget=UnfoldAdminSplitDateTimeWidget, required=False
            )
            note = forms.CharField(label=_("Note"), widget=UnfoldAdminTextInputWidget)

            class Media:
                js = [
                    "admin/js/vendor/jquery/jquery.js",
                    "admin/js/jquery.init.js",
                    "admin/js/calendar.js",
                    "admin/js/admin/DateTimeShortcuts.js",
                    "admin/js/core.js",
                ]

        form = SomeForm(request.POST or None)

        if request.method == "POST" and form.is_valid():
            # form.cleaned_data["note"]

            messages.success(request, _("Change detail action has been successful."))

            return redirect(
                reverse_lazy("admin:formula_driver_change", args=[object_id])
            )

        return render(
            request,
            "formula/driver_action.html",
            {
                "form": form,
                "object": object,
                "title": _("Change detail action for {}").format(object),
                **self.admin_site.each_context(request),
            },
        )

    def has_change_detail_action_permission(self, request, object_id=None):
        return request.user.is_superuser

    @action(description=_("Revalidate cache"), permissions=["revalidate_cache"])
    def change_detail_action1(self, request, object_id):
        messages.success(
            request, _("Change detail action has been successfully executed.")
        )
        return redirect(reverse_lazy("admin:formula_driver_change", args=[object_id]))

    def has_revalidate_cache_permission(self, request, object_id):
        return request.user.is_superuser

    @action(description=_("Deactivate object"))
    def change_detail_action2(self, request, object_id):
        messages.success(
            request, _("Change detail action has been successfully executed.")
        )
        return redirect(reverse_lazy("admin:formula_driver_change", args=[object_id]))

    @action(
        description=_("Never visible"),
        permissions=["change_detail_false"],
    )
    def change_detail_action3(self, request, object_id):
        messages.success(
            request, _("Change detail action has been successfully executed.")
        )
        return redirect(reverse_lazy("admin:formula_driver_change", args=[object_id]))

    def has_change_detail_false_permission(self, request, object_id=None):
        return False


class DriverCustomCheckboxFilter(CheckboxFilter):
    title = _("Custom status")
    parameter_name = "custom_status"

    def lookups(self, request, model_admin):
        return DriverStatus.choices

    def queryset(self, request, queryset):
        if self.value() not in EMPTY_VALUES:
            return queryset.filter(status__in=self.value())
        elif self.parameter_name in self.used_parameters:
            return queryset.filter(status=self.used_parameters[self.parameter_name])

        return queryset


@admin.register(DriverWithFilters, site=formula_admin_site)
class DriverWithFiltersAdmin(DriverAdminMixin):
    list_fullwidth = True
    list_filter = [
        FullNameFilter,
        ("constructors", AutocompleteSelectMultipleFilter),
        ("race__circuit", RelatedDropdownFilter),
        ("salary", SliderNumericFilter),
        ("status", ChoicesCheckboxFilter),
        ("category", AllValuesCheckboxFilter),
        DriverCustomCheckboxFilter,
        ("is_hidden", BooleanRadioFilter),
        ("is_active", BooleanRadioFilter),
    ]
    list_filter_sheet = False
    list_filter_submit = True


@admin.register(Race, site=formula_admin_site)
class RaceAdmin(ModelAdmin):
    date_hierarchy = "date"
    search_fields = [
        "circuit__name",
        "circuit__city",
        "circuit__country",
        "winner__first_name",
        "winner__last_name",
    ]
    list_filter = [
        ("circuit", RelatedCheckboxFilter),
        ("year", RangeNumericFilter),
        ("laps", SingleNumericFilter),
        ("date", RangeDateFilter),
        ("created_at", RangeDateTimeFilter),
    ]
    list_filter_sheet = False
    list_filter_submit = True
    raw_id_fields = ["circuit", "winner"]
    list_display = ["circuit", "winner", "year", "laps", "date"]
    list_fullwidth = True
    autocomplete_fields = ["circuit", "winner"]


@admin.register(Standing, site=formula_admin_site)
class StandingAdmin(ModelAdmin):
    # list_disable_select_all = True
    search_fields = [
        "race__circuit__name",
        "race__circuit__city",
        "race__circuit__country",
        "driver__first_name",
        "driver__last_name",
    ]
    list_display = ["race", "driver", "constructor", "position", "points"]
    list_filter = ["driver"]
    autocomplete_fields = ["driver", "constructor", "race"]
    readonly_fields = ["laps"]
    paginator = InfinitePaginator
    show_full_result_count = False
    list_disable_select_all = True
    list_paginate_by = 10


try:
    from unfold_studio.admin import StudioOptionAdmin
    from unfold_studio.models import StudioOption

    @admin.register(StudioOption, site=formula_admin_site)
    class StudioOptionAdmin(StudioOptionAdmin, ModelAdmin):
        pass
except (ImportError, RuntimeError):
    # unfold_studio is not installed
    pass


@lru_cache
def tracker_random_data():
    data = []

    for _i in range(1, 64):
        has_value = random.choice([True, True, True, True, False])
        color = None
        tooltip = None

        if has_value:
            value = random.randint(2, 6)
            color = "bg-primary-500"
            tooltip = f"Value {value}"

        data.append(
            {
                "color": color,
                "tooltip": tooltip,
            }
        )

    return data


@register_component
class TrackerComponent(BaseComponent):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["data"] = tracker_random_data()
        return context


@lru_cache
def cohort_random_data():
    rows = []
    headers = []
    cols = []

    dates = reversed(
        [(now() - timedelta(days=x)).strftime("%B %d, %Y") for x in range(8)]
    )
    groups = range(1, 10)

    for row_index, date in enumerate(dates):
        cols = []

        for col_index, _col in enumerate(groups):
            color_index = 8 - row_index - col_index
            col_classes = []

            if color_index > 0:
                col_classes.append(
                    f"bg-primary-{color_index}00 dark:bg-primary-{9 - color_index}00"
                )

            if color_index >= 4:
                col_classes.append("text-white dark:text-base-600")

            value = random.randint(
                4000 - (col_index * row_index * 225),
                5000 - (col_index * row_index * 225),
            )

            subtitle = f"{random.randint(10, 100)}%"

            if value <= 0:
                value = 0
                subtitle = None

            cols.append(
                {
                    "value": value,
                    "color": " ".join(col_classes),
                    "subtitle": subtitle,
                }
            )

        rows.append(
            {
                "header": {
                    "title": date,
                    "subtitle": f"Total {sum(col['value'] for col in cols):,}",
                },
                "cols": cols,
            }
        )

    for index, group in enumerate(groups):
        total = sum(row["cols"][index]["value"] for row in rows)

        headers.append(
            {
                "title": f"Group #{group}",
                "subtitle": f"Total {total:,}",
            }
        )

    return {
        "headers": headers,
        "rows": rows,
    }


@register_component
class CohortComponent(BaseComponent):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["data"] = cohort_random_data()
        return context


@register_component
class DriverActiveComponent(BaseComponent):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["children"] = render_to_string(
            "formula/helpers/kpi_progress.html",
            {
                "total": Driver.objects.filter(status=DriverStatus.ACTIVE).count(),
                "progress": "positive",
                "percentage": "2.8%",
            },
        )
        return context


@register_component
class DriverInactiveComponent(BaseComponent):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["children"] = render_to_string(
            "formula/helpers/kpi_progress.html",
            {
                "total": Driver.objects.filter(status=DriverStatus.INACTIVE).count(),
                "progress": "negative",
                "percentage": "-12.8%",
            },
        )
        return context


@register_component
class DriverTotalPointsComponent(BaseComponent):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["children"] = render_to_string(
            "formula/helpers/kpi_progress.html",
            {
                "total": Standing.objects.aggregate(total_points=Sum("points"))[
                    "total_points"
                ],
                "progress": "positive",
                "percentage": "24.2%",
            },
        )
        return context


@register_component
class DriverRacesComponent(BaseComponent):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["children"] = render_to_string(
            "formula/helpers/kpi_progress.html",
            {
                "total": Race.objects.count(),
                "progress": "negative",
                "percentage": "-10.0%",
            },
        )
        return context


@register_component
class DriverSectionChangeComponent(BaseComponent):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        WEEKDAYS = [
            "Mon",
            "Tue",
            "Wed",
            "Thu",
            "Fri",
            "Sat",
            "Sun",
        ]
        OF_DAYS = 21

        context["data"] = json.dumps(
            {
                "labels": [WEEKDAYS[day % 7] for day in range(1, OF_DAYS)],
                "datasets": [
                    {
                        "data": [
                            [1, random.randrange(8, OF_DAYS)] for i in range(1, OF_DAYS)
                        ],
                        "backgroundColor": "var(--color-primary-600)",
                    }
                ],
            }
        )
        return context



================================================
FILE: formula/apps.py
================================================
from django.apps import AppConfig


class FormulaAdminConfig(AppConfig):
    name = "formula"
    default = True

    def ready(self):
        import formula.signals  # NOQA



================================================
FILE: formula/asgi.py
================================================
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "formula.settings")

application = get_asgi_application()



================================================
FILE: formula/context_processors.py
================================================
from django.conf import settings


def variables(request):
    return {"plausible_domain": settings.PLAUSIBLE_DOMAIN}



================================================
FILE: formula/encoders.py
================================================
import json


class PrettyJSONEncoder(json.JSONEncoder):
    def __init__(self, *args, indent, sort_keys, **kwargs):
        super().__init__(*args, indent=4, sort_keys=True, **kwargs)



================================================
FILE: formula/exceptions.py
================================================
class ReadonlyException(Exception):
    pass



================================================
FILE: formula/forms.py
================================================
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Column, Div, Fieldset, Layout, Row
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.views.generic import RedirectView
from unfold.forms import AuthenticationForm
from unfold.layout import Submit
from unfold.widgets import (
    UnfoldAdminCheckboxSelectMultiple,
    UnfoldAdminDateWidget,
    UnfoldAdminEmailInputWidget,
    UnfoldAdminExpandableTextareaWidget,
    UnfoldAdminFileFieldWidget,
    UnfoldAdminImageFieldWidget,
    UnfoldAdminIntegerFieldWidget,
    UnfoldAdminMoneyWidget,
    UnfoldAdminRadioSelectWidget,
    UnfoldAdminSelect2Widget,
    UnfoldAdminSplitDateTimeWidget,
    UnfoldAdminTextareaWidget,
    UnfoldAdminTextInputWidget,
    UnfoldAdminTimeWidget,
    UnfoldAdminURLInputWidget,
    UnfoldBooleanSwitchWidget,
)

from formula.models import Driver


class HomeView(RedirectView):
    pattern_name = "admin:index"


class CustomForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        label=_("Name"),
        required=True,
        widget=UnfoldAdminTextInputWidget(),
    )
    email = forms.EmailField(
        label=_("Email"),
        required=True,
        widget=UnfoldAdminEmailInputWidget(),
    )
    age = forms.IntegerField(
        label=_("Age"),
        required=True,
        min_value=18,
        max_value=120,
        widget=UnfoldAdminIntegerFieldWidget(),
    )
    url = forms.URLField(
        label=_("URL"),
        required=True,
        widget=UnfoldAdminURLInputWidget(),
    )
    salary = forms.DecimalField(
        label=_("Salary"),
        required=True,
        help_text=_("Enter your salary"),
        widget=UnfoldAdminMoneyWidget(),
    )
    title = forms.CharField(
        label=_("Title"),
        required=True,
        widget=UnfoldAdminExpandableTextareaWidget(),
    )
    message = forms.CharField(
        label=_("Message"),
        required=True,
        widget=UnfoldAdminTextareaWidget(),
    )
    subscribe = forms.BooleanField(
        label=_("Subscribe to newsletter"),
        required=True,
        initial=True,
        help_text=_("Toggle to receive our newsletter with updates and offers"),
        widget=UnfoldBooleanSwitchWidget,
    )
    notifications = forms.BooleanField(
        label=_("Receive notifications"),
        required=True,
        initial=False,
        help_text=_("Toggle to receive notifications about your inquiry status"),
        widget=UnfoldBooleanSwitchWidget,
    )
    department = forms.ChoiceField(
        label=_("Department"),
        choices=[
            ("sales", _("Sales")),
            ("marketing", _("Marketing")),
            ("development", _("Development")),
            ("hr", _("Human Resources")),
            ("other", _("Other")),
        ],
        required=True,
        help_text=_("Select the department to contact"),
        widget=UnfoldAdminRadioSelectWidget,
    )
    category = forms.ChoiceField(
        label=_("Category"),
        choices=[
            ("general", _("General Inquiry")),
            ("support", _("Technical Support")),
            ("feedback", _("Feedback")),
            ("other", _("Other")),
        ],
        required=True,
        help_text=_("Select the category of your message"),
        widget=UnfoldAdminCheckboxSelectMultiple,
    )
    priority = forms.TypedChoiceField(
        label=_("Priority"),
        choices=[
            (1, _("Low")),
            (2, _("Medium")),
            (3, _("High")),
        ],
        coerce=int,
        required=True,
        initial=2,
        help_text=_("Select the priority of your message"),
        widget=UnfoldAdminSelect2Widget,
    )
    date = forms.DateField(
        label=_("Date"),
        required=True,
        widget=UnfoldAdminDateWidget,
    )
    time = forms.TimeField(
        label=_("Time"),
        required=True,
        widget=UnfoldAdminTimeWidget,
    )
    datetime = forms.SplitDateTimeField(
        label=_("Date and Time"),
        required=True,
        widget=UnfoldAdminSplitDateTimeWidget,
    )
    file = forms.FileField(
        label=_("File"),
        required=True,
        widget=UnfoldAdminFileFieldWidget,
    )
    image = forms.ImageField(
        label=_("Image"),
        required=True,
        widget=UnfoldAdminImageFieldWidget,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.add_input(Submit("submit", _("Submit")))
        self.helper.add_input(Submit("submit", _("Submit 2")))
        self.helper.add_input(Submit("submit", _("Submit 3")))
        self.helper.attrs = {
            "novalidate": "novalidate",
        }
        self.helper.layout = Layout(
            Row(
                Column(
                    Fieldset(
                        _("Custom form"),
                        Column(
                            Row(
                                Div("name", css_class="w-1/2"),
                                Div("email", css_class="w-1/2"),
                            ),
                            Row(
                                Div("age", css_class="w-1/2"),
                                Div("url", css_class="w-1/2"),
                            ),
                            "salary",
                            "priority",
                            css_class="gap-5",
                        ),
                    ),
                    Fieldset(
                        _("Textarea & expandable textarea widgets"),
                        "title",
                        "message",
                    ),
                    css_class="lg:w-1/2",
                ),
                Column(
                    Fieldset(
                        _("Radio & checkbox widgets"),
                        Column(
                            "subscribe",
                            "notifications",
                            Row(
                                Div("department", css_class="w-1/2"),
                                Div("category", css_class="w-1/2"),
                            ),
                            css_class="gap-5",
                        ),
                    ),
                    Fieldset(
                        _("File upload widgets"),
                        Column(
                            "file",
                            "image",
                            css_class="gap-5",
                        ),
                    ),
                    Fieldset(
                        _("Date & time widgets"),
                        Column(
                            "date",
                            "time",
                            "datetime",
                            css_class="gap-5",
                        ),
                    ),
                    css_class="lg:w-1/2",
                ),
                css_class="mb-8",
            ),
        )


class DriverFormHelper(FormHelper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.template = "unfold_crispy/layout/table_inline_formset.html"
        self.form_id = "driver-formset"
        self.form_add = True
        self.form_show_labels = False
        self.attrs = {
            "novalidate": "novalidate",
        }
        self.add_input(Submit("submit", _("Another submit")))
        self.add_input(Submit("submit", _("Submit")))


class DriverForm(forms.ModelForm):
    class Meta:
        model = Driver
        fields = [
            "first_name",
            "last_name",
            "code",
        ]
        widgets = {
            "first_name": UnfoldAdminTextInputWidget(),
            "last_name": UnfoldAdminTextInputWidget(),
            "code": UnfoldAdminTextInputWidget(),
        }

    def clean(self):
        raise ValidationError("Testing form wide error messages.")


class DriverFormSet(forms.BaseModelFormSet):
    def clean(self):
        raise ValidationError("Testing formset wide error messages.")


class LoginForm(AuthenticationForm):
    password = forms.CharField(widget=forms.PasswordInput(render_value=True))

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)

        if settings.LOGIN_USERNAME and settings.LOGIN_PASSWORD:
            self.fields["username"].initial = settings.LOGIN_USERNAME
            self.fields["password"].initial = settings.LOGIN_PASSWORD



================================================
FILE: formula/middleware.py
================================================
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _


class ReadonlyExceptionHandlerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_exception(self, request, exception):
        if (
            exception
            and repr(exception)
            == "ReadonlyException('Database is operating in readonly mode. Not possible to save any data.')"
        ):
            messages.warning(
                request,
                _(
                    "Database is operating in readonly mode. Not possible to save any data."
                ),
            )
            return redirect(request.headers.get("referer", reverse_lazy("admin:login")))



================================================
FILE: formula/models.py
================================================
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField
from simple_history.models import HistoricalRecords

from formula.encoders import PrettyJSONEncoder


class DriverStatus(models.TextChoices):
    ACTIVE = "ACTIVE", _("Active")
    INACTIVE = "INACTIVE", _("Inactive")


class DriverCategory(models.TextChoices):
    ROOKIE = "ROOKIE", _("Rookie")
    EXPERIENCED = "EXPERIENCED", _("Experienced")
    VETERAN = "VETERAN", _("Veteran")
    CHAMPION = "CHAMPION", _("Champion")


class AuditedModel(models.Model):
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    modified_at = models.DateTimeField(_("modified at"), auto_now=True)

    class Meta:
        abstract = True


class Tag(AuditedModel):
    title = models.CharField(_("title"), max_length=255)
    slug = models.CharField(_("slug"), max_length=255)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, verbose_name=_("content type")
    )
    object_id = models.PositiveIntegerField(_("object id"))
    content_object = GenericForeignKey("content_type", "object_id")

    def __str__(self):
        return self.tag

    class Meta:
        db_table = "tags"
        verbose_name = _("tag")
        verbose_name_plural = _("tags")
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]


class User(AbstractUser, AuditedModel):
    biography = models.TextField(_("biography"), null=True, blank=True, default=None)
    tags = GenericRelation(Tag)

    class Meta:
        db_table = "users"
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.email if self.email else self.username

    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f"{self.last_name}, {self.first_name}"

        return None


class Circuit(AuditedModel):
    name = models.CharField(_("name"), max_length=255)
    city = models.CharField(_("city"), max_length=255)
    country = models.CharField(_("country"), max_length=255)
    data = models.JSONField(_("data"), null=True, blank=True)

    class Meta:
        db_table = "circuits"
        verbose_name = _("circuit")
        verbose_name_plural = _("circuits")

    def __str__(self):
        return self.name


class Driver(AuditedModel):
    first_name = models.CharField(_("first name"), max_length=255)
    last_name = models.CharField(_("last name"), max_length=255)
    salary = MoneyField(
        max_digits=14, decimal_places=2, null=True, blank=True, default_currency=None
    )
    category = models.CharField(
        _("category"),
        choices=DriverCategory.choices,
        null=True,
        blank=True,
        max_length=255,
    )
    picture = models.ImageField(_("picture"), null=True, blank=True, default=None)
    born_at = models.DateField(_("born"), null=True, blank=True)
    last_race_at = models.DateField(_("last race"), null=True, blank=True)
    best_time = models.TimeField(_("best time"), null=True, blank=True)
    first_race_at = models.DateTimeField(_("first race"), null=True, blank=True)
    resume = models.FileField(_("resume"), null=True, blank=True, default=None)
    author = models.ForeignKey(
        "User",
        verbose_name=_("author"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    editor = models.ForeignKey(
        "User",
        verbose_name=_("editor"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="driver_editor",
    )
    standing = models.ForeignKey(
        "Standing",
        verbose_name=_("standing"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="standing",
    )
    constructors = models.ManyToManyField(
        "Constructor", verbose_name=_("constructors"), blank=True
    )
    code = models.CharField(_("code"), max_length=3)
    color = models.CharField(_("color"), null=True, blank=True, max_length=255)
    link = models.URLField(_("link"), null=True, blank=True)
    status = models.CharField(
        _("status"),
        choices=DriverStatus.choices,
        null=True,
        blank=True,
        max_length=255,
    )
    conditional_field_active = models.CharField(
        _("conditional field active"),
        null=True,
        blank=True,
        max_length=255,
        help_text="This field is only visible if the status is ACTIVE",
    )
    conditional_field_inactive = models.CharField(
        _("conditional field inactive"),
        null=True,
        blank=True,
        max_length=255,
        help_text="This field is only visible if the status is INACTIVE",
    )
    data = models.JSONField(_("data"), null=True, blank=True, encoder=PrettyJSONEncoder)
    history = HistoricalRecords()
    is_active = models.BooleanField(_("active"), default=False)
    is_hidden = models.BooleanField(_("hidden"), default=False)

    class Meta:
        db_table = "drivers"
        verbose_name = _("driver")
        verbose_name_plural = _("drivers")
        permissions = (("update_statistics", _("Update statistics")),)

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f"{self.last_name}, {self.first_name}"

        return None

    @property
    def initials(self):
        if self.first_name and self.last_name:
            return f"{self.first_name[0]}{self.last_name[0]}"

        return None


class DriverWithFilters(Driver):
    history = HistoricalRecords()

    class Meta:
        proxy = True


class Constructor(AuditedModel):
    name = models.CharField(_("name"), max_length=255)

    class Meta:
        db_table = "constructors"
        verbose_name = _("constructor")
        verbose_name_plural = _("constructors")

    def __str__(self):
        return self.name


class Race(AuditedModel):
    circuit = models.ForeignKey(
        Circuit, verbose_name=_("circuit"), on_delete=models.PROTECT
    )
    winner = models.ForeignKey(
        Driver, verbose_name=_("winner"), on_delete=models.PROTECT
    )
    picture = models.ImageField(_("picture"), null=True, blank=True, default=None)
    year = models.PositiveIntegerField(_("year"))
    laps = models.PositiveIntegerField(_("laps"))
    date = models.DateField(_("date"))
    weight = models.PositiveIntegerField(_("weight"), default=0, db_index=True)

    class Meta:
        db_table = "races"
        verbose_name = _("race")
        verbose_name_plural = _("races")
        ordering = ["weight"]

    def __str__(self):
        return f"{self.circuit.name}, {self.year}"


class Standing(AuditedModel):
    race = models.ForeignKey(Race, verbose_name=_("race"), on_delete=models.PROTECT)
    driver = models.ForeignKey(
        Driver,
        verbose_name=_("driver"),
        on_delete=models.PROTECT,
        related_name="standings",
    )
    constructor = models.ForeignKey(
        Constructor, verbose_name=_("constructor"), on_delete=models.PROTECT
    )
    position = models.PositiveIntegerField(_("position"))
    number = models.PositiveIntegerField(_("number"))
    laps = models.PositiveIntegerField(_("laps"))
    points = models.DecimalField(_("points"), decimal_places=2, max_digits=4)
    weight = models.PositiveIntegerField(_("weight"), default=0, db_index=True)

    class Meta:
        db_table = "standings"
        verbose_name = _("standing")
        verbose_name_plural = _("standings")
        ordering = ["weight"]

    def __str__(self):
        return f"{self.driver.full_name}, {self.position}"



================================================
FILE: formula/resources.py
================================================
from import_export import resources

from formula.models import Constructor


class ConstructorResource(resources.ModelResource):
    class Meta:
        model = Constructor


class AnotherConstructorResource(resources.ModelResource):
    class Meta:
        model = Constructor



================================================
FILE: formula/settings.py
================================================
from os import environ, path
from pathlib import Path

import sentry_sdk
from django.core.management.utils import get_random_secret_key
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

######################################################################
# General
######################################################################
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = environ.get("SECRET_KEY", get_random_secret_key())

DEBUG = environ.get("DEBUG") == "1"

ROOT_URLCONF = "formula.urls"

WSGI_APPLICATION = "formula.wsgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATA_UPLOAD_MAX_NUMBER_FIELDS = 10_000

######################################################################
# Domains
######################################################################
ALLOWED_HOSTS = environ.get("ALLOWED_HOSTS", "localhost").split(",")

CSRF_TRUSTED_ORIGINS = environ.get(
    "CSRF_TRUSTED_ORIGINS", "http://localhost:8000"
).split(",")

######################################################################
# Apps
######################################################################
INSTALLED_APPS = [
    "modeltranslation",
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.import_export",
    "unfold.contrib.guardian",
    "unfold.contrib.simple_history",
    "unfold.contrib.forms",
    "unfold.contrib.inlines",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.humanize",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "debug_toolbar",
    "crispy_forms",
    "import_export",
    "guardian",
    "simple_history",
    "django_celery_beat",
    "djmoney",
    "formula",
]

if environ.get("UNFOLD_STUDIO") == "1":
    INSTALLED_APPS.insert(0, "unfold_studio")

######################################################################
# Middleware
######################################################################
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "formula.middleware.ReadonlyExceptionHandlerMiddleware",
]

######################################################################
# Sessions
######################################################################
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"

######################################################################
# Templates
######################################################################
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            path.normpath(path.join(BASE_DIR, "formula/templates")),
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "formula.context_processors.variables",
            ],
        },
    },
]

######################################################################
# Databases
######################################################################
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "database.sqlite",
    },
}

######################################################################
# Authentication
######################################################################
AUTH_USER_MODEL = "formula.User"

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "guardian.backends.ObjectPermissionBackend",
)

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LOGIN_URL = "admin:login"

LOGIN_REDIRECT_URL = reverse_lazy("admin:index")

######################################################################
# Localization
######################################################################
LANGUAGE_CODE = "en"

TIME_ZONE = "Europe/Bratislava"

USE_I18N = True

USE_TZ = True

LANGUAGES = (
    ("de", _("German")),
    ("en", _("English")),
)

# https://docs.djangoproject.com/en/5.1/ref/settings/#date-input-formats
DATE_INPUT_FORMATS = [
    "%d.%m.%Y",  # Custom input
    "%Y-%m-%d",  # '2006-10-25'
    "%m/%d/%Y",  # '10/25/2006'
    "%m/%d/%y",  # '10/25/06'
    "%b %d %Y",  # 'Oct 25 2006'
    "%b %d, %Y",  # 'Oct 25, 2006'
    "%d %b %Y",  # '25 Oct 2006'
    "%d %b, %Y",  # '25 Oct, 2006'
    "%B %d %Y",  # 'October 25 2006'
    "%B %d, %Y",  # 'October 25, 2006'
    "%d %B %Y",  # '25 October 2006'
    "%d %B, %Y",  # '25 October, 2006'
]

# https://docs.djangoproject.com/en/5.1/ref/settings/#datetime-input-formats
DATETIME_INPUT_FORMATS = [
    "%d.%m.%Y %H:%M:%S",  # Custom input
    "%Y-%m-%d %H:%M:%S",  # '2006-10-25 14:30:59'
    "%Y-%m-%d %H:%M:%S.%f",  # '2006-10-25 14:30:59.000200'
    "%Y-%m-%d %H:%M",  # '2006-10-25 14:30'
    "%m/%d/%Y %H:%M:%S",  # '10/25/2006 14:30:59'
    "%m/%d/%Y %H:%M:%S.%f",  # '10/25/2006 14:30:59.000200'
    "%m/%d/%Y %H:%M",  # '10/25/2006 14:30'
    "%m/%d/%y %H:%M:%S",  # '10/25/06 14:30:59'
    "%m/%d/%y %H:%M:%S.%f",  # '10/25/06 14:30:59.000200'
    "%m/%d/%y %H:%M",  # '10/25/06 14:30'
]

######################################################################
# Static
######################################################################
STATIC_URL = "/static/"

STATICFILES_DIRS = [BASE_DIR / "formula" / "static"]

STATIC_ROOT = BASE_DIR / "static"

MEDIA_ROOT = BASE_DIR / "media"

MEDIA_URL = "/media/"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

######################################################################
# Unfold
######################################################################
UNFOLD = {
    "SITE_TITLE": _("Formula Admin"),
    "SITE_HEADER": _("Formula Admin"),
    "SITE_SUBHEADER": _("Unfold demo project"),
    # "SITE_URL": None,
    "SITE_DROPDOWN": [
        {
            "icon": "diamond",
            "title": _("Unfold theme repository"),
            "link": "https://github.com/unfoldadmin/django-unfold",
        },
        {
            "icon": "rocket_launch",
            "title": _("Turbo boilerplate repository"),
            "link": "https://github.com/unfoldadmin/turbo",
        },
        {
            "icon": "description",
            "title": _("Technical documentation"),
            "link": "https://unfoldadmin.com/docs/",
        },
    ],
    "SITE_SYMBOL": "settings",
    # "SHOW_HISTORY": True,
    "SHOW_LANGUAGES": True,
    "ENVIRONMENT": "formula.utils.environment_callback",
    "DASHBOARD_CALLBACK": "formula.views.dashboard_callback",
    "LOGIN": {
        "image": lambda request: static("images/login-bg.jpg"),
    },
    "STYLES": [
        lambda request: static("css/styles.css"),
    ],
    "SCRIPTS": [
        # lambda request: static("js/chart.min.js"),
    ],
    "TABS": [
        {
            "page": "drivers",
            "models": ["formula.driver"],
            "items": [
                {
                    "title": _("Drivers"),
                    "link": reverse_lazy("admin:formula_driver_changelist"),
                    "active": lambda request: request.path
                    == reverse_lazy("admin:formula_driver_changelist")
                    and "status__exact" not in request.GET,
                },
                {
                    "title": _("Active drivers"),
                    "link": lambda request: f"{
                        reverse_lazy('admin:formula_driver_changelist')
                    }?status__exact=ACTIVE",
                },
                {
                    "title": _("Crispy Form"),
                    "link": reverse_lazy("admin:crispy_form"),
                },
                {
                    "title": _("Crispy Formset"),
                    "link": reverse_lazy("admin:crispy_formset"),
                },
            ],
        },
    ],
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [
            {
                "title": _("Navigation"),
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                    {
                        "title": _("Drivers"),
                        "icon": "sports_motorsports",
                        "active": "formula.utils.driver_list_link_callback",
                        ###########################################################
                        # Works only with Studio: https://unfoldadmin.com/studio/
                        ###########################################################
                        "items": [
                            {
                                "title": _("List drivers"),
                                "link": reverse_lazy("admin:formula_driver_changelist"),
                                "active": "formula.utils.driver_list_link_callback",
                            },
                            {
                                "title": _("Advanced filters"),
                                "link": reverse_lazy(
                                    "admin:formula_driverwithfilters_changelist"
                                ),
                            },
                            {
                                "title": _("Crispy form"),
                                "link": reverse_lazy("admin:crispy_form"),
                            },
                            {
                                "title": _("Crispy formset"),
                                "link": reverse_lazy("admin:crispy_formset"),
                            },
                        ],
                    },
                    {
                        "title": _("Circuits"),
                        "icon": "sports_score",
                        "link": reverse_lazy("admin:formula_circuit_changelist"),
                    },
                    {
                        "title": _("Constructors"),
                        "icon": "engineering",
                        "link": reverse_lazy("admin:formula_constructor_changelist"),
                    },
                    {
                        "title": _("Races"),
                        "icon": "stadium",
                        "link": reverse_lazy("admin:formula_race_changelist"),
                        "badge": "formula.utils.badge_callback",
                    },
                    {
                        "title": _("Standings"),
                        "icon": "trophy",
                        "link": reverse_lazy("admin:formula_standing_changelist"),
                        "permission": "formula.utils.permission_callback",
                        # "permission": lambda request: request.user.is_superuser,
                    },
                ],
            },
            {
                "title": _("Users & Groups"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "account_circle",
                        "link": reverse_lazy("admin:formula_user_changelist"),
                    },
                    {
                        "title": _("Groups"),
                        "icon": "group",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                ],
            },
            {
                "title": _("Celery Tasks"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Clocked"),
                        "icon": "hourglass_bottom",
                        "link": reverse_lazy(
                            "admin:django_celery_beat_clockedschedule_changelist"
                        ),
                    },
                    {
                        "title": _("Crontabs"),
                        "icon": "update",
                        "link": reverse_lazy(
                            "admin:django_celery_beat_crontabschedule_changelist"
                        ),
                    },
                    {
                        "title": _("Intervals"),
                        "icon": "timer",
                        "link": reverse_lazy(
                            "admin:django_celery_beat_intervalschedule_changelist"
                        ),
                    },
                    {
                        "title": _("Periodic tasks"),
                        "icon": "task",
                        "link": reverse_lazy(
                            "admin:django_celery_beat_periodictask_changelist"
                        ),
                    },
                    {
                        "title": _("Solar events"),
                        "icon": "event",
                        "link": reverse_lazy(
                            "admin:django_celery_beat_solarschedule_changelist"
                        ),
                    },
                ],
            },
        ],
    },
}

UNFOLD_STUDIO_DEFAULT_FRAGMENT = "color-schemes"

UNFOLD_STUDIO_ENABLE_SAVE = False

UNFOLD_STUDIO_ENABLE_FILEUPLOAD = False

UNFOLD_STUDIO_ALWAYS_OPEN = True

######################################################################
# Money
######################################################################
CURRENCIES = ("USD", "EUR")

######################################################################
# App
######################################################################
LOGIN_USERNAME = environ.get("LOGIN_USERNAME")

LOGIN_PASSWORD = environ.get("LOGIN_PASSWORD")

############################################################################
# Debug toolbar
############################################################################
DEBUG_TOOLBAR_CONFIG = {"SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG}

######################################################################
# Plausible
######################################################################
PLAUSIBLE_DOMAIN = environ.get("PLAUSIBLE_DOMAIN")

######################################################################
# Sentry
######################################################################
SENTRY_DSN = environ.get("SENTRY_DSN")

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        enable_tracing=False,
    )

######################################################################
# Crispy forms
######################################################################
CRISPY_TEMPLATE_PACK = "unfold_crispy"

CRISPY_ALLOWED_TEMPLATE_PACKS = ["unfold_crispy"]



================================================
FILE: formula/signals.py
================================================
from django.conf import settings
from django.db.models.signals import pre_delete, pre_save
from django.dispatch import receiver

from formula.exceptions import ReadonlyException


def prevent_modifications(sender, instance, **kwargs):
    if not settings.DEBUG and sender._meta.db_table != "studio_options":
        raise ReadonlyException(
            "Database is operating in readonly mode. Not possible to save any data."
        )


@receiver(pre_save)
def block_save(sender, instance, **kwargs):
    prevent_modifications(sender, instance, **kwargs)


@receiver(pre_delete)
def block_delete(sender, instance, **kwargs):
    prevent_modifications(sender, instance, **kwargs)



================================================
FILE: formula/sites.py
================================================
from unfold.sites import UnfoldAdminSite

from .forms import LoginForm


class FormulaAdminSite(UnfoldAdminSite):
    login_form = LoginForm


formula_admin_site = FormulaAdminSite()



================================================
FILE: formula/styles.css
================================================
@import "tailwindcss";



================================================
FILE: formula/translation.py
================================================
from modeltranslation.translator import TranslationOptions, register

from formula.models import Circuit


@register(Circuit)
class CircuitTranslation(TranslationOptions):
    fields = ["name"]



================================================
FILE: formula/urls.py
================================================
from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.urls import include, path

from formula.sites import formula_admin_site
from formula.views import HomeView

urlpatterns = (
    [
        path("", HomeView.as_view(), name="home"),
        path("i18n/", include("django.conf.urls.i18n")),
        path("__debug__/", include("debug_toolbar.urls")),
    ]
    + i18n_patterns(
        path("admin/", formula_admin_site.urls),
    )
    + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
)



================================================
FILE: formula/utils.py
================================================
import random

from django.conf import settings
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _


def environment_callback(request):
    if settings.DEBUG:
        return [_("Development"), "primary"]

    return [_("Production"), "primary"]


def badge_callback(request):
    return f"{random.randint(1, 9)}"


def permission_callback(request):
    return True


def driver_link_callback(request):
    return (
        lambda request: str(reverse_lazy("admin:formula_driver_changelist"))
        in request.path
        or request.path == reverse_lazy("admin:formula_driverwithfilters_changelist")
        or request.path == reverse_lazy("admin:crispy_form")
        or request.path == reverse_lazy("admin:crispy_formset")
    )


def driver_list_link_callback(request):
    if request.path == reverse_lazy("admin:formula_driver_changelist"):
        return True

    if str(reverse_lazy("admin:formula_driver_changelist")) in request.path:
        return True

    return False



================================================
FILE: formula/views.py
================================================
import json
import random
from functools import lru_cache

from django.contrib import messages
from django.contrib.humanize.templatetags.humanize import intcomma
from django.forms import modelformset_factory
from django.urls import reverse_lazy
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView, RedirectView
from unfold.views import UnfoldModelAdminViewMixin

from formula.forms import CustomForm, DriverForm, DriverFormHelper, DriverFormSet
from formula.models import Driver


class HomeView(RedirectView):
    pattern_name = "admin:index"


class CrispyFormView(UnfoldModelAdminViewMixin, FormView):
    title = _("Crispy form")  # required: custom page header title
    form_class = CustomForm
    success_url = reverse_lazy("admin:index")
    # required: tuple of permissions
    permission_required = (
        "formula.view_driver",
        "formula.add_driver",
        "formula.change_driver",
        "formula.delete_driver",
    )
    template_name = "formula/driver_crispy_form.html"


class CrispyFormsetView(UnfoldModelAdminViewMixin, FormView):
    title = _("Crispy form with formset")  # required: custom page header title
    success_url = reverse_lazy("admin:crispy_formset")
    # required: tuple of permissions
    permission_required = (
        "formula.view_driver",
        "formula.add_driver",
        "formula.change_driver",
        "formula.delete_driver",
    )
    template_name = "formula/driver_crispy_formset.html"

    def get_form_class(self):
        return modelformset_factory(
            Driver, DriverForm, formset=DriverFormSet, extra=1, can_delete=True
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(
            {
                "queryset": Driver.objects.filter(code__in=["VER", "HAM"]),
            }
        )
        return kwargs

    def form_invalid(self, form):
        messages.error(self.request, _("Formset submitted with errors"))
        return super().form_invalid(form)

    def form_valid(self, form):
        messages.success(self.request, _("Formset submitted successfully"))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context.update(
            {
                "driver_formset_helper": DriverFormHelper(),
            }
        )
        return context


def dashboard_callback(request, context):
    context.update(random_data())
    return context


@lru_cache
def random_data():
    WEEKDAYS = [
        "Mon",
        "Tue",
        "Wed",
        "Thu",
        "Fri",
        "Sat",
        "Sun",
    ]

    positive = [[1, random.randrange(8, 28)] for i in range(1, 28)]
    negative = [[-1, -random.randrange(8, 28)] for i in range(1, 28)]
    average = [r[1] - random.randint(3, 5) for r in positive]
    performance_positive = [[1, random.randrange(8, 28)] for i in range(1, 28)]
    performance_negative = [[-1, -random.randrange(8, 28)] for i in range(1, 28)]

    return {
        "navigation": [
            {"title": _("Dashboard"), "link": "/", "active": True},
            {"title": _("Analytics"), "link": "#"},
            {"title": _("Settings"), "link": "#"},
        ],
        "filters": [
            {"title": _("All"), "link": "#", "active": True},
            {
                "title": _("New"),
                "link": "#",
            },
        ],
        "kpi": [
            {
                "title": "Product A Performance",
                "metric": f"${intcomma(f'{random.uniform(1000, 9999):.02f}')}",
                "footer": mark_safe(
                    f'<strong class="text-green-700 font-semibold dark:text-green-400">+{intcomma(f"{random.uniform(1, 9):.02f}")}%</strong>&nbsp;progress from last week'
                ),
                "chart": json.dumps(
                    {
                        "labels": [WEEKDAYS[day % 7] for day in range(1, 28)],
                        "datasets": [{"data": average, "borderColor": "#9333ea"}],
                    }
                ),
            },
            {
                "title": "Product B Performance",
                "metric": f"${intcomma(f'{random.uniform(1000, 9999):.02f}')}",
                "footer": mark_safe(
                    f'<strong class="text-green-700 font-semibold dark:text-green-400">+{intcomma(f"{random.uniform(1, 9):.02f}")}%</strong>&nbsp;progress from last week'
                ),
            },
            {
                "title": "Product C Performance",
                "metric": f"${intcomma(f'{random.uniform(1000, 9999):.02f}')}",
                "footer": mark_safe(
                    f'<strong class="text-green-700 font-semibold dark:text-green-400">+{intcomma(f"{random.uniform(1, 9):.02f}")}%</strong>&nbsp;progress from last week'
                ),
            },
        ],
        "progress": [
            {
                "title": "Social marketing e-book",
                "description": f"${intcomma(f'{random.uniform(1000, 9999):.02f}')}",
                "value": random.randint(10, 90),
            },
            {
                "title": "Freelancing tasks",
                "description": f"${intcomma(f'{random.uniform(1000, 9999):.02f}')}",
                "value": random.randint(10, 90),
            },
            {
                "title": "Development coaching",
                "description": f"${intcomma(f'{random.uniform(1000, 9999):.02f}')}",
                "value": random.randint(10, 90),
            },
            {
                "title": "Product consulting",
                "description": f"${intcomma(f'{random.uniform(1000, 9999):.02f}')}",
                "value": random.randint(10, 90),
            },
            {
                "title": "Other income",
                "description": f"${intcomma(f'{random.uniform(1000, 9999):.02f}')}",
                "value": random.randint(10, 90),
            },
            {
                "title": "Course sales",
                "description": f"${intcomma(f'{random.uniform(1000, 9999):.02f}')}",
                "value": random.randint(10, 90),
            },
            {
                "title": "Ads revenue",
                "description": f"${intcomma(f'{random.uniform(1000, 9999):.02f}')}",
                "value": random.randint(10, 90),
            },
            {
                "title": "Customer Retention Rate",
                "description": f"${intcomma(f'{random.uniform(1000, 9999):.02f}')}",
                "value": random.randint(10, 90),
            },
        ],
        "chart": json.dumps(
            {
                "labels": [WEEKDAYS[day % 7] for day in range(1, 28)],
                "datasets": [
                    {
                        "label": "Example 1",
                        "type": "line",
                        "data": average,
                        "borderColor": "var(--color-primary-500)",
                    },
                    {
                        "label": "Example 2",
                        "data": positive,
                        "backgroundColor": "var(--color-primary-700)",
                    },
                    {
                        "label": "Example 3",
                        "data": negative,
                        "backgroundColor": "var(--color-primary-300)",
                    },
                ],
            }
        ),
        "performance": [
            {
                "title": _("Last week revenue"),
                "metric": "$1,234.56",
                "footer": mark_safe(
                    '<strong class="text-green-600 font-medium">+3.14%</strong>&nbsp;progress from last week'
                ),
                "chart": json.dumps(
                    {
                        "labels": [WEEKDAYS[day % 7] for day in range(1, 28)],
                        "datasets": [
                            {
                                "data": performance_positive,
                                "borderColor": "var(--color-primary-700)",
                            }
                        ],
                    }
                ),
            },
            {
                "title": _("Last week expenses"),
                "metric": "$1,234.56",
                "footer": mark_safe(
                    '<strong class="text-green-600 font-medium">+3.14%</strong>&nbsp;progress from last week'
                ),
                "chart": json.dumps(
                    {
                        "labels": [WEEKDAYS[day % 7] for day in range(1, 28)],
                        "datasets": [
                            {
                                "data": performance_negative,
                                "borderColor": "var(--color-primary-300)",
                            }
                        ],
                    }
                ),
            },
        ],
        "table_data": {
            "headers": [_("Day"), _("Income"), _("Expenses")],
            "rows": [
                ["22-10-2025", "$2,341.89", "$1,876.45"],
                ["23-10-2025", "$1,987.23", "$2,109.67"],
                ["24-10-2025", "$3,456.78", "$1,543.21"],
                ["25-10-2025", "$1,765.43", "$2,987.65"],
                ["26-10-2025", "$2,876.54", "$1,234.56"],
                ["27-10-2025", "$1,543.21", "$2,765.43"],
                ["28-10-2025", "$3,210.98", "$1,987.65"],
            ],
        },
    }



================================================
FILE: formula/wsgi.py
================================================
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "formula.settings")

application = get_wsgi_application()



================================================
FILE: formula/fixtures/0001_users.json
================================================
[
  {
    "model": "formula.user",
    "pk": 1,
    "fields": {
      "password": "pbkdf2_sha256$600000$lDFsnIkq4q8f1z98UjxI6o$vDnxj2Fp1xdl/ECFPvn1PU0vTmI1h8+SOVf//1HSaTI=",
      "last_login": "2012-12-12T12:00:00.000Z",
      "is_superuser": true,
      "username": "demo",
      "first_name": "Sample",
      "last_name": "Example",
      "email": "sample@example.com",
      "is_staff": true,
      "is_active": true,
      "date_joined": "2012-12-12T12:00:00.000Z",
      "biography": "",
      "created_at": "2012-12-12T12:00:00.000Z",
      "modified_at": "2012-12-12T12:00:00.000Z",
      "groups": [],
      "user_permissions": []
    }
  }
]



