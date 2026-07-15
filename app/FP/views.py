# Third-party imports
import pandas as pd
import plotly.graph_objs as go
import plotly.offline as opy
from astropy.time import Time

# Django imports
from django.shortcuts import render
from django.http import HttpResponse

# Local imports
from .utils import submit_fp_request, get_results_from_request_id, get_query_status


def force_photometry_view(request):
    """
    Render the forced-photometry form. Fetch/Check only *establish* a request_id; the
    results are loaded asynchronously by fp_result_fragment (HTMX polling), so the
    request never blocks a worker waiting on the external service.
    """
    context = {}

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'fetch':
                ra = float(request.POST.get('ra'))
                dec = float(request.POST.get('dec'))
                fieldid = request.POST.get('fieldid')
                cropid = request.POST.get('cropid')
                mountnum = request.POST.get('mountnum')
                camnum = request.POST.get('camnum')
                days = request.POST.get('days')
                max_results = request.POST.get('max_results')
                use_existing_ref = 'use_existing_ref' in request.POST
                resub = 'resub' in request.POST
                loadnew = 'loadnew' in request.POST
                start_date_str = request.POST.get('start_date')
                end_date_str = request.POST.get('end_date')

                if start_date_str and end_date_str:
                    jd_start = Time(start_date_str, format='iso').jd
                    jd_end = Time(end_date_str, format='iso').jd
                else:
                    if not days:
                        context['error'] = 'You have to either specify a number of days or a start and end date.'
                        return render(request, 'forced_photometry.html', context)
                    jd_end = Time.now().jd
                    jd_start = jd_end - int(days)

                fieldid = fieldid if fieldid else "''"
                cropid = int(cropid) if cropid else 0
                mountnum = int(mountnum) if mountnum else 0
                camnum = int(camnum) if camnum else 0

                request_id = submit_fp_request(
                    ra, dec, jd_start, jd_end,
                    fieldid, cropid, mountnum, camnum,
                    max_results, use_existing_ref, resub, loadnew,
                )
                context['request_id'] = request_id

            elif action == 'check':
                requestid = request.POST.get('requestid')
                if requestid:
                    context['request_id'] = int(requestid)
        except Exception as e:
            context['error'] = f"Error: {e}"

    return render(request, 'forced_photometry.html', context)


def fp_result_fragment(request, request_id):
    """
    HTMX-polled fragment: report a forced-photometry request's status and, once ready,
    render its light curve. While pending it returns a self-repolling fragment; when
    terminal it returns the final content (which stops the polling).
    """
    context = {'request_id': request_id}
    try:
        status = get_query_status(request_id)
        if status is None:
            context['error'] = f'No such request ID: {request_id}'
        elif status == 1:  # OK
            detections, nondetections, fp_results = get_results_from_request_id(request_id)
            if fp_results is None:
                context['error'] = "No data returned for the given parameters."
            else:
                request.session['fp_results'] = fp_results.to_dict(orient='records')
                context['csv_available'] = True
                context['plot_div'] = _build_fp_plot_div(detections, nondetections, request_id)
        elif status == 2:  # Failed / no results
            context['error'] = "No data returned for the given parameters."
        elif status == 10:  # Error
            context['error'] = "Error processing query. Data might be missing, try with different parameters."
        else:  # 0 = pending (or any not-yet-terminal status)
            context['pending'] = True
    except Exception as e:
        context['error'] = f"Error: {e}"

    return render(request, 'FP/_fp_result.html', context)


def _build_fp_plot_div(detections, nondetections, request_id):
    jd_now = Time.now().jd
    det_trace = go.Scatter(
        x=jd_now - detections['jd'], y=detections['mag_psf'],
        mode='markers', name='Detections',
        error_y=dict(type='data', array=1.0857 / detections['sn'], visible=True),
    )
    nondet_trace = go.Scatter(
        x=jd_now - nondetections['jd'], y=nondetections['limmag'],
        mode='markers', name='Non-detections',
        marker=dict(symbol='triangle-down', size=8), yaxis='y',
    )
    layout = go.Layout(
        title=f'LAST photometry from request_id={request_id}',
        xaxis=dict(title='Days ago', autorange='reversed'),
        yaxis=dict(title='Apparent Magnitude', autorange='reversed'),
    )
    fig = go.Figure(data=[det_trace, nondet_trace], layout=layout)
    # plotly.js is loaded once at page level (forced_photometry.html); don't re-embed it.
    return opy.plot(fig, auto_open=False, output_type='div', include_plotlyjs=False)


def download_fp_csv(request):
    data = request.session.get('fp_results')
    if not data:
        return HttpResponse("No results to download.", status=400)

    df = pd.DataFrame(data)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="forced_photometry.csv"'
    df.to_csv(path_or_buf=response, index=False)
    return response
