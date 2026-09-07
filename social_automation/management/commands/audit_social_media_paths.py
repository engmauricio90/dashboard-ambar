from collections import Counter

from django.core.management.base import BaseCommand
from django.db.models import ImageField, FileField

from social_automation.media_paths import classify_social_media_path
from social_automation.models import (
    SocialBaseImage,
    SocialCarouselSlide,
    SocialCarouselTemplate,
    SocialContent,
    SocialCreativeReference,
    SocialVisualIdentity,
)


MODEL_SPECS = [
    (SocialBaseImage, 'profile_id', 'profile_id'),
    (SocialVisualIdentity, 'profile_id', 'profile_id'),
    (SocialCarouselTemplate, 'profile_id', 'profile_id'),
    (SocialContent, 'profile_id', 'profile_id'),
    (SocialCarouselSlide, 'content__profile_id', 'content__profile_id'),
    (SocialCreativeReference, 'profile_id', 'profile_id'),
]


class Command(BaseCommand):
    help = 'Audita paths de midia da automacao social sem mover, apagar ou reescrever arquivos.'

    def add_arguments(self, parser):
        parser.add_argument('--details', action='store_true', help='Mostra registros classificados como nao canonicos.')

    def handle(self, *args, **options):
        counters = Counter(
            {
                'canonical': 0,
                'duplicated_prefix': 0,
                'absolute': 0,
                'missing': 0,
                'cross_profile_suspect': 0,
                'other_invalid': 0,
            }
        )
        details = []

        for model, profile_lookup, profile_key in MODEL_SPECS:
            file_fields = [
                field
                for field in model._meta.fields
                if isinstance(field, (FileField, ImageField))
            ]
            if not file_fields:
                continue
            values = ['id', profile_lookup, *[field.name for field in file_fields]]
            queryset = model.objects.values(*values)
            for row in queryset.iterator():
                expected_profile_id = row.get(profile_key)
                for field in file_fields:
                    stored_name = row.get(field.name) or ''
                    if not stored_name:
                        continue
                    classification = classify_social_media_path(stored_name, expected_profile_id=expected_profile_id)
                    if classification == 'canonical':
                        try:
                            if not field.storage.exists(stored_name):
                                classification = 'missing'
                        except Exception:
                            classification = 'missing'
                    counters[classification] += 1
                    if classification != 'canonical':
                        details.append((model.__name__, row['id'], field.name, classification, stored_name))

        for key in ['canonical', 'duplicated_prefix', 'absolute', 'missing', 'cross_profile_suspect', 'other_invalid']:
            self.stdout.write(f'{key} = {counters[key]}')

        if options['details']:
            for model_name, pk, field_name, classification, stored_name in details:
                self.stdout.write(f'{model_name} id={pk} field={field_name} classification={classification} stored_name={stored_name}')
