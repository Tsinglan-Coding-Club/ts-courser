from django import forms

from courses.models import Section


class SectionForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ['title', 'emoji']
