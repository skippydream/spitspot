from django.core.exceptions import ValidationError
import redis
from osm_wrapper.utils.namespaced_redis import get_redis_connection

def validate_challenge(challenge_id, challenge_result):
    r = get_redis_connection()
    expected = r.get("challenge_%d" % int(challenge_id),)
    if challenge_result != expected:
        raise ValidationError("Captcha non valido")

def validate_eq(a, b, msg="I valori non coincidono"):
    if a != b:
        raise ValidationError(msg)

def validate_shape(struct, shp):
    for k in shp.keys():
        if k not in struct:
            raise ValidationError("Manca il campo %s" % (k,))