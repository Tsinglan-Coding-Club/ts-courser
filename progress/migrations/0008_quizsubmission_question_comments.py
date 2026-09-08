from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('progress', '0007_codesubmissionhistory')]

    operations = [
        migrations.AddField(
            model_name='quizsubmission',
            name='question_comments',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='Teacher comments keyed by question index, released with quiz results',
            ),
        ),
    ]
