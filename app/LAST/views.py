import os
import re
import time

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import Http404
from django.conf import settings
from datetime import datetime,timedelta
from .utils import plot_fields,get_sunset_sunrise

# The live night's plot keeps changing as observations come in; regenerate it at most
# this often. Past nights are immutable and served straight from the cached PNG.
CURRENT_NIGHT_MAX_AGE = 300  # seconds


def _current_observing_night():
    """Return the current observing night as 'YYYY-MM-DD' (previous day before sunset)."""
    now = datetime.utcnow()
    try:
        sunset, _ = get_sunset_sunrise(now.strftime('%Y-%m-%d'))
        if now < sunset:
            now -= timedelta(days=1)
    except Exception:
        pass
    return now.strftime('%Y-%m-%d')


@login_required
def observed_fields_plot_view(request, night=None):
    # Allow ?night=YYYY-MM-DD to override the path variable
    night = request.GET.get('night') or night
    if night is not None and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(night)):
        raise Http404("Invalid night format (expected YYYY-MM-DD).")
    current_night = _current_observing_night()
    if night is None:
        night = current_night

    # Prepare file paths
    filename = f"{night}.png"
    plot_file = os.path.join(settings.MEDIA_ROOT, "LAST", "plots", filename)

    # Only (re)generate when needed: the PNG is missing, or it's the current/future
    # night whose data is still changing (throttled). Past nights are served from cache
    # — no ClickHouse queries, no matplotlib render.
    needs_regen = not os.path.exists(plot_file)
    if not needs_regen and night >= current_night:
        needs_regen = (time.time() - os.path.getmtime(plot_file)) > CURRENT_NIGHT_MAX_AGE

    if needs_regen:
        try:
            plot_fields(date_str=night)
        except Exception as e:
            # If a cached plot exists, serve it rather than 404 (e.g. ClickHouse down).
            if not os.path.exists(plot_file):
                raise Http404(f"Failed to generate plot: {str(e)}")

    night_date = datetime.strptime(night, '%Y-%m-%d').date()
    context = {
        'plot_url': f"{settings.MEDIA_URL}LAST/plots/{filename}",
        'night': night,
        'prev_night': (night_date - timedelta(days=1)).isoformat(),
        'next_night': (night_date + timedelta(days=1)).isoformat(),
    }
    return render(request, 'observed_fields_plot.html', context)
