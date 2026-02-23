from django.http import HttpResponse, JsonResponse, HttpResponseNotFound
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import permission_required, login_required
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from django.core.validators import validate_slug
from django.template import RequestContext

from osm_wrapper.validators.validators import validate_shape


from geotiff import GeoTiff
from json import loads
from osm_wrapper.utils.line_index_finder import LineIndexFinder
from osm_wrapper.utils.namespaced_redis import redis_client, get_redis_connection
from osm_wrapper.utils.functional import key_setter

import math
import redis
import json

# A rectangle encompassing Italy, provided as default if no work region was initialized.
DEFAULTS_LAT1 = 47.0929158064116
DEFAULTS_LON1 = 6.616648588864537
DEFAULTS_LAT2 = 36.64423050629097
DEFAULTS_LON2 = 18.52144877044298

@login_required
def get_map(request):
    return render(request, "osm_wrapper/map.html", RequestContext(request).push({
        "title": "GIS demo"
    }))

@login_required
@require_GET
def get_box(request):
    r = get_redis_connection()
    data = {
        'lat1': r.get('lat1') or DEFAULTS_LAT1,
        'lon1': r.get('lon1') or DEFAULTS_LON1,
        'lat2': r.get('lat2') or DEFAULTS_LAT2,
        'lon2': r.get('lon2') or DEFAULTS_LON2,
    }
    return JsonResponse(data)

@login_required
@require_GET
def get_spots(request):
    r = redis_client(request.user)
    if r.zcount("spots", "-inf", "inf") == 0:
        return JsonResponse({"items": ()})
    data = r.geosearch("spots", longitude=r.get('lon1'), latitude=r.get('lat1'), width=50, height=50, unit="km", withcoord=True)
    res = [{"elem": elem, "coords": coords} for (elem, coords,) in data]
    res = list(map(key_setter('altitude', lambda x: r.zscore('altitudes', x['elem'])), res))
    return JsonResponse({"items": res})

@login_required
@require_GET
def get_approach(request):
    r = redis_client(request.user)
    if r.zcount("approach_paths", "-inf", "inf") == 0:
        return JsonResponse({"items": ()})
    data = r.geosearch("approach_paths", longitude=r.get('lon1'), latitude=r.get('lat1'), width=50, height=50, unit="km", withcoord=True)
    res = [{"elem": elem, "coords": coords} for (elem, coords,) in data]
    return JsonResponse({"items": res})

"""
Populate the "spots" key namespace in redis.
That's what will be then shown on the /map route via the /get-spots AJAX route.
box_size and distance act in opposing fashion: box_size is the maximum distance considered, distance is the minimum.
@todo add a redis lock that prevents multiple runs of the function.
"""
@require_POST
def populate_spots(request):
    # @todo validate values after keys
    strategy_shp = {
        "slope": None,
        "box_size": None,
        "count": None,
        "distance": None,
        "peak": None,
    }
    body = json.loads(request.body.decode('utf-8'))

    validate_shape(body, strategy_shp)
    strategy = body

    r = redis_client(request.user)
    r.zremrangebyscore("spots", "-inf", "inf")

    # @todo: query the locations set for the amount of keys in it, so we can divide that number by 10 for the zscan
    i, altitudes = r.zscan("altitudes", 0)
    while i != 0:
        for ind, altitude in altitudes:
            aggregated_slope = 0
            count = 0
            # that's lazy and slow, could access the adjacent elements by key
            around = r.geosearch("locations", member=ind, width=strategy["box_size"], height=strategy["box_size"], unit="m", withdist=True)
            for elem, distance in around:
                if distance < strategy["distance"]:
                    continue
                other_altitude = r.zscore("altitudes", elem)
                if other_altitude > altitude:
                    if strategy["peak"]:
                        count = 0
                        break
                    continue
                if altitude < other_altitude + (strategy["slope"] * distance):
                    continue
                count +=1
                aggregated_slope += (altitude - other_altitude) / distance
            if count < strategy["count"]:
                continue
            slope = aggregated_slope / count
            if slope > strategy["slope"] :
                position = r.geopos('locations', ind)[0]
                label = ind
                r.geoadd("spots", position + (label,))

        i, altitudes = r.zscan("altitudes", i)
    return JsonResponse({})


@require_POST
def populate_approach(request):
    # @todo validate values after keys
    strategy_shp = {
        "slope": None,
        "box_size": None,
        "count": None,
    }
    body = json.loads(request.body.decode('utf-8'))

    validate_shape(body, strategy_shp)
    strategy = body

    r = redis_client(request.user)
    r.zremrangebyscore("approach_paths", "-inf", "inf")
    i, altitudes = r.zscan("altitudes", 0)
    while i != 0:
        for ind, altitude in altitudes:
            count = 0
            # that's lazy and slow, could access the adjacent elements by key
            around = r.geosearch("locations", member=ind, width=strategy["box_size"], height=strategy["box_size"],
                                 unit="m", withdist=True)
            for elem, distance in around:
                other_altitude = r.zscore("altitudes", elem)
                if other_altitude > altitude:
                    continue
                if altitude > other_altitude + (strategy["slope"] * distance):
                    continue
                count += 1
            if count < strategy["count"]:
                continue
            position = r.geopos('locations', ind)[0]
            label = ind
            r.geoadd("approach_paths", position + (label,))
        i, altitudes = r.zscan("altitudes", i)
    return JsonResponse({})
"""
Given a spot index, query all spots in a 600 meters range to find if there are any other spots that could form a line.
"""
@login_required
@require_GET
def find_lines(request):
    shp = {
        'ind': None,
    }
    validate_shape(request.GET, shp)
    ind_str = request.GET["ind"]
    lines = []
    ind = ind_str.split(" ")[0]

    r = redis_client(request.user)
    altitude = r.zscore("altitudes", ind)
    around = r.geosearch("spots", member=ind, radius=600, unit="m", withdist=True)
    for other_str, distance in around:
        if distance < 40:
            continue
        other = other_str.split(" ")[0]
        other_altitude = r.zscore("altitudes", other)
        height_diff = other_altitude - altitude
        angle = math.atan(height_diff / distance)
        min_altitude = min(altitude, other_altitude)
        # are A and B in bubble?
        heights = []
        if -0.047 < angle < 0.047:
            # This returns an iterator with all the indexes between A and B
            iterator = LineIndexFinder(ind, other)
            i = 1
            current = iterator.getNth(0)
            aggregated_heights = 0
            highest_found = 0
            while current is not None:
                current = iterator.getNth(i)
                if current is None: continue
                i = i + 1
                intermediate_altitude = r.zscore("altitudes", current)
                aggregated_heights += intermediate_altitude
                heights.append(intermediate_altitude)
                highest_found = max(highest_found, intermediate_altitude)
            # @todo  That's ugly, need to fix LineIndexFinder (returns the starting point as well and it's unintended)
            average_inbetween = aggregated_heights / (i - 1)
            average_height = min_altitude - average_inbetween
            height_distance_ratio = average_height / distance
            # @todo a very bad safeguarding to avoid obstacles between lines (it's not easy with 10m steps)
            if highest_found > min_altitude + 30:
                continue
            if height_distance_ratio < .5:
                continue
            lines.append({
                "points": r.geopos("spots", ind, other),
                "angle": angle,
                "average_height": average_height,
                "min": min_altitude,
                "distance": distance,
            })
    return JsonResponse({"lines": lines})

"""
@todo This should be an admin route probably. It calls redis' FLUSHALL.
"""
#@login_required
@require_POST
@csrf_exempt
def init(request):
    shp = {
        'filename': None,
    }
    data = loads(request.body or "{}")
    validate_shape(data, shp)
    # Avoid arbitrary paths, just
    validate_slug(data['filename'])
    r = get_redis_connection()
    r.flushall()
    pipeline = r.pipeline()
    img = GeoTiff('data-sources/source-%s.tif' % data['filename'],  crs_code=32632, as_crs=4326)
    area_box = [(data['lon1'], data['lat1']), (data['lon2'], data['lat2'])]
    ((start_y, start_x), (end_y, end_x)) = img.get_int_box(area_box)
    altitude_data = img.read()

    for i in range(start_x, end_x):
        for j in range(start_y, end_y):
            key_name = "index_%s_%s" % (i, j)
            coords = img.get_wgs_84_coords(j + 1, i + 1) + (key_name,)
            altitudes = {key_name: float(altitude_data[i][j])}
            pipeline.geoadd("locations", coords)
            pipeline.zadd("altitudes", altitudes)
        pipeline.execute()
    r.set('lat1', data['lat1'])
    r.set('lon1', data['lon1'])
    r.set('lat2', data['lat2'])
    r.set('lon2', data['lon2'])
    return JsonResponse({})
