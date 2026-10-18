# Synthetic fixtures

`pois_sample.json`, `request_walk.json` and `response_walk.json` are deliberately invented QA data. They do not describe real venues and must not be used as the product dataset, relevance labels, or demo evidence. `test:*` IDs and `example.com` URLs make this explicit. Coordinates are chosen to make independent distance/time checks possible.

The reference park is 0.001 degrees latitude north of the request location: approximately 111.2 m. The reference response says 111 m, two minutes walking and a 15-20 minute visit within a 60 minute budget. No real user's location or personal data is included.
