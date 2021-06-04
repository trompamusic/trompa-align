FROM python:3.7

#install dependencies (R, python, wget, unzip)
RUN apt-get update \
    && apt-get -y install tzdata wget git unzip make r-base \
    && rm -rf /var/lib/apt/lists/*

#download smat
RUN mkdir -p /smat
RUN wget https://midialignment.github.io/AlignmentTool_v190813.zip -O /smat/smat.zip
RUN unzip /smat/smat.zip -d /smat \
    && cd /smat/AlignmentTool_v190813 \
    && ./compile.sh \
    && mv Programs/* /usr/local/bin


RUN mkdir /code
WORKDIR /code

COPY ./scripts/install-packages.R /code/scripts/
RUN Rscript /code/scripts/install-packages.R

COPY requirements.txt /code
RUN pip install --no-cache-dir -r requirements.txt

COPY . /code
