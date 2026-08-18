FROM python:3.12-slim

# Calibre from Debian's own apt repo, not upstream's curl|sh installer --
# reproducible and apt-pinned, and doesn't require piping a remote script
# into a root shell during image build. Trade-off: Debian's packaged
# version lags upstream Calibre releases by a while; acceptable here
# since we only ever use one CLI tool out of the whole suite
# (`ebook-convert`) for one well-established, format-stable conversion,
# not anything that needs bleeding-edge Calibre.
RUN apt-get update && apt-get install -y --no-install-recommends calibre \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 converter

WORKDIR /app
COPY calibre_converter/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY calibre_converter/app.py ./

# Calibre's conversion tools assume a display is available by default;
# this tells Qt to render offscreen instead, so ebook-convert works
# headless without needing a bundled Xvfb. If this ever turns out not to
# be sufficient on some future Calibre/Qt version, the fallback is
# wrapping the CMD below in `xvfb-run`.
ENV QT_QPA_PLATFORM=offscreen

USER converter
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
