FROM nikolaik/python-nodejs:python3.13-nodejs24 AS base

ENV UV_LINK_MODE=copy \
  UV_COMPILE_BYTECODE=1 \
  UV_PYTHON_DOWNLOADS=never \
  UV_NO_SYNC=1

ENV PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.9.15 /uv /uvx /bin/

#install dependencies needed for R-builder, but install the remaining dependencies in the trompa-align stage
RUN apt-get update \
    && apt-get -y install tzdata wget git unzip make r-base \
    libharfbuzz-dev libfribidi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir /code
WORKDIR /code

FROM base AS r-builder

COPY ./install-packages.R /code
RUN Rscript /code/install-packages.R

FROM base AS trompa-align

RUN apt-get update \
    && apt-get -y install ffmpeg fluidsynth fluid-soundfont-gm \
    fluid-soundfont-gs less \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir /usr/share/soundfonts
RUN ln -s /usr/share/sounds/sf2/FluidR3_GM.sf2 /usr/share/soundfonts/default.sf2

#download smat
RUN mkdir -p /smat
RUN wget https://midialignment.github.io/AlignmentTool_v190813.zip -O /smat/smat.zip
RUN unzip /smat/smat.zip -d /smat \
    && cd /smat/AlignmentTool_v190813 \
    && ./compile.sh \
    && mv Programs/* /usr/local/bin

COPY pyproject.toml uv.lock /code/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --group prod

ENV PATH="/code/.venv/bin:$PATH"

COPY --from=r-builder /usr/local/lib/R /usr/local/lib/R
COPY . /code

FROM nikolaik/python-nodejs:python3.13-nodejs24 AS clara-builder

WORKDIR /clara-build
ARG CLARA_BRANCH=main
RUN git clone -b $CLARA_BRANCH https://github.com/trompamusic/clara.git
WORKDIR /clara-build/clara
RUN --mount=type=cache,target=/root/.npm npm ci
RUN --mount=type=cache,target=/root/.npm npm run build

FROM trompa-align AS production

COPY --from=clara-builder /clara-build/clara/build /clara

WORKDIR /code
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "-t", "5", "app:app"]
