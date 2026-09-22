FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
       fonts-dejavu-core libpango-1.0-0 libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --no-create-home --uid 65532 --shell /usr/sbin/nologin renderer
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --requirement /tmp/requirements.txt \
    && rm /tmp/requirements.txt
COPY --chmod=0555 render.py /opt/render.py
USER 65532:65532
ENTRYPOINT ["python", "-I", "-B", "/opt/render.py"]
