FROM nikolaik/python-nodejs:python3.13-nodejs24 AS base

ENV UV_LINK_MODE=copy \
  UV_COMPILE_BYTECODE=1 \
  UV_PYTHON_DOWNLOADS=never \
  UV_NO_SYNC=1

ENV PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.9.15 /uv /uvx /bin/

#install dependencies (R, python, wget, unzip)
RUN apt-get update \
    && apt-get -y install ffmpeg fluidsynth fluid-soundfont-gm \
    fluid-soundfont-gs tzdata wget git unzip make r-base \
    libharfbuzz-dev libfribidi-dev less \
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


RUN mkdir /code
WORKDIR /code

COPY ./install-packages.R /code
RUN Rscript /code/install-packages.R

COPY pyproject.toml uv.lock /code/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

ENV PATH="/code/.venv/bin:$PATH"

COPY . /code

FROM base AS production

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --group prod

WORKDIR /clara
ARG CLARA_BRANCH=main
RUN git clone -b $CLARA_BRANCH https://github.com/trompamusic/clara.git
WORKDIR /clara/clara
RUN --mount=type=cache,target=/root/.npm npm ci
RUN --mount=type=cache,target=/root/.npm npm run build

WORKDIR /code
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "-t", "5", "app:app"]
