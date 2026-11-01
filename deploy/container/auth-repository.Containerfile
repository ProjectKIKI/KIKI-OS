# Build from a pinned, known working authenticated-front-door image.
# Context contains only ki2ci_auth.py and ki2repository-public.json.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY ki2ci_auth.py ki2repository-public.json /app/
