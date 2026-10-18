from .geo import haversine_m, resolve_landmark
from .hours import open_status

def search(query, lat, lon, radius_m=2000, categories=None, top_k=15):
    from .retriever import search as retrieve
    return retrieve(query, lat, lon, radius_m, categories, top_k)
