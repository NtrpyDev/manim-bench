FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libcairo2 \
    libcairo2-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpango1.0-dev \
    pkg-config \
    texlive \
    texlive-latex-extra \
    texlive-fonts-extra \
    dvisvgm \
  && rm -rf /var/lib/apt/lists/*

RUN python -m pip install "manim>=0.20,<0.21"

RUN useradd --create-home --shell /usr/sbin/nologin manimbench
USER manimbench
WORKDIR /work

ENTRYPOINT []
