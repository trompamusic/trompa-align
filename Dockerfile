FROM python:3.11

#install dependencies (R, python, wget, unzip)
RUN apt-get update \
    && apt-get -y install ffmpeg fluidsynth fluid-soundfont-gm \
    fluid-soundfont-gs tzdata wget git unzip make r-base \
    libharfbuzz-dev libfribidi-dev \
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

COPY requirements.txt /code
RUN --mount=type=cache,target=/root/.cache pip install -r requirements.txt

COPY . /code
