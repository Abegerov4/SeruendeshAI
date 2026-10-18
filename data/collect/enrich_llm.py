"""Conservative generated descriptions: only a category paraphrase, no invented amenities.

Templates authored by an LLM and explicitly labelled llm_generated. No API key
or per-record external generation is needed for this deliberately limited fallback.
"""
LABELS = {'cafe': 'кафе', 'restaurant': 'ресторан', 'bar': 'бар', 'nightlife': 'ночное заведение',
          'museum': 'музей', 'gallery': 'галерея', 'theatre': 'театр', 'cinema': 'кинотеатр',
          'park': 'парк или сад', 'viewpoint': 'смотровая площадка', 'monument': 'памятник',
          'attraction': 'достопримечательность', 'playground': 'детская площадка', 'mall': 'торговый центр',
          'library': 'библиотека', 'coworking': 'коворкинг', 'sport': 'спортивный центр', 'other': 'место'}

def description(poi):
    return f'«{poi["name"]}» — {LABELS[poi["category"]]} в Астане (по категории OpenStreetMap).'
