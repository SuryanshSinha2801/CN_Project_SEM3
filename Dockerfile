FROM python:3.13-slim

LABEL org.opencontainers.image.title="BLACKOUT Network Simulator"
LABEL org.opencontainers.image.description="Python 3.13 DTN routing simulator and test environment"
LABEL org.opencontainers.image.source="https://github.com/SuryanshSinha2801/CN_Project_SEM3"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements-container.txt ./
RUN python -m pip install --requirement requirements-container.txt

RUN addgroup --system blackout \
    && adduser --system --ingroup blackout --home /home/blackout blackout \
    && mkdir --parents /app/results \
    && chown --recursive blackout:blackout /app /home/blackout

COPY --chown=blackout:blackout pyproject.toml README.md ./
COPY --chown=blackout:blackout blackout ./blackout
COPY --chown=blackout:blackout configs ./configs
COPY --chown=blackout:blackout tests ./tests

USER blackout

# Build only succeeds when the container-compatible suite passes. Tkinter's
# desktop rendering test is host-only because this image has no display server.
RUN python -m pytest --quiet --ignore=tests/test_gui.py

ENTRYPOINT ["python", "-m", "blackout"]
CMD ["validate", "configs/presentation.yaml"]
