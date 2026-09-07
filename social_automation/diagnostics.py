from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from .ai_usage_policy import (
    COMPOSITION_OPERATIONS,
    REVIEW_OPERATIONS,
    VISUAL_QUOTA_OPERATIONS,
    ai_usage_policy,
)
from .health import _effective_ai_limit
from .models import SocialAIUsage, SocialCarouselGenerationRun, SocialCarouselSlide, SocialContent, SocialProfile
from .scheduler import _content_reserves_stock


AI_FINISHED_ACTIVE_RUN_STATUSES = {
    SocialCarouselGenerationRun.Status.IDEATING,
    SocialCarouselGenerationRun.Status.IDEA_SELECTED,
    SocialCarouselGenerationRun.Status.BLUEPRINT_READY,
    SocialCarouselGenerationRun.Status.EDITORIAL_APPROVED,
    SocialCarouselGenerationRun.Status.COMPOSING,
    SocialCarouselGenerationRun.Status.REVIEWING,
    SocialCarouselGenerationRun.Status.PARTIAL,
}


def find_social_profile(*, username='', profile_id=None):
    queryset = SocialProfile.objects.all()
    if profile_id:
        return queryset.get(pk=profile_id)
    normalized = username.strip()
    alternatives = {normalized}
    if normalized.startswith('@'):
        alternatives.add(normalized[1:])
    elif normalized:
        alternatives.add(f'@{normalized}')
    return queryset.get(username__in=alternatives)


def profile_timezone(profile):
    try:
        return ZoneInfo(profile.timezone)
    except ZoneInfoNotFoundError:
        return timezone.get_current_timezone()


def usage_window(profile, target_date):
    zone = profile_timezone(profile)
    local_start = datetime.combine(target_date, time.min, tzinfo=zone)
    local_end = local_start + timedelta(days=1)
    return local_start, local_end, local_start.astimezone(datetime_timezone.utc), local_end.astimezone(datetime_timezone.utc)


def configured_ai_limit(profile):
    profile_limit = profile.ai_image_daily_limit or getattr(settings, 'SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY', 0)
    global_limit = getattr(settings, 'SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY', profile_limit)
    source = 'profile.ai_image_daily_limit'
    if not profile.ai_image_daily_limit:
        source = 'settings.SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY'
    if global_limit and profile_limit > global_limit:
        source = f'{source} limitado por settings.SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY'
    return profile_limit, _effective_ai_limit(profile), source


def audit_ai_usage(profile, target_date=None):
    target_date = target_date or timezone.localdate(timezone.now(), profile_timezone(profile))
    local_start, local_end, start_utc, end_utc = usage_window(profile, target_date)
    usages = list(
        SocialAIUsage.objects.filter(profile=profile, created_at__gte=start_utc, created_at__lt=end_utc)
        .select_related('content', 'slide', 'base_image')
        .order_by('created_at', 'id')
    )
    rows = {}
    operation_counts = Counter()
    for usage in usages:
        metadata = usage.metadata or {}
        purpose = metadata.get('purpose') or metadata.get('stage') or usage.operation
        key = (usage.operation, purpose)
        row = rows.setdefault(
            key,
            {
                'operation': usage.operation,
                'purpose': purpose,
                'count': 0,
                'successful': 0,
                'failed': 0,
                'provider_called': 0,
                'content_ids': set(),
                'carousel_content_ids': set(),
                'slide_ids': set(),
                'quota': usage.operation in VISUAL_QUOTA_OPERATIONS,
                'composition': usage.operation in COMPOSITION_OPERATIONS,
                'review': usage.operation in REVIEW_OPERATIONS,
                'health': True,
            },
        )
        row['count'] += 1
        row['successful'] += 1 if usage.success else 0
        row['failed'] += 0 if usage.success else 1
        row['provider_called'] += 1 if metadata.get('provider_called') or usage.success else 0
        if usage.content_id:
            row['content_ids'].add(usage.content_id)
            if usage.content and usage.content.media_type == SocialContent.MediaType.CAROUSEL:
                row['carousel_content_ids'].add(usage.content_id)
        if usage.slide_id:
            row['slide_ids'].add(usage.slide_id)
        if usage.success:
            operation_counts[usage.operation] += 1

    breakdown = []
    for row in rows.values():
        item = row.copy()
        item['content_count'] = len(row['content_ids'])
        item['carousel_count'] = len(row['carousel_content_ids'])
        item['slide_count'] = len(row['slide_ids'])
        del item['content_ids']
        del item['carousel_content_ids']
        del item['slide_ids']
        breakdown.append(item)
    breakdown.sort(key=lambda item: (item['operation'], item['purpose']))

    configured_limit, effective_limit, source = configured_ai_limit(profile)
    health_total = sum(operation_counts.values())
    quota_relevant_success = sum(operation_counts[operation] for operation in VISUAL_QUOTA_OPERATIONS)
    provider_image_composition = sum(
        row['provider_called']
        for row in breakdown
        if row['operation'] in VISUAL_QUOTA_OPERATIONS
    )
    return {
        'profile': profile,
        'date': target_date,
        'timezone': profile.timezone,
        'local_start': local_start,
        'local_end': local_end,
        'start_utc': start_utc,
        'end_utc': end_utc,
        'configured_limit': configured_limit,
        'effective_limit': effective_limit,
        'limit_source': source,
        'health_total': health_total,
        'quota_relevant_success': quota_relevant_success,
        'provider_image_composition_calls': provider_image_composition,
        'operation_counts': dict(operation_counts),
        'breakdown': breakdown,
        'policies': [ai_usage_policy(operation) for operation, _label in SocialAIUsage.Operation.choices],
    }


def slide_status_counts(content):
    rows = (
        content.carousel_slides.filter(is_active=True)
        .values('ai_composition_status')
        .annotate(total=Count('id'))
    )
    counts = defaultdict(int)
    for row in rows:
        counts[row['ai_composition_status']] = row['total']
    return counts


def content_asset_count(content):
    total = 0
    if content.final_image:
        total += 1
    if content.final_video:
        total += 1
    for slide in content.carousel_slides.all():
        total += 1 if slide.source_image else 0
        total += 1 if slide.rendered_image else 0
        total += 1 if slide.ai_composed_image else 0
    return total


def audit_ai_finished(profile, *, now=None):
    now = now or timezone.now()
    all_runs = list(
        SocialCarouselGenerationRun.objects.filter(
            profile=profile,
            generation_mode=SocialProfile.CarouselGenerationMode.AI_FINISHED,
        )
        .select_related('content')
        .order_by('content_id', '-started_at', '-id')
    )
    reserved_contents = [
        content
        for content in (
            profile.contents.filter(media_type=SocialContent.MediaType.CAROUSEL)
            .prefetch_related('carousel_slides', 'carousel_generation_runs')
            .order_by('id')
        )
        if _content_reserves_stock(content, now=now)
    ]
    runs_by_content = defaultdict(list)
    for run in all_runs:
        if run.content_id:
            runs_by_content[run.content_id].append(run)

    operational_run_ids = set()
    content_rows = []
    duplicate_active_runs = 0
    for content in reserved_contents:
        runs = runs_by_content.get(content.id, [])
        latest = runs[0] if runs else None
        if latest and latest.status in AI_FINISHED_ACTIVE_RUN_STATUSES:
            operational_run_ids.add(latest.id)
        active_for_content = [run for run in runs if run.status in AI_FINISHED_ACTIVE_RUN_STATUSES and run.finished_at is None]
        if len(active_for_content) > 1:
            duplicate_active_runs += len(active_for_content) - 1
        slide_counts = slide_status_counts(content)
        content_rows.append(
            {
                'content': content,
                'runs': len(runs),
                'latest_run': latest,
                'latest_status': latest.status if latest else '-',
                'ready': slide_counts[SocialCarouselSlide.CompositionStatus.READY],
                'pending': (
                    slide_counts[SocialCarouselSlide.CompositionStatus.PENDING]
                    + slide_counts[SocialCarouselSlide.CompositionStatus.COMPOSING]
                    + slide_counts[SocialCarouselSlide.CompositionStatus.REVIEWING]
                    + slide_counts[SocialCarouselSlide.CompositionStatus.NEEDS_RECOMPOSE]
                ),
                'assets': content_asset_count(content),
            }
        )

    partial_runs = [run for run in all_runs if run.status == SocialCarouselGenerationRun.Status.PARTIAL]
    operational_partial_runs = [run for run in partial_runs if run.id in operational_run_ids]
    historical_partial_runs = [run for run in partial_runs if run.id not in operational_run_ids]
    status_counts = Counter(run.status for run in all_runs)
    slide_counts_global = Counter()
    for row in content_rows:
        slide_counts_global[SocialCarouselSlide.CompositionStatus.READY] += row['ready']
        slide_counts_global['PENDING_TOTAL'] += row['pending']

    return {
        'profile': profile,
        'reserved_contents': reserved_contents,
        'reserved_count': len(reserved_contents),
        'runs_total': len(all_runs),
        'run_status_counts': dict(status_counts),
        'partial_runs_total': len(partial_runs),
        'operational_partial_runs': len(operational_partial_runs),
        'historical_partial_runs': len(historical_partial_runs),
        'duplicate_active_runs': duplicate_active_runs,
        'content_rows': content_rows,
        'slide_counts': dict(slide_counts_global),
    }
